"""People analytics. Plain SQL queries; every group breakdown passes through k-anonymity.

Rule: a group with fewer than 5 people is never shown (see security.suppress_small_cells).
"""
import json
from datetime import date

from . import permissions
from .db import rows
from .security import K_MIN, suppress_small_cells

# The assumptions behind the "Time saved" panel. They are ESTIMATES, shown openly in the
# dashboard and editable there. Change them to match your own team's reality.
DEFAULT_ASSUMPTIONS = {
    "minutes_per_answered_question": 8,   # employee search time + People team reply time avoided
    "minutes_per_escalation_prepared": 4,  # the human gets a ready summary instead of starting cold
    "minutes_per_action_prefilled": 6,    # ticket / check-in / Slack draft prepared, human only approves
    "minutes_per_onboarding_plan": 45,    # building a checklist by hand across 4-5 tools
    "minutes_per_blocked_attempt": 0,
}


def headcount_by_team(conn):
    data = rows(conn, "SELECT team, COUNT(*) AS n FROM employees WHERE status='active' GROUP BY team ORDER BY n DESC")
    return suppress_small_cells(data)


def headcount_total(conn):
    return conn.execute("SELECT COUNT(*) FROM employees WHERE status='active'").fetchone()[0]


def funnel(conn):
    """How many applications reached each stage (a hire has also passed every earlier stage)."""
    names = ["Applied", "Phone screen", "Onsite", "Offer", "Hired"]
    return [{"stage": s, "n": conn.execute("SELECT COUNT(*) FROM applications WHERE stage_reached>=?", (i,)).fetchone()[0]}
            for i, s in enumerate(names)]


def time_to_hire(conn):
    """Days from application to hire, overall and by team (small teams suppressed)."""
    q = "SELECT team, COUNT(*) AS n, ROUND(AVG(julianday(hired_at)-julianday(applied_at)),1) AS days FROM applications WHERE status='hired'"
    overall = rows(conn, q)[0]
    by_team = suppress_small_cells(rows(conn, q + " GROUP BY team ORDER BY n DESC"), hide_keys=("days",))
    return {"overall_days": overall["days"], "hires": overall["n"], "by_team": by_team}


def onboarding_stats(conn):
    plans = conn.execute("SELECT COUNT(*) FROM onboarding_plans").fetchone()[0]
    t = rows(conn, """SELECT COUNT(*) AS total, SUM(status='done') AS done,
        SUM(status='done' AND completed_at <= due_date) AS on_time,
        SUM(due_date <= date('now','-2 day')) AS due FROM onboarding_tasks""")[0]
    prod = rows(conn, "SELECT e.team AS team, COUNT(*) AS n, ROUND(AVG(p.productive_days),1) AS days FROM onboarding_plans p "
                      "JOIN employees e ON e.id=p.employee_id WHERE p.productive_days IS NOT NULL GROUP BY e.team ORDER BY n DESC")
    overall = rows(conn, "SELECT COUNT(*) AS n, ROUND(AVG(productive_days),1) AS days FROM onboarding_plans WHERE productive_days IS NOT NULL")[0]
    due = t["due"] or 0
    owners = rows(conn, """SELECT owner_role AS owner, COUNT(*) AS tasks, ROUND(100.0*SUM(status='done' AND completed_at<=due_date)/COUNT(*)) AS on_time_pct
        FROM onboarding_tasks WHERE due_date <= date('now','-2 day') GROUP BY owner_role ORDER BY owner_role""")
    return {"plans": plans, "by_owner": owners,
            "tasks_done_pct": round(100 * (t["done"] or 0) / t["total"]) if t["total"] else None,
            "on_time_pct": round(100 * (t["on_time"] or 0) / due) if due else None,
            "time_to_productive_days": overall["days"], "productive_n": overall["n"],
            "time_to_productive_by_team": suppress_small_cells(prod, hide_keys=("days",))}


def _quarter_headcount(conn, q_end):
    return conn.execute("SELECT COUNT(*) FROM employees WHERE start_date<=? AND (end_date IS NULL OR end_date>?)",
                        (q_end, q_end)).fetchone()[0]


def arr_per_employee(conn):
    out = []
    for r in rows(conn, "SELECT * FROM arr_history ORDER BY quarter_end"):
        hc = _quarter_headcount(conn, r["quarter_end"])
        out.append({"quarter_end": r["quarter_end"], "arr_usd": r["arr_usd"], "headcount": hc,
                    "arr_per_employee": round(r["arr_usd"] / hc) if hc else None})
    return out


def manager_insights(conn, manager_id):
    """Team-level view for a manager's DIRECT reports. Hidden entirely if the team is under 5 people."""
    reports = rows(conn, "SELECT * FROM employees WHERE manager_id=? AND status='active'", (manager_id,))
    if len(reports) < K_MIN:
        return {"suppressed": True, "reports": len(reports),
                "note": f"Team has fewer than {K_MIN} people, so aggregate insights are hidden to protect individuals."}
    today = date.today()
    tenure = [(today - date.fromisoformat(r["start_date"])).days / 30.4 for r in reports]
    loc = {}
    for r in reports:
        loc[r["location"]] = loc.get(r["location"], 0) + 1
    ids = [r["id"] for r in reports]
    marks = ",".join("?" * len(ids))
    t = rows(conn, f"""SELECT COUNT(*) AS due, SUM(t.status='done' AND t.completed_at<=t.due_date) AS on_time
        FROM onboarding_tasks t JOIN onboarding_plans p ON p.id=t.plan_id WHERE p.employee_id IN ({marks}) AND t.due_date<=date('now')""", ids)[0]
    return {"suppressed": False, "reports": len(reports), "avg_tenure_months": round(sum(tenure) / len(tenure), 1),
            "joined_last_90_days": sum(1 for r in reports if (today - date.fromisoformat(r["start_date"])).days <= 90),
            "locations": suppress_small_cells([{"location": k, "n": v} for k, v in sorted(loc.items(), key=lambda x: -x[1])]),
            "onboarding_on_time_pct": round(100 * (t["on_time"] or 0) / t["due"]) if t["due"] else None}


def activity_counts(conn):
    """How often the agent did each kind of work, read straight from the audit log."""
    counts = {r["action"]: r["n"] for r in rows(conn, "SELECT action, COUNT(*) AS n FROM audit_log WHERE action LIKE 'chat.%' GROUP BY action")}
    plans = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='webhook.hire_processed'").fetchone()[0]
    return {"answered": counts.get("chat.answer", 0), "escalated": counts.get("chat.escalate", 0),
            "actions": counts.get("chat.action", 0), "blocked": counts.get("chat.block", 0),
            "clarify": counts.get("chat.clarify", 0), "plans_built": plans}


def time_saved(conn, assumptions=None):
    a = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}
    c = activity_counts(conn)
    minutes = (c["answered"] * a["minutes_per_answered_question"] + c["escalated"] * a["minutes_per_escalation_prepared"]
               + c["actions"] * a["minutes_per_action_prefilled"] + c["plans_built"] * a["minutes_per_onboarding_plan"])
    return {"counts": c, "assumptions": a, "minutes": minutes, "hours": round(minutes / 60, 1),
            "note": "Estimate = counts from the audit log x the assumed minutes shown here. Not a measured saving."}


def overview(conn, actor):
    """Everything the dashboard's Overview tab needs, limited to what this person may see."""
    if actor["role"] in ("people", "system"):
        return {"scope": "company", "headcount_total": headcount_total(conn), "headcount_by_team": headcount_by_team(conn),
                "funnel": funnel(conn), "time_to_hire": time_to_hire(conn), "onboarding": onboarding_stats(conn),
                "arr": arr_per_employee(conn), "time_saved": time_saved(conn), "k": K_MIN}
    if actor["role"] == "manager":
        return {"scope": "team", "manager_insights": manager_insights(conn, actor["id"]), "k": K_MIN}
    return {"scope": "none", "note": "Company analytics are for managers and the People team. Use the chat and your onboarding tab."}
