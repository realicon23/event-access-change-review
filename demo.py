"""Show how one fictional lift outage affects two event statements."""

from datetime import datetime, timezone

from access_change import ChannelCheck, Coverage, Event, Feature, Incident, Registry, Report, Statement
from incident_assessment import assess_event


def at(hour):
    return datetime(2027, 5, 1, hour, tzinfo=timezone.utc)


def main():
    registry = Registry(("venue",), (Feature("lift", "venue"),))
    incident = Incident("incident", "venue", "lift")
    report = Report("report", "incident", "unavailable", at(12), at(16), "venue contact", at(11), "active")
    open_report = Report("report", "incident", "unavailable", at(12), None, "venue contact", at(11), "active")
    examples = (
        ("Afternoon workshop", Event("workshop", "organiser", "venue", at(13), at(15)), "unchecked", report),
        ("Evening talk, reported end", Event("talk", "organiser", "venue", at(18), at(20)), "checked_no_statement", report),
        ("Evening talk, end unknown", Event("talk", "organiser", "venue", at(18), at(20)), "checked_no_statement", open_report),
    )

    print("Fictional examples: two reports of a lift outage starting at 12:00 UTC.")
    for title, event, ticket_state, current_report in examples:
        statement = Statement("page-claim", event.id, "organiser", "venue", "lift", "available", applicability="event", channel="event page")
        coverage = Coverage(event.id, "organiser", ("event page", "ticket"),
                            (ChannelCheck("event page", "checked_with_statement"), ChannelCheck("ticket", ticket_state)))
        result = assess_event(event, (statement,), incident, (current_report,), registry, coverage, organiser_id="organiser")
        print(f"\n{title} ({event.starts_at:%H:%M} to {event.ends_at:%H:%M} UTC)")
        print("Outage end: " + (f"{current_report.ends_at:%H:%M} UTC" if current_report.ends_at else "not confirmed"))
        print(f"Statement channel: {result.statements[0].channel}")
        print("Statement: The lift is available.")
        print("Statement result: " + ("Review needed" if result.statements[0].review else "No review prompted by this report"))
        print("Reason: " + result.pairs[0].result.reason + ".")
        print("Channel checks: " + ("Ticket marked not checked." if result.coverage.code == "coverage_incomplete" else "Page and ticket marked checked."))
        if result.issues:
            print("Information needed: " + "; ".join(issue.reason for issue in result.issues) + ".")


if __name__ == "__main__":
    main()
