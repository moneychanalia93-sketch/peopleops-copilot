import json
import unittest

from peopleops import webhook
from tests.helpers import SECRET, make_conn, make_ctx


def post(ctx, event, secret=SECRET, signature=None):
    raw, headers = webhook.signed_request(event, secret)
    return webhook.process(ctx, raw, signature or headers["Ashby-Signature"], SECRET)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.ctx = make_ctx(self.conn, "system")

    def plans(self):
        return self.conn.execute("SELECT COUNT(*) FROM onboarding_plans").fetchone()[0]

    def test_valid_hire_creates_plan_and_queues_actions(self):
        before = self.plans()
        code, body = post(self.ctx, webhook.sample_hire_event())
        self.assertEqual((code, body["status"]), (200, "processed"))
        self.assertEqual(self.plans(), before + 1)
        tools = {r["tool"] for r in self.conn.execute("SELECT tool FROM approvals WHERE status='pending'")}
        self.assertEqual(tools, {"create_it_ticket", "draft_slack_message", "schedule_checkin"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM it_tickets").fetchone()[0], 0)  # nothing ran yet

    def test_plan_is_tailored_to_team_and_location(self):
        post(self.ctx, webhook.sample_hire_event(department="Engineering", location="London"))
        titles = [t["title"] for t in self.conn.execute("SELECT title FROM onboarding_tasks WHERE plan_id=(SELECT MAX(id) FROM onboarding_plans)")]
        self.assertTrue(any("dev environment" in t for t in titles))
        self.assertTrue(any("Right-to-work" in t for t in titles))

    def test_bad_signature_rejected_and_nothing_changes(self):
        before = self.plans()
        code, _ = post(self.ctx, webhook.sample_hire_event(), signature="sha256=" + "0" * 64)
        self.assertEqual(code, 401)
        self.assertEqual(self.plans(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM webhook_events").fetchone()[0], 0)

    def test_unsigned_request_rejected(self):
        code, _ = webhook.process(self.ctx, b"{}", None, SECRET)
        self.assertEqual(code, 401)

    def test_replayed_event_is_idempotent(self):
        event = webhook.sample_hire_event(event_id="evt-dup")
        post(self.ctx, event)
        count_after_first = (self.plans(), self.conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0])
        code, body = post(self.ctx, event)
        self.assertEqual((code, body["status"]), (200, "duplicate"))
        self.assertEqual((self.plans(), self.conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]), count_after_first)

    def test_offer_salary_is_never_stored(self):
        post(self.ctx, webhook.sample_hire_event())
        dump = json.dumps([tuple(r) for t in ("employees", "onboarding_plans", "onboarding_tasks", "approvals", "audit_log", "webhook_events")
                           for r in self.conn.execute(f"SELECT * FROM {t}")])
        self.assertNotIn("185000", dump)

    def test_malformed_signed_json_is_400(self):
        raw = b"not json"
        code, _ = webhook.process(self.ctx, raw, webhook.sign(SECRET, raw), SECRET)
        self.assertEqual(code, 400)

    def test_unknown_event_type_is_ignored(self):
        code, body = post(self.ctx, {"action": "jobPostingUpdate", "webhookActionId": "evt-x", "data": {}})
        self.assertEqual((code, body["status"]), (200, "ignored"))


if __name__ == "__main__":
    unittest.main()
