"""
profile_store.py — the user's resume profile: versions, edits, search preferences.

* Resume versions live in SQLite (resume_versions + resume_chunks). Exactly one is active.
* The parsed profile is machine-extracted; the user can correct it (add/remove skills, set years). Those
  edits are kept separately as `overrides` so re-parsing or re-uploading never destroys them, and every
  manual skill is marked source="manual".
* Search preferences (remote vs local, salary floor, regions, avoid-list…) live in config/profile.yaml
  under `preferences`, next to the rest of the scanner config.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src import db, resume_parse, retrieval
from src import skills_taxonomy as tax

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PROFILE_YAML = ROOT / "config" / "profile.yaml"
def _find_bootstrap_resume() -> Path:
    """A resume already on disk (docs/resume.md, config/resume.md, or any docs/*resume*.md) adopted on first run."""
    for cand in (ROOT.parent / "docs" / "resume.md", ROOT / "config" / "resume.md"):
        if cand.exists():
            return cand
    found = sorted((ROOT.parent / "docs").glob("*[Rr]esume*.md")) if (ROOT.parent / "docs").exists() else []
    return found[0] if found else ROOT.parent / "docs" / "resume.md"


BOOTSTRAP_RESUME = _find_bootstrap_resume()

_lock = threading.RLock()
_cache: dict = {"stamp": 0.0, "profile": None, "index": None, "id": None, "key": None}
_TTL = 5.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def invalidate() -> None:
    with _lock:
        _cache.update(stamp=0.0, profile=None, index=None, id=None, key=None)


# ---------------------------------------------------------------------------
# preferences
# ---------------------------------------------------------------------------

WORK_MODES = ("both", "local_first", "remote_first", "local_only", "remote_only")
DEFAULT_PREFS = {
    "work_mode": "both",
    "min_salary_monthly_ttd": 0,
    "min_salary_monthly_usd": 0,
    "target_titles": [],
    "avoid_keywords": [],
    "preferred_regions": [],
    "willing_to_relocate": False,
    "open_to_contract": True,
    "fx_ttd_per_usd": 6.78,
}


def get_prefs() -> dict:
    try:
        raw = (yaml.safe_load(PROFILE_YAML.read_text()) or {}).get("preferences") or {}
    except Exception:  # noqa: BLE001
        raw = {}
    prefs = {**DEFAULT_PREFS, **{k: v for k, v in raw.items() if k in DEFAULT_PREFS}}
    if prefs["work_mode"] not in WORK_MODES:
        prefs["work_mode"] = "both"
    return prefs


def validate_prefs(patch: dict) -> dict:
    out: dict = {}
    for k, v in patch.items():
        if k not in DEFAULT_PREFS:
            raise ValueError(f"unknown preference: {k}")
        if k == "work_mode":
            if v not in WORK_MODES:
                raise ValueError(f"work_mode must be one of {', '.join(WORK_MODES)}")
            out[k] = v
        elif k in ("min_salary_monthly_ttd", "min_salary_monthly_usd"):
            n = float(v or 0)
            if n < 0 or n > 10_000_000:
                raise ValueError(f"{k} out of range")
            out[k] = int(n)
        elif k == "fx_ttd_per_usd":
            n = float(v)
            if not (3 <= n <= 15):
                raise ValueError("fx_ttd_per_usd must be between 3 and 15")
            out[k] = n
        elif k in ("willing_to_relocate", "open_to_contract"):
            out[k] = bool(v)
        else:  # lists of strings
            if not isinstance(v, list):
                raise ValueError(f"{k} must be a list")
            out[k] = [str(x).strip()[:80] for x in v if str(x).strip()][:40]
    return out


def save_prefs(patch: dict) -> dict:
    clean = validate_prefs(patch)
    data = yaml.safe_load(PROFILE_YAML.read_text()) or {}
    prefs = {**DEFAULT_PREFS, **(data.get("preferences") or {}), **clean}
    data["preferences"] = prefs
    PROFILE_YAML.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    invalidate()
    return get_prefs()


# ---------------------------------------------------------------------------
# resume versions
# ---------------------------------------------------------------------------

def import_resume(data: bytes | str, filename: str = "resume.md", source: str = "upload", *, embed: bool = True,
                  activate: bool = True) -> dict:
    """Parse + index a resume, store it, make it active. Returns a summary."""
    text = resume_parse.normalise(data) if isinstance(data, str) else resume_parse.extract_text(data, filename)
    if isinstance(data, str) and len(text) < 80:
        raise resume_parse.ResumeError("resume text is too short")
    profile = resume_parse.parse_resume(text)
    chunks = retrieval.chunk_profile(text, profile)
    model = retrieval.embedding_model() if embed else ""
    vecs = retrieval.embed([c["text"] for c in chunks], model) if model else None
    if vecs is None:
        model = ""
    with db._lock:
        c = db._conn()
        cur = c.execute("INSERT INTO resume_versions(filename,source,text,profile_json,overrides_json,active,embed_model,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?)", (filename[:200], source, text, json.dumps(profile), "{}", 0, model, _now()))
        rid = cur.lastrowid
        c.executemany("INSERT INTO resume_chunks(resume_id,ord,section,label,text,embedding) VALUES(?,?,?,?,?,?)",
                      [(rid, ch["ord"], ch["section"], ch["label"], ch["text"], json.dumps(vecs[i]) if vecs else "")
                       for i, ch in enumerate(chunks)])
        c.commit()
        c.close()
    if activate:
        set_active(rid)
    invalidate()
    return {"id": rid, "filename": filename, "chunks": len(chunks), "embedding_model": model, "skills": len(profile["skills"]),
            "years_experience": profile["years_experience"], "roles": len(profile["roles"])}


def set_active(rid: int) -> None:
    with db._lock:
        c = db._conn()
        if not c.execute("SELECT 1 FROM resume_versions WHERE id=?", (rid,)).fetchone():
            c.close()
            raise KeyError(rid)
        c.execute("UPDATE resume_versions SET active=CASE WHEN id=? THEN 1 ELSE 0 END", (rid,))
        c.commit()
        c.close()
    invalidate()


def delete_version(rid: int) -> None:
    with db._lock:
        c = db._conn()
        c.execute("DELETE FROM resume_chunks WHERE resume_id=?", (rid,))
        c.execute("DELETE FROM resume_versions WHERE id=?", (rid,))
        if not c.execute("SELECT 1 FROM resume_versions WHERE active=1").fetchone():
            c.execute("UPDATE resume_versions SET active=1 WHERE id=(SELECT MAX(id) FROM resume_versions)")
        c.commit()
        c.close()
    invalidate()


def list_versions() -> list[dict]:
    c = db._conn()
    rows = [dict(r) for r in c.execute(
        "SELECT v.id, v.filename, v.source, v.active, v.embed_model, v.created_at, v.profile_json, "
        "(SELECT COUNT(*) FROM resume_chunks k WHERE k.resume_id=v.id) AS chunks FROM resume_versions v ORDER BY v.id DESC")]
    c.close()
    out = []
    for r in rows:
        p = json.loads(r.pop("profile_json"))
        r.update(active=bool(r["active"]), skills=len(p.get("skills", {})), years=p.get("years_experience"),
                 name=(p.get("contact") or {}).get("name", ""))
        out.append(r)
    return out


def _active_row():
    c = db._conn()
    row = c.execute("SELECT * FROM resume_versions WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    return dict(row) if row else None


def bootstrap_if_empty() -> bool:
    """First run: adopt the resume already in docs/ so the system works before anything is uploaded."""
    c = db._conn()
    n = c.execute("SELECT COUNT(*) FROM resume_versions").fetchone()[0]
    c.close()
    if n or not BOOTSTRAP_RESUME.exists():
        return False
    try:
        import_resume(BOOTSTRAP_RESUME.read_text(), BOOTSTRAP_RESUME.name, source="bootstrap (docs/)", embed=False)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("bootstrap resume failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# effective profile (parsed + user edits)
# ---------------------------------------------------------------------------

def apply_overrides(profile: dict, ov: dict) -> dict:
    p = json.loads(json.dumps(profile))  # deep copy
    skills = p.setdefault("skills", {})
    for name in ov.get("skills_remove", []):
        skills.pop(name, None)
    for name, meta in (ov.get("skills_add") or {}).items():
        skills[name] = {"category": meta.get("category") or tax.CATEGORY.get(name, "Other"), "mentions": 1,
                        "in_skills_section": True, "years": float(meta.get("years", 0) or 0), "recent": True, "source": "manual"}
    for name, yrs in (ov.get("skill_years") or {}).items():
        if name in skills:
            skills[name]["years"] = float(yrs)
    p["domains"] = sorted(n for n in skills if n in resume_parse._DOMAIN_SKILLS)   # follows removals / additions
    if ov.get("years_experience") not in (None, ""):
        p["years_experience"] = float(ov["years_experience"])
        p["seniority"] = resume_parse.seniority(p["years_experience"], p.get("titles", []))
    if ov.get("target_titles"):
        p["target_titles"] = ov["target_titles"]
    p["overrides"] = ov
    return p


def update_overrides(rid: int, patch: dict) -> dict:
    """patch keys: add_skills [{name,years}], remove_skills [name], restore_skills [name], skill_years {name: yrs},
    years_experience, target_titles [str]."""
    with db._lock:
        c = db._conn()
        row = c.execute("SELECT overrides_json FROM resume_versions WHERE id=?", (rid,)).fetchone()
        if not row:
            c.close()
            raise KeyError(rid)
        ov = json.loads(row[0] or "{}")
        ov.setdefault("skills_add", {})
        ov.setdefault("skills_remove", [])
        for item in patch.get("add_skills", []) or []:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            canon = next((k for k in tax.TAXONOMY if k.lower() == name.lower()), name)
            ov["skills_add"][canon] = {"years": float(item.get("years", 0) or 0), "category": item.get("category") or tax.CATEGORY.get(canon, "Other")}
            if canon in ov["skills_remove"]:
                ov["skills_remove"].remove(canon)
        for name in patch.get("remove_skills", []) or []:
            ov["skills_add"].pop(name, None)
            if name not in ov["skills_remove"]:
                ov["skills_remove"].append(name)
        for name in patch.get("restore_skills", []) or []:
            if name in ov["skills_remove"]:
                ov["skills_remove"].remove(name)
        if "skill_years" in patch:
            ov.setdefault("skill_years", {}).update({k: float(v) for k, v in (patch["skill_years"] or {}).items()})
        if "years_experience" in patch:
            ov["years_experience"] = patch["years_experience"]
        if "target_titles" in patch:
            ov["target_titles"] = [str(t).strip()[:80] for t in patch["target_titles"] if str(t).strip()][:20]
        c.execute("UPDATE resume_versions SET overrides_json=? WHERE id=?", (json.dumps(ov), rid))
        c.commit()
        c.close()
    invalidate()
    return ov


def active_profile() -> dict | None:
    """The effective profile of the active resume (cached ~5s). None when there is no resume."""
    with _lock:
        if _cache["profile"] is not None and time.time() - _cache["stamp"] < _TTL:
            return _cache["profile"]
    row = _active_row()
    if not row:
        return None
    prof = apply_overrides(json.loads(row["profile_json"]), json.loads(row["overrides_json"] or "{}"))
    prof["_resume_id"] = row["id"]
    prof["_filename"] = row["filename"]
    with _lock:
        _cache.update(stamp=time.time(), profile=prof, id=row["id"], index=None)
    return prof


def active_index() -> retrieval.ResumeIndex | None:
    prof = active_profile()
    if not prof:
        return None
    with _lock:
        if _cache["index"] is not None and _cache["id"] == prof["_resume_id"]:
            return _cache["index"]
    c = db._conn()
    chunks = [dict(r) for r in c.execute("SELECT ord,section,label,text,embedding FROM resume_chunks WHERE resume_id=? ORDER BY ord",
                                         (prof["_resume_id"],))]
    model = (c.execute("SELECT embed_model FROM resume_versions WHERE id=?", (prof["_resume_id"],)).fetchone() or [""])[0]
    c.close()
    idx = retrieval.ResumeIndex(chunks, model)
    with _lock:
        _cache["index"] = idx
    return idx


def reindex(rid: int | None = None) -> dict:
    """(Re)compute embeddings for a resume — e.g. after `ollama pull nomic-embed-text`."""
    prof = active_profile() if rid is None else None
    rid = rid or (prof or {}).get("_resume_id")
    if not rid:
        raise KeyError("no resume")
    model = retrieval.embedding_model()
    c = db._conn()
    rows = c.execute("SELECT id, text FROM resume_chunks WHERE resume_id=? ORDER BY ord", (rid,)).fetchall()
    c.close()
    vecs = retrieval.embed([r["text"] for r in rows], model) if model else None
    with db._lock:
        c = db._conn()
        if vecs:
            for r, v in zip(rows, vecs):
                c.execute("UPDATE resume_chunks SET embedding=? WHERE id=?", (json.dumps(v), r["id"]))
            c.execute("UPDATE resume_versions SET embed_model=? WHERE id=?", (model, rid))
        else:
            c.execute("UPDATE resume_chunks SET embedding='' WHERE resume_id=?", (rid,))
            c.execute("UPDATE resume_versions SET embed_model='' WHERE id=?", (rid,))
        c.commit()
        c.close()
    invalidate()
    return {"embedding_model": model if vecs else "", "chunks": len(rows), "semantic": bool(vecs),
            "hint": "" if vecs else "No embedding model found. Run: ollama pull nomic-embed-text"}


def status() -> dict:
    prof = active_profile()
    idx = active_index() if prof else None
    return {
        "has_resume": bool(prof),
        "resume_id": (prof or {}).get("_resume_id"),
        "filename": (prof or {}).get("_filename", ""),
        "chunks": len(idx.chunks) if idx else 0,
        "semantic": bool(idx and idx.has_vectors),
        "embedding_model_index": idx.embed_model if idx else "",
        "embedding_model_available": retrieval.embedding_model(),
    }


def set_llm_enrichment(rid: int, llm_block: dict) -> None:
    with db._lock:
        c = db._conn()
        row = c.execute("SELECT profile_json FROM resume_versions WHERE id=?", (rid,)).fetchone()
        if not row:
            c.close()
            raise KeyError(rid)
        p = json.loads(row[0])
        p["llm"] = llm_block
        c.execute("UPDATE resume_versions SET profile_json=? WHERE id=?", (json.dumps(p), rid))
        c.commit()
        c.close()
    invalidate()


def get_resume_text(rid: int) -> str:
    c = db._conn()
    row = c.execute("SELECT text FROM resume_versions WHERE id=?", (rid,)).fetchone()
    c.close()
    return row[0] if row else ""
