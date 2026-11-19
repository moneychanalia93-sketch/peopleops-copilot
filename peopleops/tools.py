"""The six tools the agent can call, plus the rules around them.

How a tool call is handled (`run_tool`):
  1. Check the arguments match the tool's schema.
  2. Check the PERMISSION of the person asking (not whoever the model claims).
  3. If the tool is on the low-risk allowlist, run it now.
     Otherwise put it in the approval queue and tell the agent it is "pending approval".
  4. Write an audit row either way.

A People team member later approves or rejects it (`decide_approval`); only then does the action
actually happen (a ticket is created, a Slack message is posted, ...).
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from . import approvals, audit, onboarding, permissions, safety
from .context import Ctx
from .retrieval import get_handbook
from .security import redact

# The ONLY tools allowed to act without a human approving first. They read data or hand
# the question to humans; none of them change anything in an outside system.
LOW_RISK_ALLOWLIST = {"search_handbook", "get_onboarding_status", "escalate_to_people_team"}

ESCALATION_CATEGORIES = list(safety.SENSITIVE) + ["unanswerable", "other"]

TOOLS = {
    "search_handbook": {
        "description": "Search the company handbook. Returns the best-matching sections with citation ids.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    "get_onboarding_status": {
        "description": "Show onboarding progress. Omit 'employee' for the asker's own plan; managers may ask about direct reports.",
        "schema": {"type": "object", "properties": {"employee": {"type": "string"}}, "required": []}},
    "create_it_ticket": {
        "description": "Open an IT ticket (hardware, software or access). Needs human approval.",
        "schema": {"type": "object", "properties": {"summary": {"type": "string"}, "description": {"type": "string"}},
                   "required": ["summary"]}},
    "schedule_checkin": {
        "description": "Schedule an onboarding check-in or 1:1. Needs human approval.",
        "schema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["day-1", "day-7", "day-30", "one-on-one"]},
            "employee": {"type": "string"}, "date": {"type": "string"}}, "required": ["kind"]}},
    "draft_slack_message": {
        "description": "Draft a Slack message to a public channel. Posted only after human approval.",
        "schema": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
                   "required": ["channel", "text"]}},
    "escalate_to_people_team": {
        "description": "Hand the conversation to a human on the People team, with a short context summary.",
        "schema": {"type": "object", "properties": {"category": {"type": "string", "enum": ESCALATION_CATEGORIES},
                                                    "summary": {"type": "string"}}, "required": ["category", "summary"]}},
}


# ---------- validation ----------
def _validate(name, args):
    spec = TOOLS[name]["schema"]
    if not isinstance(args, dict):
        return "arguments must be an object"
    for key in spec["required"]:
        if not isinstance(args.get(key), str) or not args[key].strip():
            return f"missing or empty '{key}'"
    for key, val in args.items():
        prop = spec["properties"].get(key)
        if prop is None:
            return f"unknown argument '{key}'"
        if not isinstance(val, str):
            return f"'{key}' must be a string"
        if "enum" in prop and val not in prop["enum"]:
            return f"'{key}' must be one of {prop['enum']}"
        if len(val) > 2000:
            return f"'{key}' is too long"
    return None


def _resolve_employee(ctx, who):
    """'me'/empty -> the asker. A name or id -> that employee (or an error string)."""
    if not who or who.strip().lower() in ("me", "myself", "my", "self"):
        return ctx.actor if ctx.actor["role"] != "system" else None, None
    found = permissions.find_by_name(ctx.conn, who)
    if len(found) == 1:
        return found[0], None
    return None, ("no employee found" if not found else "more than one employee matches; use the full name")


# ---------- the actual work each tool does ----------
def _search_handbook(ctx, args):
    hits = get_handbook().search(args["query"], permissions.handbook_audiences(ctx.actor))
    return {"results": [{k: h[k] for k in ("cite", "doc_title", "section_title", "score", "text")} for h in hits]}


def _onboarding_status(ctx, args):
    target, err = _resolve_employee(ctx, args.get("employee"))
    if err or target is None:
        return {"error": "not_found", "detail": err or "say whose onboarding you mean"}
    if not permissions.can_view_employee(ctx.conn, ctx.actor, target["id"]):
        audit.log(ctx.conn, ctx.actor["id"], "permission.denied", {"tool": "get_onboarding_status", "target": target["id"]})
        return {"error": "not_permitted", "detail": "You can only see your own onboarding (managers: direct reports)."}
    status = onboarding.plan_status(ctx.conn, target["id"])
    if not status:
        return {"found": False, "employee": target["name"], "detail": "No onboarding plan on file."}
    pending = [t for t in status["tasks"] if t["status"] != "done"][:3]
    return {"found": True, "employee": status["employee"], "start_date": status["start_date"], "done": status["done"],
            "total": status["total"], "pct": status["pct"], "next_tasks": [{"title": t["title"], "due": t["due_date"]} for t in pending]}


def _create_it_ticket(ctx, args):
    ticket = ctx.adapters.itsm.create_ticket(ctx.actor["id"], args["summary"], args.get("description", ""))
    return {"ticket_id": ticket}


def _next_business_day(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _schedule_checkin(ctx, args):
    target, err = _resolve_employee(ctx, args.get("employee"))
    if err or target is None:
        return {"error": "not_found", "detail": err or "say who the check-in is for"}
    if not permissions.can_view_employee(ctx.conn, ctx.actor, target["id"]):
        return {"error": "not_permitted", "detail": "You can only schedule check-ins for yourself or your direct reports."}
    kind = args["kind"]
    if args.get("date"):
        try:
            due = date.fromisoformat(args["date"])
        except ValueError:
            return {"error": "bad_date", "detail": "use YYYY-MM-DD"}
    elif kind.startswith("day-"):
        plan = onboarding.plan_status(ctx.conn, target["id"])
        start = date.fromisoformat(plan["start_date"]) if plan else date.today()
        due = start + timedelta(days=int(kind.split("-")[1]))
    else:
        due = _next_business_day(date.today())
    ctx.conn.execute("INSERT INTO checkins (employee_id, kind, due_date, created_by) VALUES (?,?,?,?)",
                     (target["id"], kind, due.isoformat(), ctx.actor["id"]))
    return {"employee": target["name"], "kind": kind, "date": due.isoformat()}


def _draft_slack_message(ctx, args):
    if not re.fullmatch(r"#[a-z0-9][a-z0-9_-]{0,40}", args["channel"]):
        return {"error": "bad_channel", "detail": "only public channels like #general are allowed (no DMs)"}
    text = f"{redact(args['text'])}\n(drafted for {ctx.actor['name']} by PeopleOps Copilot)"
    return ctx.adapters.chat.post_message(args["channel"], text)


def _escalate(ctx, args):
    category = args["category"]
    owner = safety.SENSITIVE[category][0] if category in safety.SENSITIVE else "People Operations"
    me = ctx.actor
    summary = (f"From: {me['name']} ({me['role']}, {me.get('team', '-')})\nCategory: {category}\nSuggested owner: {owner}\n"
               f"Summary: {redact(args['summary'])}")
    esc_id = approvals.create_escalation(ctx.conn, me["id"], category, owner, summary)
    return {"escalation_id": esc_id, "owner": owner}


_EXEC = {"search_handbook": _search_handbook, "get_onboarding_status": _onboarding_status,
         "create_it_ticket": _create_it_ticket, "schedule_checkin": _schedule_checkin,
         "draft_slack_message": _draft_slack_message, "escalate_to_people_team": _escalate}


def _summarize(name, args):
    if name == "create_it_ticket":
        return f"Open IT ticket: {args['summary']}"
    if name == "schedule_checkin":
        return f"Schedule {args['kind']} check-in for {args.get('employee') or 'requester'}"
    if name == "draft_slack_message":
        return f"Post to {args['channel']}: {redact(args['text'])[:120]}"
    return name


# ---------- the entry point the agent uses ----------
def run_tool(ctx: Ctx, name: str, args: dict, source: str = "agent") -> dict:
    if name not in TOOLS:
        return {"error": "unknown_tool"}
    problem = _validate(name, args)
    if problem:
        audit.log(ctx.conn, ctx.actor["id"], "tool.rejected", {"tool": name, "problem": problem})
        return {"error": "bad_arguments", "detail": problem}

    if name in LOW_RISK_ALLOWLIST:
        result = _EXEC[name](ctx, args)
        # Escalation summaries hold the employee's words, so the audit log keeps only the argument NAMES for them.
        logged = {"category": args.get("category")} if name == "escalate_to_people_team" else args
        audit.log(ctx.conn, ctx.actor["id"], "tool.run", {"tool": name, "args": logged, "ok": "error" not in result})
        return result

    # Side-effect tool: check what we can BEFORE queueing, so nobody queues what they may not do.
    if name == "schedule_checkin":
        target, err = _resolve_employee(ctx, args.get("employee"))
        if err or target is None:
            return {"error": "not_found", "detail": err or "say who the check-in is for"}
        if not permissions.can_view_employee(ctx.conn, ctx.actor, target["id"]):
            audit.log(ctx.conn, ctx.actor["id"], "permission.denied", {"tool": name, "target": target["id"]})
            return {"error": "not_permitted", "detail": "You can only schedule check-ins for yourself or your direct reports."}
    if name == "draft_slack_message" and not re.fullmatch(r"#[a-z0-9][a-z0-9_-]{0,40}", args["channel"]):
        return {"error": "bad_channel", "detail": "only public channels like #general are allowed (no DMs)"}
    approval_id = approvals.enqueue(ctx.conn, ctx.actor["id"], source, name, args, _summarize(name, args))
    return {"status": "pending_approval", "approval_id": approval_id, "summary": _summarize(name, args)}


def decide_approval(ctx: Ctx, approval_id: int, approve: bool, reason: str = "") -> dict:
    """A People team member approves (runs the action) or rejects it."""
    if ctx.actor["role"] != "people":
        audit.log(ctx.conn, ctx.actor["id"], "permission.denied", {"action": "decide_approval", "approval_id": approval_id})
        return {"error": "not_permitted", "detail": "Only the People team can decide approvals."}
    item = approvals.get(ctx.conn, approval_id)
    if not item:
        return {"error": "not_found"}
    if item["status"] != "pending":
        return {"error": "already_decided", "status": item["status"]}
    if item["requested_by"] == ctx.actor["id"]:
        return {"error": "separation_of_duties", "detail": "You cannot approve your own request."}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not approve:
        ctx.conn.execute("UPDATE approvals SET status='rejected', decided_by=?, decided_at=?, reason=? WHERE id=?",
                         (ctx.actor["id"], now, reason, approval_id))
        audit.log(ctx.conn, ctx.actor["id"], "approval.rejected", {"approval_id": approval_id, "tool": item["tool"], "reason": reason})
        return {"status": "rejected"}
    requester = permissions.get_employee(ctx.conn, item["requested_by"])
    status, result = "executed", {}
    try:  # run the action with the REQUESTER's permissions, not the approver's
        result = _EXEC[item["tool"]](Ctx(ctx.conn, requester, ctx.adapters), item["args"])
        if "error" in result:
            status = "failed"
    except Exception as exc:  # noqa: BLE001 (record any adapter failure instead of crashing the queue)
        status, result = "failed", {"error": type(exc).__name__}
    ctx.conn.execute("UPDATE approvals SET status=?, decided_by=?, decided_at=?, reason=?, result_json=? WHERE id=?",
                     (status, ctx.actor["id"], now, reason, json.dumps(result), approval_id))
    audit.log(ctx.conn, ctx.actor["id"], "approval.approved", {"approval_id": approval_id, "tool": item["tool"], "status": status})
    return {"status": status, "result": result}
