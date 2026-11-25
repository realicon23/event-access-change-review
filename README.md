# Access change review

This local prototype compares registered event statements with reported changes to venue features. It identifies statements that may need review and leaves the decision to an organiser. Use fictional records for local exploration.

The inputs use a registry of venues and features. Times must include a time zone. Intervals include their start and exclude their end. A change with no end is treated as open-ended.

A review refers to specific event, statement, and change revisions. The caller must give an edited record a new revision number.

`incident_assessment` compares all supplied active reports with the event statements and reports channel coverage separately. Input snapshots can be compared with later records to check whether the supplied information has changed.

Each statement identifies its channel. Channel checks are compared with supplied statements to find missing links and inconsistent records.

Each pair result includes the report's one-based position in the supplied list. The position identifies a record in that assessment; it may change when the list is reordered.

Run the fictional cases with Python 3.9 or later:

```sh
python3 -m unittest -v
```

Run the local organiser view:

```sh
python3 workflow.py --port 8765
```

Open `http://127.0.0.1:8765/`. The view uses fictional records. Form choices are not stored; opening the page again returns the initial values.

The rules engine compares recorded statements and reports; it does not discover event pages, store reviews, or check physical access. The organiser view runs on the local machine and sends no messages.

The [rules](RULES.md) describe how comparisons and coverage checks work.

## Licence

This project is available under the [MIT licence](LICENSE).
