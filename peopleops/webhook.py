"""Webhook receiver logic for Ashby-style events (the HTTP wrapper is in server.py).

Ashby's real scheme (developers.ashbyhq.com, "Authenticating Webhooks"):
  * POST with a JSON body shaped like {"action": "<event name>", "data": {...}}
  * header  Ashby-Signature: sha256=<hex HMAC-SHA256 of the raw body, keyed with your secret token>
  * no timestamp in the signature, so replay defence = our own dedupe by event id.

ASSUMPTIONS (could not be verified against a live Ashby account; all in this one file):
  * the event id is in `webhookActionId` (we fall back to a hash of the body if absent);
  * the hire payload fields read in `extract_hire_fields` follow the documented candidateHire /
    applicationUpdate shapes. If your payload differs, change ONLY that function.

What we do on a hire event:
  verify signature -> dedupe -> keep only the fields we need (data minimisation: any offer
  salary in the payload is dropped, never stored) -> create the employee in the HRIS ->
  build the onboarding plan -> QUEUE (not execute) the IT ticket, welcome post and day-1 check-in.
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from . import approvals, audit, onboarding, permissions
from .security import sign, verify_signature
from .tools import run_tool

TEAM_NAMES = {"engineering", "product", "design", "sales", "customer success", "marketing", "people", "finance",
              "it & security", "operations"}


def sample_hire_event(event_id="evt-hire-0001", name="Riley Quinn", email="riley.quinn@example.com",
                      job="Senior Software Engineer", department="Engineering", location="London", start_date=None):
    """A realistic, SYNTHETIC candidateHire event. Includes an offer salary on purpose, to show it is dropped."""
    start = start_date or (date.today() + timedelta(days=14)).isoformat()
    return {"action": "candidateHire", "webhookActionId": event_id,
            "data": {"application": {"id": "app-9001", "status": "Hired",
                                     "candidate": {"id": "cand-9001", "name": name, "primaryEmailAddress": {"value": email}},
                                     "job": {"id": "job-77", "title": job, "departmentName": department, "locationName": location}},
                     "offer": {"startDate": start, "salary": {"currencyCode": "USD", "value": 185000}}}}


def signed_request(event: dict, secret: str):
    """Return (raw_body_bytes, headers) exactly as Ashby would send them."""
    raw = json.dumps(event).encode()
    return raw, {"Content-Type": "application/json", "Ashby-Signature": sign(secret, raw), "User-Agent": "Ashby-Webhook"}


def extract_hire_fields(payload):
    """Pick ONLY what onboarding needs. Everything else in the payload (salary, notes...) is ignored."""
    data = payload.get("data", {})
    app = data.get("application", {})
    cand, job = app.get("candidate", {}), app.get("job", {})
    dept = (job.get("departmentName") or "").strip()
    start = (data.get("offer") or {}).get("startDate")
    try:
        start = date.fromisoformat(start).isoformat()
    except (TypeError, ValueError):
        start = (date.today() + timedelta(days=14)).isoformat()
    return {"name": (cand.get("name") or "").strip(), "email": ((cand.get("primaryEmailAddress") or {}).get("value") or "").strip(),
            "title": job.get("title") or "New Hire", "team": dept if dept.lower() in TEAM_NAMES else "Operations",
            "location": job.get("locationName") or "US-Remote", "start_date": start}


def _team_manager(conn, team):
    row = conn.execute("SELECT id FROM employees WHERE team=? AND role='manager' AND status='active' ORDER BY id LIMIT 1", (team,)).fetchone()
    return row["id"] if row else "E001"


def _on_hire(ctx, event_id, payload):
    f = extract_hire_fields(payload)
    if not f["name"] or "@" not in f["email"]:
        return {"outcome": "rejected", "reason": "missing candidate name or email"}
    manager = _team_manager(ctx.conn, f["team"])
    emp_id = ctx.adapters.hris.create_employee(f["name"], f["email"], f["team"], f["title"], manager, f["location"], f["start_date"])
    plan_id = onboarding.create_plan(ctx.conn, emp_id, date.fromisoformat(f["start_date"]), source_event_id=event_id)
    first, _, last = f["name"].partition(" ")
    ctx.adapters.idp.create_user(f["email"], first, last, f["team"])  # staged account only, not active
    queued = [
        run_tool(ctx, "create_it_ticket", {"summary": f"New hire setup: laptop + accounts for {f['name']} ({f['team']}, {f['location']})",
                                           "description": f"Start date {f['start_date']}. Standard kit for {f['title']}."}, source="webhook"),
        run_tool(ctx, "draft_slack_message", {"channel": "#new-hires",
                                              "text": f"Welcome {first}! {f['name']} joins {f['team']} as {f['title']} on {f['start_date']}."}, source="webhook"),
        run_tool(ctx, "schedule_checkin", {"kind": "day-1", "employee": emp_id}, source="webhook"),
    ]
    audit.log(ctx.conn, "system", "webhook.hire_processed", {"event_id": event_id, "employee_id": emp_id, "plan_id": plan_id,
                                                           "team": f["team"], "queued_approvals": [q.get("approval_id") for q in queued]})
    return {"outcome": "processed", "employee_id": emp_id, "plan_id": plan_id, "queued_approvals": [q.get("approval_id") for q in queued]}


def _on_stage_change(ctx, event_id, payload):
    app = payload.get("data", {}).get("application", {})
    stage = (app.get("currentInterviewStage") or {}).get("title", "")
    audit.log(ctx.conn, "system", "webhook.stage_change", {"event_id": event_id, "application": app.get("id"), "stage": stage})
    return {"outcome": "processed", "application": app.get("id"), "stage": stage}


HANDLERS = {"candidateHire": _on_hire, "applicationUpdate": _on_stage_change}


def process(ctx, raw_body: bytes, signature_header, secret: str):
    """Handle one webhook request. Returns (http_status, json_reply)."""
    if not verify_signature(secret, raw_body, signature_header):
        audit.log(ctx.conn, "webhook", "webhook.rejected", {"reason": "bad_signature"})
        return 401, {"error": "invalid signature"}
    try:
        payload = json.loads(raw_body)
        action = payload["action"]
        if not isinstance(payload, dict) or not isinstance(action, str):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return 400, {"error": "invalid JSON or missing action"}

    event_id = str(payload.get("webhookActionId") or hashlib.sha256(raw_body).hexdigest())
    # Idempotency: the event id is the primary key, so a second delivery cannot insert.
    cur = ctx.conn.execute("INSERT OR IGNORE INTO webhook_events (event_id, action, received_at, outcome) VALUES (?,?,?,'received')",
                           (event_id, action, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    if cur.rowcount == 0:
        previous = ctx.conn.execute("SELECT outcome FROM webhook_events WHERE event_id=?", (event_id,)).fetchone()["outcome"]
        if previous != "received":  # already handled; a stuck 'received' row means a crash, so retry it
            audit.log(ctx.conn, "webhook", "webhook.duplicate", {"event_id": event_id})
            return 200, {"status": "duplicate", "event_id": event_id}

    handler = HANDLERS.get(action)
    if not handler:
        ctx.conn.execute("UPDATE webhook_events SET outcome='ignored' WHERE event_id=?", (event_id,))
        return 200, {"status": "ignored", "action": action}
    try:
        result = handler(ctx, event_id, payload)
    except Exception:  # noqa: BLE001  (leave the row as 'received' so Ashby's retry is processed)
        audit.log(ctx.conn, "system", "webhook.error", {"event_id": event_id})
        return 500, {"error": "processing failed; safe to retry"}
    ctx.conn.execute("UPDATE webhook_events SET outcome=? WHERE event_id=?", (result["outcome"], event_id))
    return 200, {"status": result["outcome"], "event_id": event_id, **{k: v for k, v in result.items() if k != "outcome"}}
