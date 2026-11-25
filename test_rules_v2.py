import unittest
from dataclasses import replace
from datetime import datetime, timezone

from access_change import (Change, ChannelCheck, Coverage, Event, Feature, Incident,
                           Outcome, Registry, Report, Review, Statement,
                           assess_coverage, assess_incident, evaluate, evaluate_incident, review_is_current)

DEFAULT = object()


def at(hour):
    return datetime(2027, 5, 1, hour, tzinfo=timezone.utc)


class RulesV2Tests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry(("V1", "V2"), (Feature("F1", "V1"), Feature("F2", "V1"), Feature("F3", "V2")))
        self.event = Event("E", "O", "V1", at(10), at(12), 1)
        self.statement = Statement("S", "E", "O", "V1", "F1", "available", 1, "event")
        self.change = Change("C", 1, "V1", "F1", "unavailable", at(9), at(13))

    def run_case(self, event=DEFAULT, statement=DEFAULT, change=DEFAULT, registry=DEFAULT):
        return evaluate(self.event if event is DEFAULT else event,
                        self.statement if statement is DEFAULT else statement,
                        self.change if change is DEFAULT else change,
                        organiser_id="O", registry=self.registry if registry is DEFAULT else registry)

    def test_registry_and_precedence(self):
        cases = [
            (self.statement, self.change, self.registry, Outcome.REVIEW, "availability_changed"),
            (replace(self.statement, feature_id="F2"), self.change, self.registry, Outcome.NO_REVIEW, "different_feature"),
            (replace(self.statement, feature_id="missing"), self.change, self.registry, Outcome.NEEDS_INFORMATION, "unknown_feature"),
            (replace(self.statement, feature_id="F3"), self.change, self.registry, Outcome.NEEDS_INFORMATION, "feature_venue_mismatch"),
            (self.statement, replace(self.change, feature_id="missing", starts_at=None), self.registry, Outcome.NEEDS_INFORMATION, "unknown_feature"),
            (self.statement, self.change, Registry(("V1",), (Feature("F1", "V1"), Feature("F1", "V1"))), Outcome.NEEDS_INFORMATION, "invalid_registry"),
            (self.statement, self.change, Registry(("V1",), None), Outcome.NEEDS_INFORMATION, "invalid_registry"),
        ]
        for statement, change, registry, expected, reason in cases:
            with self.subTest(reason=reason):
                result = self.run_case(statement=statement, change=change, registry=registry)
                self.assertEqual((result.outcome, result.code), (expected, reason))
        self.assertEqual(self.run_case(registry=None).code, "invalid_registry")
        self.assertEqual(self.run_case(statement=None).code, "no_statement")

    def test_applicability(self):
        cases = [
            (replace(self.statement, applicability="unknown"), self.change, Outcome.NEEDS_INFORMATION, "unknown_applicability"),
            (replace(self.statement, applicability="interval", applies_from=at(10), applies_until=at(11)), replace(self.change, starts_at=at(11)), Outcome.NO_REVIEW, "outside_statement_interval"),
            (replace(self.statement, applicability="interval", applies_from=at(10), applies_until=at(11)), self.change, Outcome.REVIEW, "availability_changed"),
            (replace(self.statement, applicability="interval", applies_from=at(11), applies_until=at(10)), self.change, Outcome.NEEDS_INFORMATION, "invalid_applicability"),
        ]
        for statement, change, outcome, code in cases:
            with self.subTest(code=code):
                result = self.run_case(statement=statement, change=change)
                self.assertEqual((result.outcome, result.code), (outcome, code))

    def test_claim_status_table(self):
        table = {
            "available": {"available": (Outcome.NO_REVIEW, "states_agree"), "unavailable": (Outcome.REVIEW, "availability_changed"), "unknown": (Outcome.REVIEW, "availability_changed")},
            "unavailable": {"available": (Outcome.REVIEW, "availability_changed"), "unavailable": (Outcome.NO_REVIEW, "states_agree"), "unknown": (Outcome.NEEDS_INFORMATION, "unknown_status")},
            "conditional": {status: (Outcome.NEEDS_INFORMATION, "unclear_claim") for status in ("available", "unavailable", "unknown")},
            "unknown": {status: (Outcome.NEEDS_INFORMATION, "unclear_claim") for status in ("available", "unavailable", "unknown")},
        }
        for claim, statuses in table.items():
            for status, expected in statuses.items():
                with self.subTest(claim=claim, status=status):
                    actual = self.run_case(statement=replace(self.statement, claim=claim), change=replace(self.change, status=status))
                    self.assertEqual((actual.outcome, actual.code), expected)

    def test_event_revision_invalidates_review(self):
        review = Review("O", "S", "C", 1, 1, "E", 1)
        self.assertTrue(review_is_current(review, self.event, self.statement, self.change, organiser_id="O"))
        self.assertFalse(review_is_current(review, replace(self.event, revision=2, starts_at=at(11)), self.statement, self.change, organiser_id="O"))
        self.assertFalse(review_is_current(review, replace(self.event, id="E2"), replace(self.statement, event_id="E2"), self.change, organiser_id="O"))

    def test_coverage(self):
        coverage = Coverage("E", "O", ("page", "ticket"), (ChannelCheck("page", "checked_with_statement"), ChannelCheck("ticket", "unchecked")))
        self.assertEqual(assess_coverage(coverage, self.event, organiser_id="O").code, "coverage_incomplete")
        complete = replace(coverage, checks=(ChannelCheck("page", "checked_with_statement"), ChannelCheck("ticket", "checked_no_statement")))
        self.assertEqual(assess_coverage(complete, self.event, organiser_id="O").code, "coverage_recorded")
        self.assertEqual(assess_coverage(replace(coverage, expected_channels=(), checks=()), self.event, organiser_id="O").code, "coverage_unknown")
        self.assertEqual(assess_coverage(replace(coverage, expected_channels=()), self.event, organiser_id="O").code, "invalid_coverage")
        self.assertEqual(assess_coverage(replace(coverage, checks=None), self.event, organiser_id="O").code, "coverage_unknown")
        self.assertEqual(assess_coverage(None, self.event, organiser_id="O").code, "coverage_unknown")
        self.assertEqual(assess_coverage(replace(coverage, event_id="wrong", checks=None), self.event, organiser_id="O").code, "invalid_coverage")
        self.assertEqual(assess_coverage(replace(coverage, checks=(ChannelCheck("page", "checked_with_statement"), ChannelCheck("page", "unchecked"))), self.event, organiser_id="O").code, "invalid_coverage")
        with self.assertRaises(PermissionError):
            assess_coverage(coverage, self.event, organiser_id="other")

    def test_incident_conflicts_and_explicit_supersession(self):
        incident = Incident("I", "V1", "F1")
        outage = Report("R1", "I", "unavailable", at(9), at(13), "venue", at(8), "active")
        self.assertEqual(assess_incident(None, (outage,), self.registry).code, "invalid_incident")
        restoration = Report("R2", "I", "available", at(11), None, "organiser", at(10), "active")
        self.assertEqual(assess_incident(incident, (outage, restoration), self.registry).code, "conflicting_reports")
        self.assertEqual(assess_incident(incident, (outage, replace(restoration, starts_at=at(13))), self.registry).code, "reports_recorded")
        self.assertEqual(assess_incident(incident, (replace(outage, lifecycle="superseded"), restoration), self.registry).code, "invalid_lifecycle")
        closed = replace(outage, lifecycle="superseded", actor="person", reason="confirmed replacement")
        self.assertEqual(assess_incident(incident, (closed, restoration), self.registry).code, "reports_recorded")
        self.assertEqual(assess_incident(incident, (closed,), self.registry).code, "no_active_reports")
        self.assertEqual(assess_incident(incident, (outage, replace(restoration, status="unknown")), self.registry).code, "conflicting_reports")

    def test_incident_gate(self):
        incident = Incident("I", "V1", "F1")
        change = replace(self.change, status="available")
        available = Report("C", "I", "available", at(9), at(13), "venue", at(8), "active")
        outage = Report("R2", "I", "unavailable", at(10), at(12), "organiser", at(9), "active")
        result = evaluate_incident(self.event, self.statement, change, incident, (available, outage), organiser_id="O", registry=self.registry)
        self.assertEqual((result.outcome, result.code), (Outcome.NEEDS_INFORMATION, "conflicting_reports"))
        result = evaluate_incident(self.event, self.statement, change, incident, (available,), organiser_id="O", registry=self.registry)
        self.assertEqual((result.outcome, result.code), (Outcome.NO_REVIEW, "states_agree"))
        result = evaluate_incident(self.event, self.statement, replace(change, status="unavailable"), incident, (available,), organiser_id="O", registry=self.registry)
        self.assertEqual(result.code, "invalid_report_link")


if __name__ == "__main__":
    unittest.main()
