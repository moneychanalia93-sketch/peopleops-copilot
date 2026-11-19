"""Settings. Everything comes from environment variables, with safe local defaults.

Read at call time (not import time) so tests can change the environment.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the peopleops-copilot folder
HOST = "127.0.0.1"  # the servers ONLY ever bind to this address


def var_dir() -> Path:
    """Folder for runtime files (database, Slack outbox, eval report)."""
    p = Path(os.environ.get("PEOPLEOPS_VAR", ROOT / "var"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> str:
    return os.environ.get("PEOPLEOPS_DB", str(var_dir() / "peopleops.db"))


def outbox_path() -> Path:
    """Slack messages are written here unless SLACK_WEBHOOK_URL is set."""
    return Path(os.environ.get("PEOPLEOPS_OUTBOX", var_dir() / "slack_outbox.jsonl"))


def webhook_secret() -> str:
    """Shared secret used to sign/verify Ashby webhooks.

    The default is a DEMO-ONLY value so the one-command demo works. For anything
    real, set ASHBY_WEBHOOK_SECRET to the secret token configured in Ashby.
    """
    return os.environ.get("ASHBY_WEBHOOK_SECRET", "demo-only-secret-change-me")


def port() -> int:
    return int(os.environ.get("PEOPLEOPS_PORT", "8765"))


def slack_webhook_url() -> str:
    return os.environ.get("SLACK_WEBHOOK_URL", "")
