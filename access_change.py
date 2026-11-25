"""Compare recorded event statements with reported access changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from itertools import combinations


class Outcome(str, Enum):
    REVIEW = "review"
    NO_REVIEW = "no_review"
    NEEDS_INFORMATION = "needs_information"
    COVERAGE_UNKNOWN = "coverage_unknown"


@dataclass(frozen=True)
class Feature:
    id: str
    venue_id: str


@dataclass(frozen=True)
class Registry:
    venues: tuple[str, ...]
    features: tuple[Feature, ...]


@dataclass(frozen=True)
class Event:
    id: str
    organiser_id: str
    venue_id: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    revision: int = 1


@dataclass(frozen=True)
class Statement:
    id: str
    event_id: str
    organiser_id: str
    venue_id: str | None
    feature_id: str | None
    claim: str
    revision: int = 1
    applicability: str = "unknown"
    applies_from: datetime | None = None
    applies_until: datetime | None = None
    channel: str | None = None


@dataclass(frozen=True)
class Change:
    id: str
    revision: int
    venue_id: str | None
    feature_id: str | None
    status: str
    starts_at: datetime | None
    ends_at: datetime | None


@dataclass(frozen=True)
class Result:
    outcome: Outcome
    reason: str
    code: str


@dataclass(frozen=True)
class Review:
    organiser_id: str
    statement_id: str
    change_id: str
    change_revision: int
    statement_revision: int
    event_id: str
    event_revision: int


@dataclass(frozen=True)
class ChannelCheck:
    channel: str
    state: str


@dataclass(frozen=True)
class Coverage:
    event_id: str
    organiser_id: str
    expected_channels: tuple[str, ...]
    checks: tuple[ChannelCheck, ...]


@dataclass(frozen=True)
class Incident:
    id: str
    venue_id: str
    feature_id: str


@dataclass(frozen=True)
class Report:
    id: str
    incident_id: str
    status: str
    starts_at: datetime | None
    ends_at: datetime | None
    source: str
    recorded_at: datetime | None
    lifecycle: str
    actor: str | None = None
    reason: str | None = None


def _result(outcome: Outcome, code: str, reason: str) -> Result:
    return Result(outcome, reason, code)


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_revision(value: object) -> bool:
    return type(value) is int and value > 0


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        if value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _registry_valid(registry: Registry) -> bool:
    if (not isinstance(registry, Registry) or not isinstance(registry.venues, (tuple, list))
            or not isinstance(registry.features, (tuple, list)) or not all(_valid_id(v) for v in registry.venues)):
        return False
    if len(set(registry.venues)) != len(registry.venues):
        return False
    if not all(isinstance(f, Feature) and _valid_id(f.id) and f.venue_id in registry.venues for f in registry.features):
        return False
    ids = [feature.id for feature in registry.features]
    return len(set(ids)) == len(ids)


def _feature_status(registry: Registry, feature_id: object, venue_id: object) -> str | None:
    if not _valid_id(feature_id):
        return "unknown_feature"
    for feature in registry.features:
        if feature.id == feature_id:
            return None if feature.venue_id == venue_id else "feature_venue_mismatch"
    return "unknown_feature"


def evaluate(event: Event, statement: Statement | None, change: Change, *, organiser_id: str, registry: Registry) -> Result:
    if not _valid_id(organiser_id) or organiser_id != event.organiser_id or (statement is not None and statement.organiser_id != organiser_id):
        raise PermissionError("Record is outside the organiser's scope")
    if not _valid_id(event.id) or not _valid_id(change.id):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_id", "Event or change ID is missing")
    if not _valid_revision(event.revision) or not _valid_revision(change.revision):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_revision", "Event or change revision is invalid")
    if statement is not None:
        if not _valid_id(statement.id) or statement.event_id != event.id:
            return _result(Outcome.NEEDS_INFORMATION, "invalid_statement_link", "Statement is not linked to this event")
        if not _valid_revision(statement.revision):
            return _result(Outcome.NEEDS_INFORMATION, "invalid_revision", "Statement revision is invalid")
    if not _registry_valid(registry):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_registry", "Venue or feature registry is invalid")
    if not _valid_id(event.venue_id) or not _valid_id(change.venue_id) or event.venue_id not in registry.venues or change.venue_id not in registry.venues:
        return _result(Outcome.NEEDS_INFORMATION, "unknown_venue", "Venue link is missing or unregistered")
    if statement is not None and (not _valid_id(statement.venue_id) or statement.venue_id != event.venue_id):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_statement_venue", "Statement venue link is missing or inconsistent")
    if statement is not None:
        feature_problem = _feature_status(registry, statement.feature_id, statement.venue_id)
        if feature_problem:
            return _result(Outcome.NEEDS_INFORMATION, feature_problem, "Statement feature link is unresolved")
    feature_problem = _feature_status(registry, change.feature_id, change.venue_id)
    if feature_problem:
        return _result(Outcome.NEEDS_INFORMATION, feature_problem, "Change feature link is unresolved")
    if event.venue_id != change.venue_id:
        return _result(Outcome.NO_REVIEW, "different_venue", "Change concerns a different venue")
    if statement is None:
        return _result(Outcome.COVERAGE_UNKNOWN, "no_statement", "No statement is registered for this event")
    if statement.feature_id != change.feature_id:
        return _result(Outcome.NO_REVIEW, "different_feature", "Change concerns a different feature")
    start, end, changed = _utc(event.starts_at), _utc(event.ends_at), _utc(change.starts_at)
    changed_end = _utc(change.ends_at) if change.ends_at is not None else None
    if (start is None or end is None or changed is None or start >= end
            or (change.ends_at is not None and changed_end is None)
            or (changed_end is not None and changed >= changed_end)):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_interval", "Event or change interval is missing or invalid")
    if (changed_end is not None and changed_end <= start) or changed >= end:
        return _result(Outcome.NO_REVIEW, "outside_event", "Change does not overlap the event")
    if statement.applicability == "unknown":
        return _result(Outcome.NEEDS_INFORMATION, "unknown_applicability", "Statement applicability is unknown")
    if statement.applicability == "interval":
        applies_from, applies_until = _utc(statement.applies_from), _utc(statement.applies_until)
        if applies_from is None or applies_until is None or applies_from >= applies_until:
            return _result(Outcome.NEEDS_INFORMATION, "invalid_applicability", "Statement interval is invalid")
        if max(start, changed, applies_from) >= min(end, changed_end or end, applies_until):
            return _result(Outcome.NO_REVIEW, "outside_statement_interval", "Change does not overlap the statement interval during the event")
    elif statement.applicability != "event" or statement.applies_from is not None or statement.applies_until is not None:
        return _result(Outcome.NEEDS_INFORMATION, "invalid_applicability", "Statement applicability is invalid")
    if not isinstance(statement.claim, str) or statement.claim not in {"available", "unavailable", "unknown", "conditional"}:
        return _result(Outcome.NEEDS_INFORMATION, "invalid_claim", "Statement claim is invalid")
    if not isinstance(change.status, str) or change.status not in {"available", "unavailable", "unknown"}:
        return _result(Outcome.NEEDS_INFORMATION, "invalid_status", "Change status is invalid")
    if statement.claim in {"unknown", "conditional"}:
        return _result(Outcome.NEEDS_INFORMATION, "unclear_claim", "Statement wording needs review")
    if (statement.claim == "available" and change.status in {"unavailable", "unknown"}) or (statement.claim == "unavailable" and change.status == "available"):
        return _result(Outcome.REVIEW, "availability_changed", "The recorded statement may be out of date")
    if change.status == "unknown":
        return _result(Outcome.NEEDS_INFORMATION, "unknown_status", "Current feature status is unknown")
    return _result(Outcome.NO_REVIEW, "states_agree", "Recorded states agree")


def review_is_current(review: Review, event: Event, statement: Statement, change: Change, *, organiser_id: str) -> bool:
    if not _valid_id(organiser_id) or event.organiser_id != organiser_id or statement.organiser_id != organiser_id or review.organiser_id != organiser_id:
        raise PermissionError("Record is outside the organiser's scope")
    ids = (event.id, statement.id, statement.event_id, change.id, review.event_id, review.statement_id, review.change_id)
    revisions = (event.revision, statement.revision, change.revision, review.event_revision, review.statement_revision, review.change_revision)
    if not all(_valid_id(value) for value in ids) or not all(_valid_revision(value) for value in revisions):
        return False
    return (review.event_id == event.id == statement.event_id and review.statement_id == statement.id
            and _valid_id(event.venue_id) and event.venue_id == statement.venue_id == change.venue_id
            and _valid_id(statement.feature_id) and statement.feature_id == change.feature_id
            and review.change_id == change.id and review.event_revision == event.revision
            and review.statement_revision == statement.revision and review.change_revision == change.revision)


def assess_coverage(coverage: Coverage, event: Event, *, organiser_id: str) -> Result:
    if not _valid_id(organiser_id) or organiser_id != event.organiser_id:
        raise PermissionError("Record is outside the organiser's scope")
    if coverage is None:
        return _result(Outcome.COVERAGE_UNKNOWN, "coverage_unknown", "Coverage record is unknown")
    if coverage.organiser_id != organiser_id:
        raise PermissionError("Record is outside the organiser's scope")
    channels = coverage.expected_channels
    checks = coverage.checks
    if coverage.event_id != event.id or not _valid_id(event.id):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_coverage", "Coverage record is invalid")
    if channels is None or checks is None:
        return _result(Outcome.COVERAGE_UNKNOWN, "coverage_unknown", "Expected channels or checks are unknown")
    if not isinstance(channels, (tuple, list)) or not isinstance(checks, (tuple, list)):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_coverage", "Coverage record is invalid")
    if not all(_valid_id(channel) for channel in channels):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_coverage", "Coverage record is invalid")
    if len(set(channels)) != len(channels) or any(not isinstance(c, ChannelCheck) or not _valid_id(c.channel) or not isinstance(c.state, str) or c.state not in {"unchecked", "checked_no_statement", "checked_with_statement"} for c in checks):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_coverage", "Coverage record is invalid")
    names = [check.channel for check in checks]
    if len(set(names)) != len(names) or any(name not in channels for name in names):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_coverage", "Coverage record is invalid")
    if not channels:
        return _result(Outcome.COVERAGE_UNKNOWN, "coverage_unknown", "Expected channels are unknown")
    if len(checks) != len(channels) or any(c.state == "unchecked" for c in checks):
        return _result(Outcome.COVERAGE_UNKNOWN, "coverage_incomplete", "Some expected channels have not been checked")
    return _result(Outcome.NO_REVIEW, "coverage_recorded", "Expected channels have recorded checks")


def assess_incident(incident: Incident, reports: tuple[Report, ...], registry: Registry) -> Result:
    if not _registry_valid(registry):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_registry", "Venue or feature registry is invalid")
    if not isinstance(incident, Incident) or not _valid_id(incident.id) or incident.venue_id not in registry.venues:
        return _result(Outcome.NEEDS_INFORMATION, "invalid_incident", "Incident link is invalid")
    feature_problem = _feature_status(registry, incident.feature_id, incident.venue_id)
    if feature_problem:
        return _result(Outcome.NEEDS_INFORMATION, feature_problem, "Incident feature link is unresolved")
    if not reports:
        return _result(Outcome.NEEDS_INFORMATION, "no_reports", "No reports are recorded")
    seen, active = set(), []
    for report in reports:
        if not isinstance(report, Report) or not _valid_id(report.id) or report.id in seen or report.incident_id != incident.id or not _valid_id(report.source) or _utc(report.recorded_at) is None:
            return _result(Outcome.NEEDS_INFORMATION, "invalid_report", "Report identity or source is invalid")
        seen.add(report.id)
        if not isinstance(report.status, str) or report.status not in {"available", "unavailable", "unknown"}:
            return _result(Outcome.NEEDS_INFORMATION, "invalid_status", "Report status is invalid")
        if not isinstance(report.lifecycle, str) or report.lifecycle not in {"active", "superseded", "withdrawn"} or (report.lifecycle != "active" and (not _valid_id(report.actor) or not _valid_id(report.reason))):
            return _result(Outcome.NEEDS_INFORMATION, "invalid_lifecycle", "Report lifecycle decision is invalid")
        start = _utc(report.starts_at)
        end = _utc(report.ends_at) if report.ends_at is not None else None
        if start is None or (report.ends_at is not None and end is None) or (end is not None and start >= end):
            return _result(Outcome.NEEDS_INFORMATION, "invalid_interval", "Report interval is invalid")
        if report.lifecycle == "active":
            active.append((report, start, end))
    if not active:
        return _result(Outcome.NEEDS_INFORMATION, "no_active_reports", "No active reports are recorded")
    for (first, start_a, end_a), (second, start_b, end_b) in combinations(active, 2):
        if first.status != second.status and (end_a is None or start_b < end_a) and (end_b is None or start_a < end_b):
            return _result(Outcome.NEEDS_INFORMATION, "conflicting_reports", "Overlapping active reports have different statuses")
    return _result(Outcome.NO_REVIEW, "reports_recorded", "Report records have no detected conflict")


def evaluate_incident(event: Event, statement: Statement | None, change: Change, incident: Incident,
                      reports: tuple[Report, ...], *, organiser_id: str, registry: Registry) -> Result:
    if not _valid_id(organiser_id) or event.organiser_id != organiser_id or (statement is not None and statement.organiser_id != organiser_id):
        raise PermissionError("Record is outside the organiser's scope")
    incident_result = assess_incident(incident, reports, registry)
    if incident_result.outcome != Outcome.NO_REVIEW:
        return incident_result
    if incident.venue_id != change.venue_id or incident.feature_id != change.feature_id:
        return _result(Outcome.NEEDS_INFORMATION, "invalid_incident_link", "Change and incident links differ")
    matches = [report for report in reports if report.id == change.id and report.lifecycle == "active"]
    if (len(matches) != 1 or matches[0].status != change.status
            or _utc(matches[0].starts_at) != _utc(change.starts_at)
            or (matches[0].ends_at is None) != (change.ends_at is None)
            or (change.ends_at is not None and _utc(matches[0].ends_at) != _utc(change.ends_at))):
        return _result(Outcome.NEEDS_INFORMATION, "invalid_report_link", "Change does not match an active report")
    return evaluate(event, statement, change, organiser_id=organiser_id, registry=registry)
