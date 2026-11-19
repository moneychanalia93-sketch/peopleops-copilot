"""Onboarding plans: which tasks a new hire gets, and when they are due.

The template below is plain data. To change what a Sales hire in London receives,
edit one line here; no other code changes.
"""
from datetime import date, datetime, timedelta, timezone

from . import permissions

# (title, category, owner, due = days from start date, who it applies to)
# `applies` is a function of (team, location, is_manager). `None` means everyone.
TEMPLATE = [
    ("Ship laptop and accessories", "IT", "IT", -5, None),
    ("Create accounts: email, Slack, SSO (Okta)", "IT", "IT", -3, None),
    ("Send welcome note and day-1 schedule", "Communication", "People", -2, None),
    ("Add to Slack channels (#general, #new-hires, team channel)", "IT", "IT", -1, None),
    ("Manager 1:1 intro", "Manager", "Manager", 1, None),
    ("Day-1 check-in", "Check-in", "Manager", 1, None),
    ("Sign handbook acknowledgment", "Compliance", "Employee", 3, None),
    ("Complete security awareness training", "Compliance", "Employee", 5, None),
    ("Day-7 check-in", "Check-in", "Manager", 7, None),
    ("Complete code of conduct and compliance training", "Compliance", "Employee", 14, None),
    ("Benefits enrollment (window closes day 30)", "Benefits", "Employee", 28, None),
    ("Day-30 check-in", "Check-in", "Manager", 30, None),
    # Team-specific
    ("Set up dev environment and repository access", "IT", "IT", 2, lambda t, l, m: t == "Engineering"),
    ("Complete secure coding training", "Compliance", "Employee", 14, lambda t, l, m: t == "Engineering"),
    ("CRM access and product certification", "IT", "IT", 10, lambda t, l, m: t == "Sales"),
    ("Support tooling access", "IT", "IT", 3, lambda t, l, m: t == "Customer Success"),
    # Location-specific
    ("Right-to-work document check (People team)", "Compliance", "People", -1, lambda t, l, m: l == "London"),
    ("Complete I-9 employment verification", "Compliance", "People", 3, lambda t, l, m: l in ("US-Remote", "New York")),
    ("Provide payroll and tax forms", "Compliance", "Employee", 3, lambda t, l, m: l == "Toronto"),
    # Role-specific
    ("Manager essentials training", "Manager", "Employee", 14, lambda t, l, m: m),
]


def _iso(d: date) -> str:
    return d.isoformat()


def create_plan(conn, employee_id, start_date: date, source_event_id=None, today=None):
    """Build the plan + tasks for one employee. Returns the plan id."""
    emp = permissions.get_employee(conn, employee_id)
    is_manager = emp["role"] == "manager" or any(
        w in (emp["title"] or "") for w in ("Engineering Manager", "Director", "VP", "Head of"))
    created = (today or datetime.now(timezone.utc).date())
    cur = conn.execute(
        "INSERT INTO onboarding_plans (employee_id, source_event_id, created_at, start_date) VALUES (?,?,?,?)",
        (employee_id, source_event_id, _iso(created), _iso(start_date)))
    plan_id = cur.lastrowid
    for title, category, owner, offset, applies in TEMPLATE:
        if applies is None or applies(emp["team"], emp["location"], is_manager):
            conn.execute(
                "INSERT INTO onboarding_tasks (plan_id, title, category, owner_role, due_date) VALUES (?,?,?,?,?)",
                (plan_id, title, category, owner, _iso(start_date + timedelta(days=offset))))
    return plan_id


def plan_status(conn, employee_id):
    """Latest plan for an employee with task list and % complete, or None."""
    plan = conn.execute(
        "SELECT * FROM onboarding_plans WHERE employee_id=? ORDER BY id DESC LIMIT 1", (employee_id,)).fetchone()
    if not plan:
        return None
    tasks = [dict(t) for t in conn.execute(
        "SELECT title, category, owner_role, due_date, status, completed_at FROM onboarding_tasks "
        "WHERE plan_id=? ORDER BY due_date, id", (plan["id"],))]
    done = sum(1 for t in tasks if t["status"] == "done")
    emp = permissions.get_employee(conn, employee_id)
    return {"plan_id": plan["id"], "employee_id": employee_id, "employee": emp["name"],
            "team": emp["team"], "start_date": plan["start_date"], "tasks": tasks,
            "done": done, "total": len(tasks), "pct": round(100 * done / len(tasks)) if tasks else 0}


def list_plans(conn, actor):
    """Plans the actor is allowed to see (permission rules from permissions.py)."""
    out = []
    for emp_id in permissions.visible_employee_ids(conn, actor):
        status = plan_status(conn, emp_id)
        if status:
            out.append(status)
    out.sort(key=lambda s: s["start_date"], reverse=True)
    return out
