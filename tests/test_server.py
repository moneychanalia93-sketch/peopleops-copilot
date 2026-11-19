import json
import os
import unittest
import urllib.error
import urllib.request

from peopleops import db, seed, server, webhook
from tests.helpers import SECRET, TMP


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(TMP, "server-test.db")
        conn = db.connect(path)
        seed.seed(conn)
        conn.close()
        cls.srv = server.create_server(port=0, db_path=path, secret=SECRET)
        server.start_in_thread(cls.srv)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, path, user=None, body=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if user:
            h["X-Demo-User"] = user
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_binds_to_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_dashboard_page_and_health(self):
        code, page = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn(b"PeopleOps Copilot", page)
        self.assertNotIn(b"https://", page)  # no external resources (no CDN)
        self.assertEqual(self.call("/healthz")[0], 200)

    def test_people_overview_has_charts_data(self):
        code, body = self.call("/api/overview", "E002")
        data = json.loads(body)
        self.assertEqual((code, data["scope"], data["headcount_total"]), (200, "company", 60))

    def test_role_limits_on_api(self):
        self.assertEqual(self.call("/api/approvals", "E006")[0], 403)
        self.assertEqual(self.call("/api/audit", "E003")[0], 403)
        self.assertEqual(self.call("/api/approvals", "E002")[0], 200)
        self.assertEqual(self.call("/api/overview")[0], 401)
        self.assertEqual(json.loads(self.call("/api/overview", "E006")[1])["scope"], "none")

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(self.call("/", headers={"Host": "evil.example"})[0], 403)

    def test_chat_over_http_and_identity_required(self):
        code, body = self.call("/api/chat", "E006", {"message": "When is payday?"})
        self.assertEqual((code, json.loads(body)["route"]), (200, "answer"))
        self.assertEqual(self.call("/api/chat", None, {"message": "hi"})[0], 400)  # no identity header

    def test_webhook_over_http(self):
        raw, headers = webhook.signed_request(webhook.sample_hire_event(event_id="evt-http-1"), SECRET)
        self.assertEqual(self.call("/webhooks/ashby", body=raw, headers=headers)[0], 200)
        self.assertEqual(json.loads(self.call("/webhooks/ashby", body=raw, headers=headers)[1])["status"], "duplicate")
        forged = {**headers, "Ashby-Signature": "sha256=" + "1" * 64}
        self.assertEqual(self.call("/webhooks/ashby", body=raw, headers=forged)[0], 401)

    def test_approve_over_http(self):
        raw, headers = webhook.signed_request(webhook.sample_hire_event(event_id="evt-http-2"), SECRET)
        self.call("/webhooks/ashby", body=raw, headers=headers)
        pending = [a for a in json.loads(self.call("/api/approvals", "E002")[1]) if a["status"] == "pending"]
        self.assertEqual(self.call(f"/api/approvals/{pending[0]['id']}/approve", "E006", {})[0], 403)
        self.assertEqual(self.call(f"/api/approvals/{pending[0]['id']}/approve", "E002", {})[0], 200)


if __name__ == "__main__":
    unittest.main()
