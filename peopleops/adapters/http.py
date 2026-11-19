"""Tiny shared helper for real API calls (standard library only)."""
import base64
import json
import urllib.request


def basic_auth(user: str, password: str = "") -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def call_json(method: str, url: str, headers: dict, body: dict | None = None, timeout: int = 15):
    """Send one JSON request and return the decoded JSON reply. Raises on HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https URLs only, set by config)
        raw = resp.read()
    return json.loads(raw) if raw else {}
