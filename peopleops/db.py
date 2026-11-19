"""SQLite database: connection helper and the full schema in one place."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT, team TEXT, title TEXT,
  manager_id TEXT, location TEXT, start_date TEXT, end_date TEXT,
  status TEXT NOT NULL DEFAULT 'active',      -- active | pre-start | terminated
  role TEXT NOT NULL DEFAULT 'employee'       -- employee | manager | people
);
-- Compensation lives in its own table. NO agent tool reads it (least privilege).
CREATE TABLE IF NOT EXISTS comp_private (employee_id TEXT PRIMARY KEY, salary INTEGER);

CREATE TABLE IF NOT EXISTS applications (
  id TEXT PRIMARY KEY, candidate_name TEXT, job_title TEXT, team TEXT,
  stage_reached INTEGER NOT NULL,   -- 0 Applied, 1 Phone screen, 2 Onsite, 3 Offer, 4 Hired
  status TEXT NOT NULL,             -- active | hired | rejected
  applied_at TEXT, hired_at TEXT
);
CREATE TABLE IF NOT EXISTS arr_history (quarter_end TEXT PRIMARY KEY, arr_usd INTEGER);

CREATE TABLE IF NOT EXISTS onboarding_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, source_event_id TEXT,
  created_at TEXT, start_date TEXT, productive_days INTEGER   -- days until fully productive
);
CREATE TABLE IF NOT EXISTS onboarding_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL, title TEXT, category TEXT,
  owner_role TEXT, due_date TEXT, status TEXT NOT NULL DEFAULT 'pending', completed_at TEXT
);

CREATE TABLE IF NOT EXISTS webhook_events (
  event_id TEXT PRIMARY KEY, action TEXT, received_at TEXT, outcome TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, requested_by TEXT, source TEXT,
  tool TEXT, args_json TEXT, summary TEXT,
  status TEXT NOT NULL DEFAULT 'pending',     -- pending | executed | rejected | failed
  decided_by TEXT, decided_at TEXT, reason TEXT, result_json TEXT
);
CREATE TABLE IF NOT EXISTS escalations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, requester_id TEXT, category TEXT,
  owner TEXT, summary TEXT, status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS it_tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, requester_id TEXT,
  summary TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT, kind TEXT, due_date TEXT, created_by TEXT
);

-- Append-only audit log. Each row stores a hash of the previous row (a chain),
-- and triggers block UPDATE and DELETE.
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


def connect(path: str = ":memory:", init: bool = True) -> sqlite3.Connection:
    """Open the database (autocommit mode, rows behave like dicts). init=True also creates missing tables."""
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    if init:
        conn.executescript(SCHEMA)
    return conn


def rows(conn, sql, params=()):
    """Run a query and return a list of plain dicts."""
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
