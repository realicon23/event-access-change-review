# Comparison rules

The registry associates each venue feature with a venue. Event statements describe a feature as available, unavailable, conditional, or unknown. Change reports record its status as available, unavailable, or unknown.

The incident assessment compares each active report with the event statements. Event and report intervals include their start and exclude their end. A report with an unconfirmed end remains open-ended.

## Statement results

When a report overlaps the event and the statement's applicable interval for the same feature, the recorded states lead to these results:

| Statement | Report | Result |
| --- | --- | --- |
| Available | Unavailable or unknown | Review |
| Unavailable | Available | Review |
| Available | Available | No review |
| Unavailable | Unavailable | No review |
| Unavailable | Unknown | Needs information |
| Conditional or unknown | Any status | Needs information |

An unresolved feature link or an invalid interval for a matching report requires information. When a report overlaps the event, an unknown statement interval also requires information. Inconsistent records and overlapping active reports with different statuses are flagged for clarification.

Each result identifies the statement and report. Duplicate report IDs are flagged, and each result includes the report's one-based position in the supplied list. Duplicate statement IDs are flagged for correction before individual results are attributed.

## Channels and snapshots

Statements link to channels such as an event page or ticket. A coverage record lists the expected channels and their check states, alongside the statement results.

An input snapshot captures the event, statement, registry, incident, reports, and coverage records for later comparison. Timestamps are represented as UTC instants. The comparison treats reordered reports, registry entries, and channel checks as unchanged when their contents stay the same.
