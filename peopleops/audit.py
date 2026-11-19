"""Append-only, tamper-evident audit log.

Two protections:
  1. SQL triggers (see db.py) refuse UPDATE and DELETE on the table.
  2. Every row stores a SHA-256 hash that covers the previous row's hash, so editing
     history after the fact (e.g. by dropping the triggers) breaks the chain and
     `verify_chain` reports exactly where.
"""
import hashlib
import json
import threading
from datetime import datetime, timezone

from .security import redact

_LOCK = threading.Lock()  # one writer at a time inside this process
GENESIS = "0" * 64


def _hash(prev_hash, ts, actor, action, detail):
    return hashlib.sha256("|".join([prev_hash, ts, actor, action, detail]).encode()).hexdigest()


def log(conn, actor: str, action: str, detail: dict | None = None):
    """Write one audit row. The detail is JSON, with PII redacted before it is stored."""
    detail_text = redact(json.dumps(detail or {}, sort_keys=True, default=str))
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else GENESIS
            conn.execute(
                "INSERT INTO audit_log (ts, actor, action, detail, prev_hash, hash) VALUES (?,?,?,?,?,?)",
                (ts, actor, action, detail_text, prev, _hash(prev, ts, actor, action, detail_text)),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def verify_chain(conn) -> dict:
    """Recompute every hash. Returns {"ok": True, "rows": n} or says which row is broken."""
    prev, count = GENESIS, 0
    for r in conn.execute("SELECT * FROM audit_log ORDER BY id"):
        expected = _hash(prev, r["ts"], r["actor"], r["action"], r["detail"])
        if r["prev_hash"] != prev or r["hash"] != expected:
            return {"ok": False, "broken_at": r["id"], "rows": count}
        prev, count = r["hash"], count + 1
    return {"ok": True, "rows": count}


def recent(conn, limit=200):
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
