"""
ai_match.py — how closely your resume reads like this posting (semantic when possible).

With an Ollama embedding model installed the resume passages and the posting are compared by meaning (cosine);
otherwise retrieval is BM25 over the same passages. Either way the score comes from YOUR active resume, and the
passages that matched best are returned so the number can be checked.
"""

from __future__ import annotations

import re

from src import matching, profile_store, retrieval


def semantic_score(job: dict, resume_text: str | None = None) -> dict:
    idx = profile_store.active_index()
    if not idx:
        return {"score": 0, "method": "none", "cosine": 0, "explanation": "Add a resume on the Profile page first.", "passages": []}
    jd = f"{job.get('title', '')}\n{(job.get('description') or '')[:3000]}"
    a = matching.analyze_job(job)
    reqs = a["requirements"] or [s.strip() for s in re.split(r"(?<=[.!?])\s+", job.get("description") or "") if 30 < len(s) < 240][:8]
    qvecs = None
    method = "bm25"
    if idx.has_vectors and idx.embed_model:
        qvecs = retrieval.embed(reqs + [jd[:1500]], idx.embed_model)
        method = "embeddings + bm25" if qvecs else "bm25"
    scores, passages = [], []
    for i, r in enumerate(reqs):
        hit = (idx.retrieve(r, k=1, qvec=qvecs[i] if qvecs else None) or [None])[0]
        if hit:
            scores.append(hit["score"])
            passages.append({"requirement": r[:160], "passage": hit["text"][:260], "where": hit["label"], "score": round(hit["score"], 2)})
    whole = None
    if qvecs:
        sims = [retrieval.cosine(qvecs[-1], v) for v in idx.vecs if v]
        whole = round(sum(sorted(sims, reverse=True)[:3]) / max(1, min(3, len(sims))), 3) if sims else None
    base = sum(scores) / len(scores) if scores else 0.0
    score = round(100 * min(1.0, base * 1.2))
    passages.sort(key=lambda p: -p["score"])
    return {
        "score": score, "method": method, "cosine": whole if whole is not None else round(base, 3),
        "explanation": (f"{len(scores)} posting requirements compared with your resume passages ({method}); "
                        f"{sum(s >= 0.5 for s in scores)} answered well, {sum(s < 0.3 for s in scores)} not at all."
                        if scores else "The posting has no separable requirements to compare."),
        "passages": passages[:5],
        "top_terms": [k for k, v in list(a["skills"].items())[:8]],
    }


def batch(jobs: list[dict]) -> list[dict]:
    for j in jobs:
        j["ai_match"] = semantic_score(j)
    jobs.sort(key=lambda x: x["ai_match"]["score"], reverse=True)
    return jobs
