"""Local interface for reviewing fictional event-access records."""

from __future__ import annotations

import html
import secrets
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from access_change import ChannelCheck, Coverage, Event, Feature, Incident, Registry, Report, Statement
from incident_assessment import assess_event


ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
TICKET_CHOICES = {
    "unchecked": "Not checked",
    "none": "Checked: no lift statement",
    "available": "Checked: lift available",
    "unavailable": "Checked: lift unavailable",
}
STATUS_CHOICES = {"unavailable": "Unavailable", "unknown": "Unknown", "available": "Available"}
END_CHOICES = {"16": "16:00 UTC", "unknown": "Not confirmed"}
DEFAULTS = {"status": "unavailable", "end": "16", "workshop": "unchecked", "talk": "none"}


def at(hour: int) -> datetime:
    return datetime(2027, 5, 1, hour, tzinfo=timezone.utc)


def options(values: dict[str, str], current: str) -> str:
    return "".join(f'<option value="{html.escape(key)}"{ " selected" if key == current else ""}>{html.escape(label)}</option>'
                   for key, label in values.items())


def validate(form: dict[str, list[str]]) -> dict[str, str]:
    valid = {"status": STATUS_CHOICES, "end": END_CHOICES, "workshop": TICKET_CHOICES, "talk": TICKET_CHOICES}
    if any(len(form.get(key, [])) != 1 or form[key][0] not in choices for key, choices in valid.items()):
        raise ValueError("Choose one of the available options for each field.")
    return {key: form[key][0] for key in valid}


def evaluate_event(event: Event, ticket: str, report: Report):
    registry = Registry(("venue",), (Feature("lift", "venue"),))
    incident = Incident("incident", "venue", "lift")
    statements = [Statement("page", event.id, "organiser", "venue", "lift", "available", applicability="event", channel="Event page")]
    if ticket in ("available", "unavailable"):
        statements.append(Statement("ticket", event.id, "organiser", "venue", "lift", ticket, applicability="event", channel="Ticket"))
    state = "unchecked" if ticket == "unchecked" else "checked_no_statement" if ticket == "none" else "checked_with_statement"
    coverage = Coverage(event.id, "organiser", ("Event page", "Ticket"),
                        (ChannelCheck("Event page", "checked_with_statement"), ChannelCheck("Ticket", state)))
    return assess_event(event, tuple(statements), incident, (report,), registry, coverage, organiser_id="organiser")


def event_section(title: str, event: Event, ticket: str, report: Report) -> str:
    result = evaluate_event(event, ticket, report)
    items = []
    for statement in result.statements:
        pairs = [pair for pair in result.pairs if pair.statement_id == statement.statement_id]
        if statement.review:
            label, css = "Review needed", "review"
        elif statement.needs_information or not pairs:
            label, css = "Information needed", "unknown"
        else:
            label, css = "No review prompted", "clear"
        reason = pairs[0].result.reason if len(pairs) == 1 else "The statement needs a closer look"
        claim = "Available" if statement.statement_id == "page" else ticket.title()
        items.append(f'<li class="statement"><div><span class="channel">{html.escape(statement.channel or "Unknown channel")}</span>'
                     f'<p>Lift: {html.escape(claim)}</p></div><div class="finding"><span class="badge {css}">{label}</span>'
                     f'<p>{html.escape(reason)}.</p></div></li>')
    coverage = "Ticket marked not checked" if result.coverage.code == "coverage_incomplete" else "Page and ticket marked checked"
    issues = "".join(f"<li>{html.escape(issue.reason)}</li>" for issue in result.issues)
    issue_html = f'<ul class="issues">{issues}</ul>' if issues else ""
    return (f'<section class="event" aria-labelledby="{html.escape(event.id)}-title">'
            f'<div class="event-heading"><div><h2 id="{html.escape(event.id)}-title">{html.escape(title)}</h2>'
            f'<p>1 May 2027 <span aria-hidden="true">&middot;</span> {event.starts_at:%H:%M} to {event.ends_at:%H:%M} UTC</p></div>'
            f'<span class="coverage">{html.escape(coverage)}</span></div><ul class="statements">{"".join(items)}</ul>{issue_html}</section>')


def page(values: dict[str, str], token: str, error: str = "") -> bytes:
    report = Report("report", "incident", values["status"], at(12), None if values["end"] == "unknown" else at(16),
                    "venue contact", at(11), "active")
    workshop = event_section("Afternoon workshop", Event("workshop", "organiser", "venue", at(13), at(15)), values["workshop"], report)
    talk = event_section("Evening talk", Event("talk", "organiser", "venue", at(18), at(20)), values["talk"], report)
    error_html = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Access changes</title><link rel="stylesheet" href="/style.css"></head><body>
<header class="top"><div class="top-inner"><div class="brand-mark" aria-hidden="true">A</div><div><p class="brand">Access changes</p><p class="subbrand">Organiser workspace</p></div><span class="sample">Fictional records</span></div></header>
<main><div class="heading"><div><p class="eyebrow">Venue report</p><h1>Lift at Riverside Hall</h1><p class="subtitle">Reported 1 May 2027, 11:00 UTC</p></div><span class="reference">2 events</span></div>
<p class="session-note">Selections apply to this assessment and are not saved.</p>
<form method="post" action="/"><input type="hidden" name="token" value="{html.escape(token, quote=True)}">
<section class="controls" aria-labelledby="report-heading"><div class="section-heading"><h2 id="report-heading">Reported change</h2><span>From 12:00 UTC</span></div>
{error_html}<div class="fields"><label>Lift status<select name="status">{options(STATUS_CHOICES, values["status"])}</select></label>
<label>Reported end<select name="end">{options(END_CHOICES, values["end"])}</select></label></div></section>
<section class="ticket-controls" aria-labelledby="ticket-heading"><div class="section-heading"><h2 id="ticket-heading">Ticket checks</h2></div><div class="fields">
<label>Afternoon workshop<select name="workshop">{options(TICKET_CHOICES, values["workshop"])}</select></label>
<label>Evening talk<select name="talk">{options(TICKET_CHOICES, values["talk"])}</select></label></div>
<div class="actions"><button type="submit">Update assessment</button></div></section></form>
<div class="results-heading"><div><p class="eyebrow">Statements and coverage</p><h2>Event assessments</h2></div></div>{workshop}{talk}
</main></body></html>'''
    return document.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def respond(self, status: HTTPStatus, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self) -> bool:
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def do_GET(self):
        if not self.valid_host():
            return self.respond(HTTPStatus.FORBIDDEN, b"Invalid host", "text/plain; charset=utf-8")
        if self.path == "/":
            return self.respond(HTTPStatus.OK, page(DEFAULTS, TOKEN), "text/html; charset=utf-8")
        if self.path == "/style.css":
            return self.respond(HTTPStatus.OK, (ROOT / "workflow.css").read_bytes(), "text/css; charset=utf-8")
        self.respond(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if not self.valid_host() or self.path != "/":
            return self.respond(HTTPStatus.FORBIDDEN, b"Invalid request", "text/plain; charset=utf-8")
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            return self.respond(HTTPStatus.FORBIDDEN, b"Invalid origin", "text/plain; charset=utf-8")
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            return self.respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, b"Invalid content type", "text/plain; charset=utf-8")
        try:
            size = int(self.headers.get("Content-Length", ""))
            if size < 0 or size > 4096:
                raise ValueError
            form = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True, max_num_fields=10)
        except (ValueError, UnicodeDecodeError):
            return self.respond(HTTPStatus.BAD_REQUEST, b"Invalid form", "text/plain; charset=utf-8")
        tokens = form.get("token", [])
        if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], TOKEN):
            return self.respond(HTTPStatus.FORBIDDEN, b"Invalid token", "text/plain; charset=utf-8")
        try:
            values = validate(form)
        except ValueError as exc:
            return self.respond(HTTPStatus.BAD_REQUEST, page(DEFAULTS, TOKEN, str(exc)), "text/html; charset=utf-8")
        self.respond(HTTPStatus.OK, page(values, TOKEN), "text/html; charset=utf-8")


def serve(port: int = 8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Local URL: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    serve(parser.parse_args().port)
