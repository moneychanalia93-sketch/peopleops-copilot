import json
import unittest

from peopleops import approvals, config, tools
from tests.helpers import make_conn, make_ctx


class ApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.employee = make_ctx(self.conn, "E006")
        self.people = make_ctx(self.conn, "E002")
        self.queued = tools.run_tool(self.employee, "create_it_ticket", {"summary": "Cracked screen"})

    def test_side_effect_tools_wait_in_the_queue(self):
        self.assertEqual(self.queued["status"], "pending_approval")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM it_tickets").fetchone()[0], 0)

    def test_allowlist_is_explicit_and_excludes_side_effects(self):
        self.assertEqual(tools.LOW_RISK_ALLOWLIST, {"search_handbook", "get_onboarding_status", "escalate_to_people_team"})

    def test_people_team_approval_runs_the_action(self):
        result = tools.decide_approval(self.people, self.queued["approval_id"], True)
        self.assertEqual(result["status"], "executed")
        ticket = self.conn.execute("SELECT * FROM it_tickets").fetchone()
        self.assertEqual((ticket["requester_id"], ticket["summary"]), ("E006", "Cracked screen"))

    def test_rejection_does_nothing(self):
        result = tools.decide_approval(self.people, self.queued["approval_id"], False, "not needed")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM it_tickets").fetchone()[0], 0)

    def test_employee_and_manager_cannot_approve(self):
        for user in ("E006", "E003"):
            self.assertEqual(tools.decide_approval(make_ctx(self.conn, user), self.queued["approval_id"], True)["error"], "not_permitted")

    def test_cannot_approve_twice(self):
        tools.decide_approval(self.people, self.queued["approval_id"], True)
        self.assertEqual(tools.decide_approval(self.people, self.queued["approval_id"], True)["error"], "already_decided")

    def test_nobody_approves_their_own_request(self):
        mine = tools.run_tool(self.people, "create_it_ticket", {"summary": "My own ask"})
        self.assertEqual(tools.decide_approval(self.people, mine["approval_id"], True)["error"], "separation_of_duties")

    def test_slack_post_goes_to_outbox_only_after_approval_and_is_redacted(self):
        outbox = config.outbox_path()
        outbox.unlink(missing_ok=True)
        queued = tools.run_tool(self.employee, "draft_slack_message", {"channel": "#general", "text": "Ping me at jordan@corp.example"})
        self.assertFalse(outbox.exists())
        tools.decide_approval(self.people, queued["approval_id"], True)
        record = json.loads(outbox.read_text().splitlines()[-1])
        self.assertEqual(record["channel"], "#general")
        self.assertNotIn("jordan@corp", record["text"])

    def test_slack_dms_and_bad_channels_are_refused(self):
        result = tools.run_tool(self.employee, "draft_slack_message", {"channel": "@dana", "text": "hi"})
        self.assertEqual(result["error"], "bad_channel")

    def test_checkin_for_someone_else_is_refused(self):
        result = tools.run_tool(self.employee, "schedule_checkin", {"kind": "day-7", "employee": "Nadia Okafor"})
        self.assertEqual(result["error"], "not_permitted")
        self.assertEqual(len(approvals.list_all(self.conn, "pending")), 1)  # only the ticket from setUp

    def test_bad_tool_arguments_are_rejected(self):
        self.assertEqual(tools.run_tool(self.employee, "create_it_ticket", {})["error"], "bad_arguments")
        self.assertEqual(tools.run_tool(self.employee, "create_it_ticket", {"summary": "x", "evil": "y"})["error"], "bad_arguments")
        self.assertEqual(tools.run_tool(self.employee, "no_such_tool", {})["error"], "unknown_tool")


if __name__ == "__main__":
    unittest.main()
