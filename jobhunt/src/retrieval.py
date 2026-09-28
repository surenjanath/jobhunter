"""
retrieval.py — the "RAG" half: split a resume into evidence chunks and retrieve the best chunk(s) for a
job requirement.

Two retrievers, combined:
  * lexical  — BM25 over stemmed tokens (always available, no dependencies)
  * semantic — cosine over embeddings from a local Ollama embedding model (nomic-embed-text, mxbai-embed-large,
               bge-*, all-minilm, snowflake-arctic-embed…) when one is installed. Picked automatically.

Retrieved chunks are *evidence*: they are shown to the user next to each job requirement, so a match is never a
black box ("Requirement: 3+ years Django  ->  Resume: 'Built Django REST APIs and PostgreSQL pipelines for 50,000 policies…'").
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter

log = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
_PREFERRED = ("nomic-embed-text", "mxbai-embed-large", "bge-m3", "bge-large", "snowflake-arctic-embed", "all-minilm", "embed")

STOP = set("""a an the and or of to in on for with by at from as is are be been being this that these those it its our your you we they
their will can may must should would could have has had not no nor but if then than so such into over under about across per via
etc job role team work working experience years year able ability strong good great excellent including include includes within
using use used new all any more most other some also who what when where which while both each very well""".split())


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------

def stem(w: str) -> str:
    for suf in ("ations", "ation", "ingly", "ments", "ment", "ities", "ity", "ings", "ing", "ies", "ied", "ers", "er", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-z][a-z0-9+#.]*[a-z0-9+#]|[a-z]", (text or "").lower().replace("_", " "))
    return [stem(t.strip(".")) for t in raw if t not in STOP and len(t) > 1]


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------

def chunk_profile(text: str, profile: dict) -> list[dict]:
    """Evidence chunks: one per experience bullet (labelled with its role), plus projects, summary, skills, education."""
    chunks: list[dict] = []

    def add(section, label, body):
        body = re.sub(r"\s+", " ", body or "").strip()
        if len(body) >= 20:
            chunks.append({"ord": len(chunks), "section": section, "label": label[:120], "text": body[:700]})

    if profile.get("summary"):
        add("summary", "Summary", profile["summary"])
    for r in profile.get("roles", []):
        label = " · ".join(x for x in (r.get("title"), r.get("company")) if x)
        dates = f"{r.get('start', '')}–{'present' if r.get('current') else r.get('end', '')}".strip("–")
        for b in r.get("bullets", []):
            add("experience", f"{label} ({dates})" if dates else label, b)
    for p in profile.get("projects", []):
        add("projects", p.get("name") or "Project", f"{p.get('name', '')}: {p.get('text', '')}")
    skills = profile.get("skills", {})
    if skills:
        by_cat: dict[str, list[str]] = {}
        for name, meta in skills.items():
            by_cat.setdefault(meta.get("category", "Other"), []).append(name)
        for cat, names in by_cat.items():
            add("skills", f"Skills · {cat}", f"{cat}: " + ", ".join(sorted(names)))
    for e in profile.get("education", []):
        add("education", "Education", e.get("text", ""))
    for c in profile.get("certifications", []):
        add("certifications", "Certification", c)
    if not chunks:  # unparseable layout: fall back to paragraphs
        for para in re.split(r"\n\s*\n", text):
            add("text", "Resume", para)
    return chunks


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.72):
        self.k1, self.b = k1, b
        self.toks = [tokens(d) for d in docs]
        self.tf = [Counter(t) for t in self.toks]
        self.len = [len(t) for t in self.toks]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 1.0
        df: Counter = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def score(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                f = tf.get(w, 0)
                if not f:
                    continue
                s += self.idf.get(w, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1)))
            out.append(s)
        return out

    def self_score(self, query: str) -> float:
        """Best conceivable score for this query (every term present once in an average-length doc)."""
        q = set(tokens(query))
        return sum(self.idf.get(w, math.log(1 + 1)) * (self.k1 + 1) / (1 + self.k1) for w in q) or 1.0


# ---------------------------------------------------------------------------
# embeddings (optional)
# ---------------------------------------------------------------------------

def _http_json(path: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{OLLAMA_HOST}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def embedding_model() -> str:
    """Name of an installed Ollama embedding model, or ''."""
    try:
        names = [m.get("name", "") for m in _http_json("/api/tags", timeout=3).get("models", [])]
    except Exception:  # noqa: BLE001
        return ""
    for pref in _PREFERRED:
        for n in names:
            if pref in n.lower():
                return n
    return ""


def embed(texts: list[str], model: str) -> list[list[float]] | None:
    """Embed a batch. Returns None if the model/server can't do it (callers fall back to lexical)."""
    if not texts or not model:
        return None
    try:
        data = _http_json("/api/embed", {"model": model, "input": [t[:2000] for t in texts]}, timeout=120)
        vecs = data.get("embeddings")
        if vecs and len(vecs) == len(texts):
            return vecs
    except Exception as exc:  # noqa: BLE001
        log.info("  /api/embed failed (%s); trying legacy endpoint", repr(exc)[:80])
    try:  # older Ollama
        out = []
        for t in texts:
            out.append(_http_json("/api/embeddings", {"model": model, "prompt": t[:2000]}, timeout=60)["embedding"])
        return out
    except Exception as exc:  # noqa: BLE001
        log.info("  embeddings unavailable: %s", repr(exc)[:80])
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# the index
# ---------------------------------------------------------------------------

# Where evidence comes from matters: a real experience bullet proves more than a line in a skills list.
SECTION_WEIGHT = {"experience": 1.0, "projects": 0.9, "summary": 0.8, "certifications": 0.8, "education": 0.7, "skills": 0.7}


class ResumeIndex:
    def __init__(self, chunks: list[dict], embed_model: str = ""):
        self.chunks = chunks
        self.embed_model = embed_model
        self.bm25 = BM25([c["text"] + " " + c.get("label", "") for c in chunks])
        self.vecs = [json.loads(c["embedding"]) if isinstance(c.get("embedding"), str) and c.get("embedding") else c.get("embedding")
                     for c in chunks]
        self.has_vectors = bool(chunks) and all(v for v in self.vecs)

    def retrieve(self, query: str, k: int = 2, qvec: list[float] | None = None) -> list[dict]:
        """Top-k chunks with a 0..1 `score`, plus `lexical` and `semantic` parts for transparency."""
        if not self.chunks:
            return []
        lex = self.bm25.score(query)
        denom = self.bm25.self_score(query)
        q_tokens = set(tokens(query))
        scored = []
        for i, c in enumerate(self.chunks):
            c_tokens = set(tokens(c["text"] + " " + c.get("label", "")))
            overlap = len(q_tokens & c_tokens) / len(q_tokens) if q_tokens else 0.0
            lexical = min(1.0, 0.55 * min(1.0, lex[i] / denom * 1.6) + 0.45 * overlap)
            sem = None
            if qvec is not None and self.has_vectors:
                sem = max(0.0, min(1.0, (cosine(qvec, self.vecs[i]) - 0.42) / 0.38))
            score = lexical if sem is None else max(lexical, 0.5 * lexical + 0.5 * sem, sem * 0.95)
            score *= SECTION_WEIGHT.get(c.get("section"), 0.85)
            scored.append((score, lexical, sem, i))
        scored.sort(reverse=True)
        out = []
        for score, lexical, sem, i in scored[:k]:
            c = self.chunks[i]
            out.append({"score": round(score, 3), "lexical": round(lexical, 3), "semantic": None if sem is None else round(sem, 3),
                        "section": c["section"], "label": c["label"], "text": c["text"]})
        return out
