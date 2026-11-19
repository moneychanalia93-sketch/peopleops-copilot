"""Language models behind one tiny interface.

    model.complete(system, messages, tools) -> {"text": str | None, "tool_calls": [{"id", "name", "args"}]}

Messages use one simple shape for every provider:
    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [...]}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "<json>"}

Three implementations:
  MockModel       default. Offline, deterministic, zero cost. A rule-based stand-in that
                  makes the same tool-calling decisions an LLM would, so the demo and the
                  tests need no API key. Its answers are EXTRACTIVE: it copies sentences
                  from the handbook section it retrieved, so it cannot invent facts.
  AnthropicModel  used when ANTHROPIC_API_KEY is set (Messages API with tool use).
  OpenAIModel     used when OPENAI_API_KEY is set (Chat Completions with function calling).
HONEST STATUS: the two live classes were written from the providers' public docs and unit-
tested only for message translation; they were not run against the live APIs in this build.
"""
import json
import os
import re

from .adapters.http import call_json
from .retrieval import tokens


class ModelError(Exception):
    pass


def _call(name, args, n=1):
    return {"text": None, "tool_calls": [{"id": f"call_{name}_{n}", "name": name, "args": args}]}


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if s.strip()]


IT_WORDS = r"\b(laptop|computer|monitor|keyboard|mouse|headset|vpn|wi-?fi|okta|password|log ?in|account|licen[cs]e|software|access to|badge|phone|screen|charger)\b"
IT_PROBLEM = r"\b(broken|cracked|not working|isn'?t working|doesn'?t work|won'?t|can'?t|cannot|need|stolen|lost|crash\w*|stopped|locked out|replacement|request|install)\b"
QUESTION_START = r"^(how|what|where|when|why|which|who|can|do|does|am|is|are|should|will)\b"


class MockModel:
    name = "mock-offline"

    def complete(self, system, messages, tools):
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        last = messages[-1]
        if last["role"] != "tool":
            return self._plan(question)
        return self._finish(question, last)

    # ---- step 1: decide which tool to call ----
    def _plan(self, q):
        low = q.lower()
        if re.search(r"\b(onboarding|checklist)\b", low) and re.search(r"\b(status|progress|going|how is|how's|my|tasks|left|remaining)\b", low):
            m = re.search(r"((?:[A-Z][\w'-]+ ?)+)'s onboarding", q)
            return _call("get_onboarding_status", {"employee": m.group(1).strip()} if m else {})
        if re.search(r"\b(schedule|set up|book)\b", low) and re.search(r"check-?in|1:1|one[- ]on[- ]one", low):
            n = re.search(r"day[- ]?(\d+)|(\d+)[- ]day", low)
            day = (n.group(1) or n.group(2)) if n else None
            args = {"kind": f"day-{day}" if day in ("1", "7", "30") else "one-on-one"}
            who = re.search(r"\bfor ((?:[A-Z][\w'-]+ ?)+)", q)
            if who:
                args["employee"] = who.group(1).strip()
            return _call("schedule_checkin", args)
        if re.search(r"\b(draft|write|compose|post|send)\b", low) and re.search(r"\bslack\b|#[a-z]", low):
            channel = re.search(r"#[a-z0-9_-]+", q)
            body = re.split(r"\b(?:saying|that says|reminding|announcing)\b\s*|:\s*", q, maxsplit=1)
            text = body[1].strip() if len(body) > 1 and body[1].strip() else q
            return _call("draft_slack_message", {"channel": channel.group(0) if channel else "#general", "text": text})
        if re.search(r"\b(talk|speak) to (?:a |an )?(?:human|person|someone)\b", low):
            return _call("escalate_to_people_team", {"category": "other", "summary": f"Employee asked for a person: {q}"})
        if re.search(IT_WORDS, low) and re.search(IT_PROBLEM, low) and not re.match(QUESTION_START, low):
            return _call("create_it_ticket", {"summary": _sentences(q)[0][:100], "description": q})
        return _call("search_handbook", {"query": q})

    # ---- step 2: turn the tool result into the final reply ----
    def _finish(self, q, tool_msg):
        result = json.loads(tool_msg["content"])
        name = tool_msg["name"]
        if "error" in result:
            return {"text": f"I could not do that: {result.get('detail', result['error'])}", "tool_calls": []}
        if name == "search_handbook":
            hits = result["results"]
            if not hits:
                return _call("escalate_to_people_team", {"category": "unanswerable",
                                                         "summary": f"No confident handbook answer for: {q}"}, 2)
            top, qt = hits[0], set(tokens(q))
            sents = _sentences(top["text"])
            ranked = sorted(range(len(sents)), key=lambda i: -len(qt & set(tokens(sents[i]))))[:2]
            body = " ".join(sents[i] for i in sorted(ranked))
            return {"text": f"{body} [{top['cite']}]", "tool_calls": []}
        if name == "get_onboarding_status":
            if not result["found"]:
                return {"text": f"There is no onboarding plan on file for {result['employee']}.", "tool_calls": []}
            nxt = "; ".join(f"{t['title']} (due {t['due']})" for t in result["next_tasks"]) or "nothing left"
            return {"text": f"{result['employee']}: {result['done']} of {result['total']} onboarding tasks are done "
                            f"({result['pct']}%). Next up: {nxt}.", "tool_calls": []}
        if result.get("status") == "pending_approval":
            return {"text": f"Done on my side. I queued this for a People team member to approve (request #{result['approval_id']}): "
                            f"{result['summary'].rstrip('.')}. Nothing happens until they approve it.", "tool_calls": []}
        if name == "escalate_to_people_team":
            return {"text": f"I could not answer this reliably, so I passed it to {result['owner']} "
                            f"(case #{result['escalation_id']}). A person will follow up.", "tool_calls": []}
        return {"text": "Done.", "tool_calls": []}


def _tool_defs(tools):
    return [{"name": n, "description": t["description"], "schema": t["schema"]} for n, t in tools.items()]


class AnthropicModel:
    """Anthropic Messages API. POST https://api.anthropic.com/v1/messages"""

    def __init__(self, api_key, model=None):
        self.key = api_key
        self.name = model or os.environ.get("PEOPLEOPS_MODEL_NAME", "claude-sonnet-4-5")

    @staticmethod
    def translate(messages):
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m.get("tool_calls", [])]
                out.append({"role": "assistant", "content": blocks})
            else:  # tool result: must be a user message; consecutive results share one message
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def complete(self, system, messages, tools):
        body = {"model": self.name, "max_tokens": 700, "system": system, "messages": self.translate(messages),
                "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in _tool_defs(tools)]}
        try:
            reply = call_json("POST", "https://api.anthropic.com/v1/messages",
                              {"x-api-key": self.key, "anthropic-version": "2023-06-01"}, body, timeout=60)
        except Exception as exc:  # noqa: BLE001
            raise ModelError(type(exc).__name__) from exc
        text = "".join(b.get("text", "") for b in reply.get("content", []) if b["type"] == "text") or None
        calls = [{"id": b["id"], "name": b["name"], "args": b["input"]} for b in reply.get("content", []) if b["type"] == "tool_use"]
        return {"text": text, "tool_calls": calls}


class OpenAIModel:
    """OpenAI Chat Completions with function calling. POST https://api.openai.com/v1/chat/completions"""

    def __init__(self, api_key, model=None):
        self.key = api_key
        self.name = model or os.environ.get("PEOPLEOPS_MODEL_NAME", "gpt-4o-mini")

    @staticmethod
    def translate(system, messages):
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                    for c in m["tool_calls"]]})
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def complete(self, system, messages, tools):
        body = {"model": self.name, "messages": self.translate(system, messages),
                "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]}}
                          for t in _tool_defs(tools)]}
        try:
            reply = call_json("POST", "https://api.openai.com/v1/chat/completions",
                              {"Authorization": f"Bearer {self.key}"}, body, timeout=60)
            msg = reply["choices"][0]["message"]
            calls = [{"id": c["id"], "name": c["function"]["name"], "args": json.loads(c["function"]["arguments"] or "{}")}
                     for c in msg.get("tool_calls") or []]
        except Exception as exc:  # noqa: BLE001
            raise ModelError(type(exc).__name__) from exc
        return {"text": msg.get("content"), "tool_calls": calls}


def get_model():
    """Pick the model from the environment. PEOPLEOPS_MODEL=mock forces the offline model."""
    choice = os.environ.get("PEOPLEOPS_MODEL", "").lower()
    if choice != "mock":
        if os.environ.get("ANTHROPIC_API_KEY") and choice in ("", "anthropic"):
            return AnthropicModel(os.environ["ANTHROPIC_API_KEY"])
        if os.environ.get("OPENAI_API_KEY") and choice in ("", "openai"):
            return OpenAIModel(os.environ["OPENAI_API_KEY"])
    return MockModel()
