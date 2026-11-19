"""Local web server: dashboard page, JSON API and the Ashby webhook endpoint.

Safety choices:
  * binds to 127.0.0.1 ONLY (config.HOST); there is no option to listen on other addresses
  * rejects requests whose Host header is not localhost/127.0.0.1 (blocks DNS-rebinding tricks)
  * POST /api/* must be JSON and carry the X-Demo-User header, which a web page on another site
    cannot send without a CORS preflight that we never grant (blocks cross-site request forgery)
  * the webhook is authenticated by its HMAC signature, not by user identity

DEMO LIMITATION: who you are is chosen with the "View as" dropdown (X-Demo-User header). That is a
stand-in for real sign-in. A live deployment must put SSO (e.g. Okta) in front of this.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import adapters, agent, analytics, approvals, audit, config, db, onboarding, permissions, webhook
from .context import Ctx
from .llm import get_model
from .tools import decide_approval

WEB = config.ROOT / "peopleops" / "web"
DEMO_USERS = ["E002", "E003", "E005", "E006", "E007"]  # People head, two managers, two employees
MAX_BODY = 1_000_000


class Handler(BaseHTTPRequestHandler):
    server_version = "PeopleOpsCopilot"

    def log_message(self, *args):  # keep the console quiet; the audit log is the real record
        pass

    # ----- helpers -----
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):
        return re.fullmatch(r"(127\.0\.0\.1|localhost)(:\d+)?", self.headers.get("Host", "")) is not None

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return None
        return self.rfile.read(length)

    def _ctx(self, conn, system=False):
        user = "system" if system else self.headers.get("X-Demo-User", "")
        try:
            return Ctx.for_user(conn, user, adapters.build(conn))
        except KeyError:
            return None

    # ----- routing -----
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html")
        if path == "/healthz":
            return self._send(200, {"ok": True})
        conn = db.connect(self.server.app.db_path, init=False)
        try:
            self._api_get(conn, path)
        finally:
            conn.close()

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        raw = self._body()
        if raw is None:
            return self._send(413, {"error": "body too large"})
        path = self.path.split("?")[0]
        conn = db.connect(self.server.app.db_path, init=False)
        try:
            if path == "/webhooks/ashby":
                ctx = self._ctx(conn, system=True)
                code, reply = webhook.process(ctx, raw, self.headers.get("Ashby-Signature"), self.server.app.secret)
                return self._send(code, reply)
            if "application/json" not in self.headers.get("Content-Type", "") or not self.headers.get("X-Demo-User"):
                return self._send(400, {"error": "JSON body and X-Demo-User header required"})
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            self._api_post(conn, path, body if isinstance(body, dict) else {})
        finally:
            conn.close()

    def _api_get(self, conn, path):
        if path == "/api/users":
            users = [permissions.get_employee(conn, u) for u in DEMO_USERS]
            return self._send(200, [{k: u[k] for k in ("id", "name", "role", "team", "title")} for u in users if u])
        ctx = self._ctx(conn)
        if ctx is None:
            return self._send(401, {"error": "unknown user (set X-Demo-User)"})
        actor, is_people = ctx.actor, ctx.actor["role"] == "people"
        if path == "/api/overview":
            return self._send(200, analytics.overview(conn, actor))
        if path == "/api/onboarding":
            return self._send(200, onboarding.list_plans(conn, actor))
        if path == "/api/eval":
            report = config.var_dir() / "eval_latest.json"
            return self._send(200, json.loads(report.read_text()) if report.exists() else {"missing": True})
        if path in ("/api/approvals", "/api/escalations", "/api/audit"):
            if not is_people:
                audit.log(conn, actor["id"], "permission.denied", {"api": path})
                return self._send(403, {"error": "People team only"})
            if path == "/api/approvals":
                return self._send(200, approvals.list_all(conn))
            if path == "/api/escalations":
                return self._send(200, approvals.list_escalations(conn))
            return self._send(200, {"verify": audit.verify_chain(conn), "rows": audit.recent(conn, 150)})
        return self._send(404, {"error": "not found"})

    def _api_post(self, conn, path, body):
        ctx = self._ctx(conn)
        if ctx is None:
            return self._send(401, {"error": "unknown user"})
        if path == "/api/chat":
            if not isinstance(body.get("message"), str):
                return self._send(400, {"error": "message must be text"})
            result = agent.handle_message(ctx, body["message"], self.server.app.model)
            return self._send(200, result)
        m = re.fullmatch(r"/api/approvals/(\d+)/(approve|reject)", path)
        if m:
            result = decide_approval(ctx, int(m.group(1)), m.group(2) == "approve", str(body.get("reason", ""))[:200])
            return self._send(403 if result.get("error") == "not_permitted" else 200, result)
        return self._send(404, {"error": "not found"})


class App:
    def __init__(self, db_path, secret, model):
        self.db_path, self.secret, self.model = db_path, secret, model


def create_server(port=None, db_path=None, secret=None, model=None):
    """Build (but do not start) the server. port=0 picks a free port (used by tests)."""
    db_path = db_path or config.db_path()
    db.connect(db_path).close()  # make sure the tables exist
    srv = ThreadingHTTPServer((config.HOST, config.port() if port is None else port), Handler)
    srv.app = App(db_path, secret or config.webhook_secret(), model or get_model())
    return srv


def start_in_thread(srv):
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return t
