"""Team chat: Slack.

Interface:  post_message(channel, text) -> {"delivered_to": "...", ...}
By default messages go to a local file (the "outbox"), so a demo can never message real people.
Set SLACK_WEBHOOK_URL to switch to a real Slack incoming webhook.
"""
import json
from datetime import datetime, timezone

from .. import config
from .http import call_json


class MockSlack:
    """Appends one JSON line per message to var/slack_outbox.jsonl."""

    def post_message(self, channel, text):
        path = config.outbox_path()
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "channel": channel, "text": text}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return {"delivered_to": f"outbox:{path.name}", "channel": channel}


class SlackWebhook:
    """REAL. Slack incoming webhook: POST <SLACK_WEBHOOK_URL> with {"text": "..."}.
    An incoming webhook is tied to ONE channel chosen when it was created, so `channel`
    is only shown as a prefix here. For per-channel posting use chat.postMessage
    (POST https://slack.com/api/chat.postMessage, header `Authorization: Bearer xoxb-...`,
    body {"channel": "#general", "text": "..."}).
    NOT run against a live workspace.
    """

    def __init__(self, url):
        self.url = url

    def post_message(self, channel, text):
        call_json("POST", self.url, {}, {"text": f"[{channel}] {text}"})
        return {"delivered_to": "slack-webhook", "channel": channel}
