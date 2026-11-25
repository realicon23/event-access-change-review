"""Assess a supplied incident report set against event statements."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone

from access_change import (Change, Coverage, Event, Incident, Outcome, Registry, Report, Result, Statement,
                           _feature_status, _registry_valid, _utc, _valid_id, _valid_revision,
                           assess_coverage, assess_incident, evaluate)


@dataclass(frozen=True)
class PairResult:
    statement_id: str
    report_id: str
    result: Result
    report_position: int


@dataclass(frozen=True)
class StatementResult:
    statement_id: str
    review: bool
    needs_information: bool
    channel: str | None


@dataclass(frozen=True)
class Assessment:
    pairs: tuple[PairResult, ...]
    statements: tuple[StatementResult, ...]
    issues: tuple[Result, ...]
    coverage: Result
    needs_information: bool


@dataclass(frozen=True)
class InputSnapshot:
    values: tuple


def _issue(code: str, reason: str) -> Result:
    return Result(Outcome.NEEDS_INFORMATION, reason, code)


def _scope(event: Event, statements: tuple[Statement, ...], coverage: Coverage | None, organiser_id: str) -> None:
    if not isinstance(event, Event) or not isinstance(statements, (tuple, list)) or any(not isinstance(s, Statement) for s in statements):
        raise ValueError("Event or statements are invalid")
    if not _valid_id(organiser_id) or organiser_id != event.organiser_id:
        raise PermissionError("Event is outside the organiser's scope")
    if any(s.organiser_id != organiser_id for s in statements):
        raise PermissionError("Statement is outside the organiser's scope")
    if isinstance(coverage, Coverage) and coverage.organiser_id != organiser_id:
        raise PermissionError("Coverage is outside the organiser's scope")


def _event_valid(event: Event, registry: Registry) -> bool:
    start, end = _utc(event.starts_at), _utc(event.ends_at)
    return (bool(_valid_id(event.id)) and _valid_revision(event.revision)
            and _registry_valid(registry) and _valid_id(event.venue_id)
            and event.venue_id in registry.venues and start is not None and end is not None and start < end)


def _statement_valid(statement: Statement, event: Event, registry: Registry) -> bool:
    if (not _valid_id(statement.id) or statement.event_id != event.id or not _valid_revision(statement.revision)
            or not _valid_id(statement.venue_id) or statement.venue_id != event.venue_id
            or not _registry_valid(registry) or _feature_status(registry, statement.feature_id, statement.venue_id)
            or not isinstance(statement.claim, str) or statement.claim not in {"available", "unavailable", "conditional", "unknown"}):
        return False
    if statement.applicability == "interval":
        start, end = _utc(statement.applies_from), _utc(statement.applies_until)
        return start is not None and end is not None and start < end
    return statement.applicability in ("event", "unknown") and statement.applies_from is None and statement.applies_until is None


def assess_event(event: Event, statements: tuple[Statement, ...], incident: Incident,
                 reports: tuple[Report, ...], registry: Registry, coverage: Coverage | None,
                 *, organiser_id: str) -> Assessment:
    _scope(event, statements, coverage, organiser_id)
    coverage_result = (assess_coverage(coverage, event, organiser_id=organiser_id)
                       if coverage is None or isinstance(coverage, Coverage)
                       else _issue("invalid_coverage", "Coverage record is invalid"))
    issues = []
    pairs = []
    statements_supplied = bool(statements)
    ids = [s.id for s in statements if _valid_id(s.id)]
    duplicates = {value for value in ids if ids.count(value) > 1}
    if len(ids) != len(statements) or duplicates:
        issues.append(_issue("invalid_statements", "Statement IDs are missing or duplicated"))
    statements = tuple(s for s in statements if _valid_id(s.id) and s.id not in duplicates)
    if not _event_valid(event, registry):
        issues.append(_issue("invalid_event", "Event record is invalid"))
    invalid_statement_ids = {s.id for s in statements if not _statement_valid(s, event, registry)}
    if invalid_statement_ids:
        issues.append(_issue("invalid_statement", "A statement record is invalid"))
    if any(not _valid_id(s.channel) for s in statements):
        issues.append(_issue("statement_channel_missing", "A statement has no channel link"))
    if (isinstance(coverage, Coverage) and coverage_result.code != "invalid_coverage"
            and isinstance(coverage.expected_channels, (tuple, list)) and coverage.expected_channels
            and isinstance(coverage.checks, (tuple, list))):
        channels = coverage.expected_channels
        if any(_valid_id(s.channel) and s.channel not in channels for s in statements):
            issues.append(_issue("statement_channel_unknown", "A statement channel is not in the channel inventory"))
        if any(c.state == "checked_no_statement" and any(s.channel == c.channel for s in statements) for c in coverage.checks):
            issues.append(_issue("channel_check_conflict", "A channel check conflicts with a supplied statement"))
        if not duplicates and len(ids) == len(statements) and any(c.state == "checked_with_statement" and not any(s.channel == c.channel for s in statements) for c in coverage.checks):
            issues.append(_issue("channel_statement_unmatched", "No supplied statement is linked to a checked channel"))
    if (not statements_supplied and isinstance(coverage, Coverage) and isinstance(coverage.checks, (tuple, list))
            and any(getattr(c, "state", None) == "checked_with_statement" for c in coverage.checks)):
        issues.append(_issue("coverage_statement_mismatch", "Coverage refers to a statement that was not supplied"))
    if not isinstance(reports, (tuple, list)):
        issues.append(_issue("invalid_reports", "Report set is missing or invalid"))
        reports = ()
    base = assess_incident(incident, (), registry)
    if base.code != "no_reports":
        issues.append(base)
    if not reports:
        issues.append(_issue("no_active_reports", "No active reports are recorded"))

    counts = {}
    for report in reports:
        if isinstance(report, Report) and _valid_id(report.id):
            counts[report.id] = counts.get(report.id, 0) + 1
    duplicates = {key for key, count in counts.items() if count > 1}
    if duplicates:
        issues.append(_issue("duplicate_report", "Report IDs are duplicated"))

    valid = []
    for position, report in enumerate(reports, start=1):
        checked = assess_incident(incident, (report,), registry)
        if checked.code in {"reports_recorded", "no_active_reports"}:
            if report.lifecycle == "active":
                valid.append((position, report))
        else:
            issues.append(checked)
            if isinstance(report, Report) and _valid_id(report.id):
                for statement in statements:
                    pairs.append(PairResult(statement.id, report.id, checked, position))

    if reports and not valid:
        issues.append(_issue("no_active_reports", "No valid active reports are recorded"))
    if valid:
        for index, (_, first) in enumerate(valid):
            for _, second in valid[index + 1:]:
                if first.id != second.id:
                    incident_result = assess_incident(incident, (first, second), registry)
                    if incident_result.code == "conflicting_reports" and not any(i.code == "conflicting_reports" for i in issues):
                        issues.append(incident_result)
        for statement in statements:
            for position, report in valid:
                change = Change(report.id, 1, incident.venue_id, incident.feature_id,
                                report.status, report.starts_at, report.ends_at)
                result = evaluate(event, statement, change, organiser_id=organiser_id, registry=registry)
                pairs.append(PairResult(statement.id, report.id, result, position))

    conflict = any(issue.code == "conflicting_reports" for issue in issues)
    statement_results = tuple(
        StatementResult(statement.id,
                        any(p.statement_id == statement.id and p.result.outcome == Outcome.REVIEW for p in pairs),
                        bool(issues) or statement.id in invalid_statement_ids or conflict
                        or any(p.statement_id == statement.id and p.result.outcome == Outcome.NEEDS_INFORMATION for p in pairs),
                        statement.channel)
        for statement in statements
    )
    needs = bool(issues) or any(s.needs_information for s in statement_results) or coverage_result.outcome in {Outcome.NEEDS_INFORMATION, Outcome.COVERAGE_UNKNOWN}
    return Assessment(tuple(pairs), statement_results, tuple(issues), coverage_result, needs)


def _freeze(value: object) -> object:
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if value is None or type(value) is str:
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a time zone")
        return ("datetime", value.astimezone(timezone.utc).isoformat())
    if is_dataclass(value) and not isinstance(value, type):
        return (type(value).__name__, tuple((field.name, _freeze(getattr(value, field.name))) for field in fields(value)))
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    raise ValueError("Unsupported snapshot value")


def make_snapshot(event: Event, statement: Statement, incident: Incident, reports: tuple[Report, ...],
                  registry: Registry, coverage: Coverage | None, *, organiser_id: str) -> InputSnapshot:
    _scope(event, (statement,), coverage, organiser_id)
    if statement.event_id != event.id or not _valid_id(statement.id) or not _valid_id(event.id):
        raise ValueError("Statement link is invalid")
    if not _valid_revision(event.revision) or not _valid_revision(statement.revision):
        raise ValueError("Event or statement revision is invalid")
    if not _registry_valid(registry) or not isinstance(reports, (tuple, list)):
        raise ValueError("Registry or report set is invalid")
    report_ids = [r.id for r in reports if isinstance(r, Report) and _valid_id(r.id)]
    if len(report_ids) != len(reports) or len(set(report_ids)) != len(report_ids):
        raise ValueError("Report IDs are missing or duplicated")
    assessment = assess_incident(incident, tuple(reports), registry)
    if assessment.code not in {"reports_recorded", "conflicting_reports", "no_active_reports", "no_reports"}:
        raise ValueError("Incident or report set is invalid")
    if coverage is not None and not isinstance(coverage, Coverage):
        raise ValueError("Coverage record is invalid")
    coverage_result = assess_coverage(coverage, event, organiser_id=organiser_id)
    if coverage_result.code == "invalid_coverage":
        raise ValueError("Coverage record is invalid")
    sorted_registry = Registry(tuple(sorted(registry.venues)), tuple(sorted(registry.features, key=lambda f: f.id)))
    sorted_reports = tuple(sorted(reports, key=lambda r: r.id))
    if coverage is not None and coverage.expected_channels is not None and coverage.checks is not None:
        coverage = Coverage(coverage.event_id, coverage.organiser_id, tuple(sorted(coverage.expected_channels)),
                            tuple(sorted(coverage.checks, key=lambda c: c.channel)))
    return InputSnapshot(_freeze((event, statement, sorted_registry, incident, sorted_reports, coverage)))


def snapshot_is_current(snapshot: InputSnapshot, event: Event, statement: Statement, incident: Incident,
                        reports: tuple[Report, ...], registry: Registry, coverage: Coverage | None,
                        *, organiser_id: str) -> bool:
    try:
        return snapshot == make_snapshot(event, statement, incident, reports, registry, coverage, organiser_id=organiser_id)
    except (ValueError, TypeError, OverflowError):
        return False
