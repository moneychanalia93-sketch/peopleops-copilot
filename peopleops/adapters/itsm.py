"""IT tickets (Jira Service Management) and identity provider (Okta).

Interfaces:
  itsm.create_ticket(requester_id, summary, description) -> ticket id
  idp.create_user(email, first_name, last_name, team)    -> okta user id (created STAGED, not active)
"""
from datetime import datetime, timezone

from .http import basic_auth, call_json


class MockITSM:
    """Stores tickets in the local `it_tickets` table."""

    def __init__(self, conn):
        self.conn = conn

    def create_ticket(self, requester_id, summary, description):
        cur = self.conn.execute(
            "INSERT INTO it_tickets (created_at, requester_id, summary, description) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), requester_id, summary, description))
        return f"IT-{cur.lastrowid}"


class JiraServiceDeskAPI:
    """REAL stub.
      POST {base}/rest/servicedeskapi/request     (auth: HTTP Basic, account email + API token)
      body {"serviceDeskId": "...", "requestTypeId": "...", "requestFieldValues": {"summary": "...", "description": "..."}}
    The two ids come from your own Jira project. Docs: developer.atlassian.com (Jira Service Management Cloud REST API).
    NOT run against a live account.
    """

    def __init__(self, base_url, email, api_token, service_desk_id="1", request_type_id="1"):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": basic_auth(email, api_token)}
        self.ids = (service_desk_id, request_type_id)

    def create_ticket(self, requester_id, summary, description):
        body = {"serviceDeskId": self.ids[0], "requestTypeId": self.ids[1],
                "requestFieldValues": {"summary": summary, "description": f"Requested by {requester_id}\n{description}"}}
        return call_json("POST", f"{self.base}/rest/servicedeskapi/request", self.headers, body).get("issueKey")


class MockOkta:
    def create_user(self, email, first_name, last_name, team):
        return "okta-mock-" + email.split("@")[0]


class OktaAPI:
    """REAL stub.
      POST {org}/api/v1/users?activate=false   header `Authorization: SSWS <api token>`
      body {"profile": {"firstName","lastName","email","login"}}   -> user is STAGED until activated.
    Docs: developer.okta.com (Users API). NOT run against a live org.
    """

    def __init__(self, org_url, api_token):
        self.base = org_url.rstrip("/")
        self.headers = {"Authorization": f"SSWS {api_token}"}

    def create_user(self, email, first_name, last_name, team):
        body = {"profile": {"firstName": first_name, "lastName": last_name, "email": email, "login": email, "department": team}}
        return call_json("POST", f"{self.base}/api/v1/users?activate=false", self.headers, body).get("id")
