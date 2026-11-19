"""Security helpers: webhook signatures, PII redaction, small-group suppression."""
import hashlib
import hmac
import re

K_MIN = 5  # k-anonymity threshold: never show a group smaller than this


# ---------- webhook signatures (Ashby scheme) ----------
# Ashby sends:  Ashby-Signature: sha256=<hex HMAC-SHA256 of the RAW request body>
# keyed with the webhook's secret token. Source: developers.ashbyhq.com/docs/authenticating-webhooks
def sign(secret: str, raw_body: bytes) -> str:
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def verify_signature(secret: str, raw_body: bytes, header_value) -> bool:
    """True only if the header matches. Uses a constant-time compare (no timing leaks)."""
    if not secret or not header_value:
        return False
    return hmac.compare_digest(sign(secret, raw_body), header_value.strip())


# ---------- PII redaction ----------
# Applied to audit-log text, escalation summaries and anything sent to an LLM provider.
# Order matters: the most specific patterns first.
_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD]"),
    (re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"[$£€]\s?\d[\d,]*(?:\.\d+)?\s?[kKmM]?"), "[AMOUNT]"),
]


def redact(text, money=True) -> str:
    """Replace emails, phone numbers, SSNs, card numbers and (optionally) money amounts with tags."""
    out = str(text)
    for pattern, tag in _PATTERNS:
        if tag == "[AMOUNT]" and not money:
            continue
        out = pattern.sub(tag, out)
    return out


# ---------- k-anonymity ----------
def suppress_small_cells(rows, count_key="n", hide_keys=(), k=K_MIN):
    """Hide any group with fewer than k people.

    For each row whose count is below k: the count and every field in `hide_keys`
    become None and `suppressed` is set to True (the UI shows "<5").
    Shortcut: this is simple cell suppression; with several breakdowns shown at once
    a determined person could still subtract. Upgrade: complementary suppression.
    """
    result = []
    for row in rows:
        row = dict(row)
        small = row.get(count_key) is not None and row[count_key] < k
        row["suppressed"] = small
        if small:
            row[count_key] = None
            for key in hide_keys:
                row[key] = None
        result.append(row)
    return result
