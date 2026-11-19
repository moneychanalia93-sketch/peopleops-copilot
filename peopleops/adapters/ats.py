"""Applicant tracking system: Ashby.

Interface:  get_application(application_id) -> dict with candidate, job, stage.
Ashby also PUSHES events to us by webhook; that side lives in webhook.py.
"""
from .http import basic_auth, call_json


class MockAshby:
    """Reads from the synthetic `applications` table."""

    def __init__(self, conn):
        self.conn = conn

    def get_application(self, application_id):
        row = self.conn.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        return dict(row) if row else None


class AshbyAPI:
    """REAL stub. Ashby's RPC-style API: POST https://api.ashbyhq.com/<method>
    Auth: HTTP Basic with the API key as the username and an empty password.
    Docs: https://developers.ashbyhq.com  (method used: application.info)
    NOT run against a live account.
    """
    BASE = "https://api.ashbyhq.com"

    def __init__(self, api_key):
        self.headers = {"Authorization": basic_auth(api_key)}

    def get_application(self, application_id):
        reply = call_json("POST", f"{self.BASE}/application.info", self.headers, {"applicationId": application_id})
        return reply.get("results")
