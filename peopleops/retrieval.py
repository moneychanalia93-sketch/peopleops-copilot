"""Handbook search: BM25 ranking over markdown sections, with citations.

BM25 is the classic keyword-ranking formula. It rewards sections that contain the
rare words from the question and discounts very long sections. No AI model is used,
so the same question always finds the same sections (easy to test and explain).

Every result carries a citation like `pto-and-sick-time#carryover` (document#section).
"""
import math
import re
from functools import lru_cache
from pathlib import Path

from . import config

STOPWORDS = set("""a an and are as at be by can could do does for from get got has have how i if in is it its
me my of on or our should so than that the their them then there these they this to us was we what when where which
who why will with would you your many much any some each about into out up about need want please""".split())

MIN_COVERAGE = 0.6   # share of the question's content words that must appear in the section
MIN_SCORE = 2.0      # BM25 score floor; below this we say "I don't know" instead of guessing


def stem(word: str) -> str:
    """Very light stemmer so 'approves', 'approved' and 'approval' meet each other."""
    for suffix in ("ment", "ing", "ed", "es", "al", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    word = word[:-1] if word.endswith("e") and len(word) > 3 else word
    return word[:-1] if len(word) > 3 and word[-1] == word[-2] else word  # submitt -> submit, enroll -> enrol


def tokens(text: str):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_doc(path: Path):
    """Return (front_matter dict, list of (section_title, section_text))."""
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    meta = {}
    if raw.startswith("---\n"):
        header, _, raw = raw[4:].partition("\n---\n")
        meta = dict(line.split(":", 1) for line in header.splitlines() if ":" in line)
        meta = {k.strip(): v.strip() for k, v in meta.items()}
    sections = []
    for block in re.split(r"^## ", raw, flags=re.M)[1:]:
        title, _, body = block.partition("\n")
        sections.append((title.strip(), body.strip()))
    return meta, sections


class Handbook:
    def __init__(self, folder):
        self.chunks = []
        for path in sorted(Path(folder).glob("*.md")):
            meta, sections = _parse_doc(path)
            for title, body in sections:
                # The section title is counted twice so a matching heading ranks higher.
                toks = tokens(f"{meta.get('title', '')} {title} {title} {body}")
                self.chunks.append({"doc": path.stem, "doc_title": meta.get("title", path.stem),
                                    "audience": meta.get("audience", "all"), "section": slug(title),
                                    "section_title": title, "text": body, "tokens": toks})
        n = len(self.chunks)
        self.avg_len = sum(len(c["tokens"]) for c in self.chunks) / max(n, 1)
        df = {}
        for c in self.chunks:
            for t in set(c["tokens"]):
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, audiences=("all",), limit=3, k1=1.5, b=0.75):
        """Best sections for the question. Returns [] when nothing is a confident match."""
        q = list(dict.fromkeys(tokens(query)))
        if not q:
            return []
        results = []
        for c in self.chunks:
            if c["audience"] not in audiences:
                continue
            counts = {t: c["tokens"].count(t) for t in q}
            matched = [t for t in q if counts[t]]
            if not matched:
                continue
            length_norm = 1 - b + b * len(c["tokens"]) / self.avg_len
            score = sum(self.idf.get(t, 0) * counts[t] * (k1 + 1) / (counts[t] + k1 * length_norm) for t in matched)
            results.append({"doc": c["doc"], "doc_title": c["doc_title"], "section": c["section"],
                            "section_title": c["section_title"], "cite": f"{c['doc']}#{c['section']}",
                            "score": round(score, 2), "coverage": round(len(matched) / len(q), 2), "text": c["text"]})
        results.sort(key=lambda r: -r["score"])
        return [r for r in results[:limit] if r["score"] >= MIN_SCORE and r["coverage"] >= MIN_COVERAGE]


@lru_cache(maxsize=1)
def get_handbook(folder: str | None = None) -> Handbook:
    return Handbook(folder or config.ROOT / "content" / "handbook")
