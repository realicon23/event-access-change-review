import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from access_change import Change, Event, Feature, Outcome, Registry, Review, Statement, evaluate as evaluate_registered, review_is_current


REGISTRY = Registry(("V1", "V2"), (Feature("L1", "V1"), Feature("L2", "V1"), Feature("E1", "V1"), Feature("L3", "V2")))


def evaluate(event, statement, change, *, organiser_id):
    return evaluate_registered(event, statement, change, organiser_id=organiser_id, registry=REGISTRY)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 12, 5, hour, minute, tzinfo=timezone.utc)


class AccessChangeTests(unittest.TestCase):
    def setUp(self):
        self.event = Event("A", "O1", "V1", at(10), at(12))
        self.statement = Statement("S1", "A", "O1", "V1", "L1", "available", applicability="event")
        self.change = Change("C1", 1, "V1", "L1", "unavailable", at(9), at(13))

    def check(self, event=None, statement=None, change=None):
        return evaluate(event or self.event, statement or self.statement, change or self.change, organiser_id="O1").outcome

    def test_fictional_reference_cases(self):
        e, s, c = self.event, self.statement, self.change
        cases = [
            ("T01", e, s, c, Outcome.REVIEW),
            ("T02", replace(e, id="B"), replace(s, event_id="B"), c, Outcome.REVIEW),
            ("T03", replace(e, id="C"), replace(s, event_id="C", feature_id="L2"), c, Outcome.NO_REVIEW),
            ("T04", replace(e, id="D", venue_id="V2"), replace(s, event_id="D", venue_id="V2", feature_id="L3"), c, Outcome.NO_REVIEW),
            ("T05", e, s, replace(c, starts_at=at(8), ends_at=at(10)), Outcome.NO_REVIEW),
            ("T06", e, s, replace(c, starts_at=at(12), ends_at=at(13)), Outcome.NO_REVIEW),
            ("T07", e, s, replace(c, ends_at=None), Outcome.REVIEW),
            ("T08", e, replace(s, claim="unavailable"), c, Outcome.NO_REVIEW),
            ("T09", e, replace(s, claim="unavailable"), replace(c, status="available"), Outcome.REVIEW),
            ("T10", e, replace(s, claim="conditional"), c, Outcome.NEEDS_INFORMATION),
            ("T11", e, replace(s, claim="unknown"), c, Outcome.NEEDS_INFORMATION),
            ("T12", e, s, replace(c, status="unknown"), Outcome.REVIEW),
            ("T13", e, replace(s, feature_id=None), c, Outcome.NEEDS_INFORMATION),
            ("T14", e, s, replace(c, starts_at=None), Outcome.NEEDS_INFORMATION),
            ("T15", e, replace(s, feature_id="E1"), c, Outcome.NO_REVIEW),
            ("T16", e, s, replace(c, status="available"), Outcome.NO_REVIEW),
            ("T17", e, None, c, Outcome.COVERAGE_UNKNOWN),
            ("T18", e, s, replace(c, starts_at=at(13), ends_at=at(9)), Outcome.NEEDS_INFORMATION),
        ]
        codes = ["availability_changed", "availability_changed", "different_feature", "different_venue",
                 "outside_event", "outside_event", "availability_changed", "states_agree",
                 "availability_changed", "unclear_claim", "unclear_claim", "availability_changed",
                 "unknown_feature", "invalid_interval", "different_feature", "states_agree",
                 "no_statement", "invalid_interval"]
        for (case_id, event, statement, change, expected), code in zip(cases, codes):
            with self.subTest(case=case_id):
                actual = evaluate(event, statement, change, organiser_id="O1")
                self.assertEqual(actual.outcome, expected)
                self.assertEqual(actual.code, code)

    def test_unrelated_venue_without_a_statement(self):
        result = evaluate(self.event, None, replace(self.change, venue_id="V2", feature_id="L3"), organiser_id="O1")
        self.assertEqual(result.outcome, Outcome.NO_REVIEW)

    def test_one_second_of_overlap_at_boundaries(self):
        for change in (replace(self.change, ends_at=at(10) + timedelta(seconds=1)),
                       replace(self.change, starts_at=at(12) - timedelta(seconds=1))):
            with self.subTest(change=change):
                self.assertEqual(self.check(change=change), Outcome.REVIEW)

    def test_timezones_are_compared_as_instants(self):
        plus_one = timezone(timedelta(hours=1))
        event = replace(self.event, starts_at=at(10).astimezone(plus_one), ends_at=at(12).astimezone(plus_one))
        self.assertEqual(self.check(event=event), Outcome.REVIEW)

    def test_naive_missing_and_reversed_times_need_information(self):
        events = [replace(self.event, starts_at=None), replace(self.event, ends_at=None),
                  replace(self.event, starts_at=at(12), ends_at=at(10)),
                  replace(self.event, starts_at=at(10).replace(tzinfo=None))]
        for event in events:
            with self.subTest(event=event):
                self.assertEqual(self.check(event=event), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(change=replace(self.change, ends_at=at(13).replace(tzinfo=None))), Outcome.NEEDS_INFORMATION)

    def test_missing_identity_and_invalid_values_need_information(self):
        self.assertEqual(self.check(statement=replace(self.statement, event_id="other")), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(statement=replace(self.statement, venue_id="V2")), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(statement=replace(self.statement, feature_id="  ")), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(statement=replace(self.statement, claim="accessible")), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(change=replace(self.change, status="repaired")), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(change=replace(self.change, venue_id=None)), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(statement=replace(self.statement, claim="unavailable"), change=replace(self.change, status="unknown")), Outcome.NEEDS_INFORMATION)

    def test_scope_mismatch_is_refused(self):
        with self.assertRaises(PermissionError):
            evaluate(self.event, self.statement, self.change, organiser_id="O2")
        with self.assertRaises(PermissionError):
            evaluate(self.event, replace(self.statement, organiser_id="O2"), self.change, organiser_id="O1")

    def test_review_covers_one_revision_and_one_statement(self):
        review = Review("O1", "S1", "C1", 1, 1, "A", 1)
        self.assertTrue(review_is_current(review, self.event, self.statement, self.change, organiser_id="O1"))
        self.assertFalse(review_is_current(review, self.event, self.statement, replace(self.change, revision=2), organiser_id="O1"))
        self.assertFalse(review_is_current(review, self.event, replace(self.statement, id="S2"), self.change, organiser_id="O1"))
        self.assertFalse(review_is_current(review, self.event, self.statement, replace(self.change, id="C2"), organiser_id="O1"))
        self.assertFalse(review_is_current(review, self.event, self.statement, replace(self.change, revision=True), organiser_id="O1"))
        self.assertFalse(review_is_current(replace(review, change_revision=True), self.event, self.statement, self.change, organiser_id="O1"))
        self.assertFalse(review_is_current(review, self.event, replace(self.statement, revision=2), self.change, organiser_id="O1"))
        self.assertFalse(review_is_current(replace(review, statement_revision=True), self.event, self.statement, self.change, organiser_id="O1"))
        self.assertFalse(review_is_current(review, self.event, replace(self.statement, feature_id="L2"), self.change, organiser_id="O1"))
        self.assertFalse(review_is_current(review, self.event, replace(self.statement, venue_id="V2"), self.change, organiser_id="O1"))
        with self.assertRaises(PermissionError):
            review_is_current(replace(review, organiser_id="O2"), self.event, self.statement, self.change, organiser_id="O1")

    def test_invalid_revisions_need_information(self):
        for value in (0, -1, True, "1", None):
            with self.subTest(value=value):
                self.assertEqual(self.check(change=replace(self.change, revision=value)), Outcome.NEEDS_INFORMATION)
                self.assertEqual(self.check(statement=replace(self.statement, revision=value)), Outcome.NEEDS_INFORMATION)

    def test_contradictory_links_are_checked_before_unrelated_venue(self):
        event = replace(self.event, venue_id="V2")
        self.assertEqual(self.check(event=event), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(statement=replace(self.statement, event_id="other"),
                                    change=replace(self.change, venue_id="V2")), Outcome.NEEDS_INFORMATION)
        self.assertEqual(self.check(statement=replace(self.statement, venue_id=None),
                                    change=replace(self.change, venue_id="V2")), Outcome.NEEDS_INFORMATION)

    def test_non_string_claims_and_statuses_need_information(self):
        for value in ([], {}, None, 1, True):
            with self.subTest(value=value):
                self.assertEqual(self.check(statement=replace(self.statement, claim=value)), Outcome.NEEDS_INFORMATION)
                self.assertEqual(self.check(change=replace(self.change, status=value)), Outcome.NEEDS_INFORMATION)


if __name__ == "__main__":
    unittest.main()
