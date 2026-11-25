import unittest
from dataclasses import replace
from datetime import datetime, timezone

from access_change import ChannelCheck, Coverage, Event, Feature, Incident, Outcome, Registry, Report, Statement
from incident_assessment import assess_event, make_snapshot, snapshot_is_current


def at(hour):
    return datetime(2027, 5, 1, hour, tzinfo=timezone.utc)


class IncidentAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry(("V",), (Feature("F", "V"),))
        self.event = Event("E", "O", "V", at(13), at(14))
        self.statement = Statement("S", "E", "O", "V", "F", "available", applicability="event", channel="page")
        self.incident = Incident("I", "V", "F")
        self.coverage = Coverage("E", "O", ("page", "ticket"), (ChannelCheck("page", "checked_with_statement"), ChannelCheck("ticket", "unchecked")))
        self.available = Report("A", "I", "available", at(9), at(13), "venue", at(8), "active")
        self.outage = Report("B", "I", "unavailable", at(13), at(15), "venue", at(12), "active")

    def assess(self, reports, statements=None, coverage=None):
        return assess_event(self.event, (self.statement,) if statements is None else statements, self.incident,
                            reports, self.registry, self.coverage if coverage is None else coverage, organiser_id="O")

    def snapshot(self, reports=None, event=None, statement=None, registry=None, coverage=None):
        return make_snapshot(event or self.event, statement or self.statement, self.incident,
                             reports if reports is not None else (self.available, self.outage), registry or self.registry,
                             coverage or self.coverage, organiser_id="O")

    def test_all_reports_and_separate_coverage(self):
        result = self.assess((self.available, self.outage))
        self.assertEqual([(p.report_id, p.result.code) for p in result.pairs], [("A", "outside_event"), ("B", "availability_changed")])
        self.assertTrue(result.statements[0].review)
        self.assertFalse(result.statements[0].needs_information)
        self.assertEqual(result.coverage.code, "coverage_incomplete")

    def test_conflict_keeps_warning(self):
        result = self.assess((replace(self.available, ends_at=at(15)), self.outage))
        self.assertTrue(result.statements[0].review)
        self.assertTrue(result.needs_information)
        self.assertIn("conflicting_reports", [issue.code for issue in result.issues])

    def test_bad_report_does_not_hide_warning(self):
        bad = replace(self.available, starts_at=None)
        result = self.assess((bad, self.outage))
        self.assertTrue(result.statements[0].review)
        self.assertTrue(result.needs_information)
        self.assertIn("invalid_interval", [issue.code for issue in result.issues])
        self.assertEqual([pair.report_position for pair in result.pairs], [1, 2])
        malformed = replace(self.available, id=[])
        result = self.assess((malformed, self.outage))
        self.assertIn("invalid_report", [issue.code for issue in result.issues])
        self.assertTrue(result.statements[0].review)

    def test_unknown_applicability_and_review_are_both_visible(self):
        unclear = replace(self.statement, id="S2", applicability="unknown")
        result = self.assess((self.outage,), (self.statement, unclear))
        self.assertTrue(result.statements[0].review)
        self.assertTrue(result.statements[1].needs_information)
        self.assertTrue(result.needs_information)

    def test_conflict_outside_event_still_reported(self):
        before = replace(self.outage, starts_at=at(9), ends_at=at(11))
        result = self.assess((self.available, before))
        self.assertIn("conflicting_reports", [issue.code for issue in result.issues])
        self.assertFalse(result.statements[0].review)

    def test_no_active_duplicate_and_unknown_feature(self):
        closed = replace(self.outage, lifecycle="withdrawn", actor="person", reason="withdrawn")
        self.assertIn("no_active_reports", [i.code for i in self.assess((closed,)).issues])
        self.assertIn("duplicate_report", [i.code for i in self.assess((self.outage, self.outage)).issues])
        missing = replace(self.statement, feature_id="unknown")
        result = self.assess((self.outage,), (missing,))
        self.assertEqual(result.pairs[0].result.code, "unknown_feature")
        self.assertTrue(result.needs_information)

    def test_snapshot_detects_changes_and_ignores_order(self):
        snapshot = self.snapshot()
        self.assertTrue(snapshot_is_current(snapshot, self.event, self.statement, self.incident,
                                             (self.outage, self.available), self.registry, self.coverage, organiser_id="O"))
        self.assertFalse(snapshot_is_current(snapshot, self.event, self.statement, self.incident,
                                              (self.outage,), self.registry, self.coverage, organiser_id="O"))
        added = replace(self.outage, id="C", starts_at=at(15), ends_at=at(16))
        self.assertFalse(snapshot_is_current(snapshot, self.event, self.statement, self.incident,
                                              (self.outage, self.available, added), self.registry, self.coverage, organiser_id="O"))
        self.assertNotEqual(snapshot, self.snapshot(event=replace(self.event, starts_at=at(12))))
        self.assertNotEqual(snapshot, self.snapshot(statement=replace(self.statement, claim="unavailable")))
        self.assertNotEqual(snapshot, self.snapshot(coverage=replace(self.coverage, checks=())))
        self.assertNotEqual(snapshot, self.snapshot(reports=(self.available, replace(self.outage, lifecycle="withdrawn", actor="p", reason="r"))))
        self.assertNotEqual(snapshot, self.snapshot(registry=Registry(("V",), (Feature("F", "V"), Feature("F2", "V")))))
        with self.assertRaises(ValueError):
            self.snapshot(reports=(self.outage, self.outage))

    def test_snapshot_copies_mutable_inputs(self):
        features = [Feature("F", "V")]
        registry = Registry(["V"], features)
        snapshot = self.snapshot(registry=registry)
        features.append(Feature("F2", "V"))
        self.assertFalse(snapshot_is_current(snapshot, self.event, self.statement, self.incident,
                                              (self.available, self.outage), registry, self.coverage, organiser_id="O"))

    def test_scope_rejected(self):
        with self.assertRaises(PermissionError):
            assess_event(self.event, (replace(self.statement, organiser_id="other"),), self.incident,
                         (self.outage,), self.registry, self.coverage, organiser_id="O")

    def test_duplicate_reports_retain_warning_and_uncertainty(self):
        result = self.assess((self.outage, replace(self.outage, status="available")))
        self.assertIn("duplicate_report", [issue.code for issue in result.issues])
        self.assertTrue(result.statements[0].review)
        self.assertTrue(result.statements[0].needs_information)
        self.assertEqual([(p.report_id, p.report_position, p.result.code) for p in result.pairs],
                         [("B", 1, "availability_changed"), ("B", 2, "states_agree")])
        reversed_result = self.assess((replace(self.outage, status="available"), self.outage))
        self.assertEqual([(p.report_position, p.result.code) for p in reversed_result.pairs],
                         [(1, "states_agree"), (2, "availability_changed")])

    def test_invalid_revision_cannot_match_snapshot(self):
        snapshot = self.snapshot()
        changed = replace(self.event, revision=True)
        self.assertFalse(snapshot_is_current(snapshot, changed, self.statement, self.incident,
                                              (self.available, self.outage), self.registry, self.coverage, organiser_id="O"))
        with self.assertRaises(ValueError):
            self.snapshot(event=changed)
        with self.assertRaises(ValueError):
            self.snapshot(statement=replace(self.statement, revision=0))

    def test_coverage_with_no_supplied_statements(self):
        coverage = Coverage("E", "O", ("page",), (ChannelCheck("page", "checked_with_statement"),))
        result = self.assess((self.outage,), (), coverage)
        self.assertTrue(result.needs_information)
        self.assertIn("coverage_statement_mismatch", [issue.code for issue in result.issues])

    def test_duplicate_statements_not_attributed(self):
        other = replace(self.statement, claim="unavailable")
        result = self.assess((self.outage,), (self.statement, other))
        self.assertIn("invalid_statements", [issue.code for issue in result.issues])
        self.assertNotIn("coverage_statement_mismatch", [issue.code for issue in result.issues])
        self.assertEqual(result.statements, ())
        self.assertEqual(result.pairs, ())

    def test_validate_records_without_active_reports(self):
        invalid = replace(self.statement, event_id="wrong", revision=0)
        result = self.assess((), (invalid,))
        self.assertTrue(result.statements[0].needs_information)
        self.assertIn("invalid_statement", [issue.code for issue in result.issues])
        result = assess_event(replace(self.event, revision=True), (self.statement,), self.incident,
                              (), self.registry, self.coverage, organiser_id="O")
        self.assertIn("invalid_event", [issue.code for issue in result.issues])

    def test_malformed_inputs_fail_closed(self):
        result = assess_event(self.event, (self.statement,), self.incident, (self.outage,),
                              self.registry, object(), organiser_id="O")
        self.assertEqual(result.coverage.code, "invalid_coverage")
        self.assertTrue(result.needs_information)
        snapshot = self.snapshot()
        self.assertFalse(snapshot_is_current(snapshot, self.event, self.statement, self.incident,
                                              (self.available, self.outage), self.registry, object(), organiser_id="O"))
        with self.assertRaises(ValueError):
            assess_event(None, (self.statement,), self.incident, (self.outage,), self.registry, self.coverage, organiser_id="O")

    def test_statement_channel_link(self):
        result = self.assess((self.outage,))
        self.assertEqual(result.statements[0].channel, "page")
        self.assertTrue(result.statements[0].review)
        missing = self.assess((self.outage,), (replace(self.statement, channel=None),))
        self.assertTrue(missing.needs_information)
        self.assertIn("statement_channel_missing", [issue.code for issue in missing.issues])
        unknown = self.assess((self.outage,), (replace(self.statement, channel="poster"),))
        self.assertIn("statement_channel_unknown", [issue.code for issue in unknown.issues])

    def test_channel_checks_match_supplied_statements(self):
        coverage = Coverage("E", "O", ("page", "ticket"), (ChannelCheck("page", "checked_no_statement"), ChannelCheck("ticket", "checked_with_statement")))
        result = self.assess((self.outage,), coverage=coverage)
        self.assertIn("channel_check_conflict", [issue.code for issue in result.issues])
        self.assertIn("channel_statement_unmatched", [issue.code for issue in result.issues])
        self.assertTrue(result.needs_information)

    def test_unknown_outage_end_needs_later_review(self):
        later = replace(self.event, starts_at=at(18), ends_at=at(20))
        outage = replace(self.outage, ends_at=None)
        result = assess_event(later, (self.statement,), self.incident, (outage,), self.registry, self.coverage, organiser_id="O")
        self.assertTrue(result.statements[0].review)
        self.assertEqual(result.pairs[0].result.code, "availability_changed")

    def test_snapshot_changes_when_statement_channel_changes(self):
        snapshot = self.snapshot()
        changed = replace(self.statement, channel="ticket")
        self.assertFalse(snapshot_is_current(snapshot, self.event, changed, self.incident,
                                              (self.available, self.outage), self.registry, self.coverage, organiser_id="O"))


if __name__ == "__main__":
    unittest.main()
