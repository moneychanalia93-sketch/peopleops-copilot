"""Approval queue and escalation inbox (storage only; running an approved action is in tools.py).

Rule: any action that changes something in the outside world waits here for a human,
unless its tool is on the explicit low-risk allowlist in tools.py.
"""
import json
from datetime import datetime, timezone

from . import audit


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enqueue(conn, requested_by, source, tool, args, summary) -> int:
    cur = conn.execute(
        "INSERT INTO approvals (created_at, requested_by, source, tool, args_json, summary) VALUES (?,?,?,?,?,?)",
        (_now(), requested_by, source, tool, json.dumps(args), summary))
    audit.log(conn, requested_by, "approval.queued", {"approval_id": cur.lastrowid, "tool": tool, "source": source})
    return cur.lastrowid


def get(conn, approval_id):
    row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["args"] = json.loads(d.pop("args_json"))
    d["result"] = json.loads(d["result_json"]) if d.get("result_json") else None
    return d


def list_all(conn, status=None):
    sql, params = "SELECT id FROM approvals", ()
    if status:
        sql, params = sql + " WHERE status=?", (status,)
    return [get(conn, r["id"]) for r in conn.execute(sql + " ORDER BY id DESC", params)]


def create_escalation(conn, requester_id, category, owner, summary) -> int:
    cur = conn.execute(
        "INSERT INTO escalations (created_at, requester_id, category, owner, summary) VALUES (?,?,?,?,?)",
        (_now(), requester_id, category, owner, summary))
    return cur.lastrowid


def list_escalations(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM escalations ORDER BY id DESC")]
