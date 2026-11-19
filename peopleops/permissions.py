"""Who may see whose data. One small rulebook, used by every tool and API call.

  employee    -> only their own record
  manager     -> themselves + their DIRECT reports
  people team -> everyone
  system      -> the webhook automation (acts for the People team)
"""

SYSTEM_ACTOR = {"id": "system", "name": "PeopleOps Copilot (system)", "role": "system", "team": "People"}


def get_employee(conn, emp_id):
    if emp_id == "system":
        return dict(SYSTEM_ACTOR)
    row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    return dict(row) if row else None


def find_by_name(conn, text):
    """Find active/pre-start employees whose full name appears in `text`, or exact-name match."""
    needle = text.strip().lower()
    rows = conn.execute("SELECT * FROM employees WHERE status != 'terminated'").fetchall()
    exact = [dict(r) for r in rows if r["name"].lower() == needle or r["id"].lower() == needle]
    if exact:
        return exact
    return [dict(r) for r in rows if needle and needle in r["name"].lower()]


def is_people(actor) -> bool:
    return actor["role"] in ("people", "system")


def can_view_employee(conn, actor, target_id) -> bool:
    if is_people(actor) or actor["id"] == target_id:
        return True
    if actor["role"] != "manager":
        return False
    row = conn.execute("SELECT manager_id FROM employees WHERE id=?", (target_id,)).fetchone()
    return bool(row and row["manager_id"] == actor["id"])


def visible_employee_ids(conn, actor):
    if is_people(actor):
        return [r["id"] for r in conn.execute("SELECT id FROM employees")]
    ids = [actor["id"]]
    if actor["role"] == "manager":
        ids += [r["id"] for r in conn.execute("SELECT id FROM employees WHERE manager_id=?", (actor["id"],))]
    return ids


def handbook_audiences(actor):
    """Handbook documents are tagged 'all' or 'managers'."""
    return ("all", "managers") if actor["role"] in ("manager", "people", "system") else ("all",)
