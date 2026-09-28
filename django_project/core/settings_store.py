"""Settings store — reads/writes jobhunt/config/profile.yaml + ui_settings.json.

Separation:
- profile.yaml = backend truth (sources, min_score, max_age, provider, search_terms, targets, candidate)
- ui_settings.json = frontend-only prefs (show_remote, show_links, hide_blockers, local_only, etc.)

GET /api/settings/ merges both + computed links.
PUT /api/settings/ accepts partial updates and persists to correct file.
"""
from pathlib import Path
import json
import os

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"

import sys  # noqa: E402
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import src  # noqa: E402,F401  (creates config/*.yaml|md|json from the *.example templates on first run)
PROFILE = ROOT / "config" / "profile.yaml"
UI_SETTINGS = ROOT / "config" / "ui_settings.json"

DEFAULT_UI = {
    "show_remote": True,      # False = hide remote jobs (onsite/local only)
    "remote_only": False,     # True = show ONLY remote jobs
    "show_links": True,       # show apply URLs / alt links in table + detail
    "show_salary": True,
    "hide_blockers": False,
    "local_only_default": False,
    "min_score_default": 0,
}

PROFILE_DEFAULTS = {
    "min_score_to_include": 35,
    "max_age_days": 30,
}


def _load_yaml():
    try:
        import yaml
        if not PROFILE.exists():
            return {}
        return yaml.safe_load(PROFILE.read_text()) or {}
    except Exception:
        return {}


def _save_yaml(data):
    import yaml
    PROFILE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _load_ui():
    try:
        if UI_SETTINGS.exists():
            return {**DEFAULT_UI, **json.loads(UI_SETTINGS.read_text())}
    except Exception:
        pass
    return dict(DEFAULT_UI)


def _save_ui(data):
    UI_SETTINGS.write_text(json.dumps(data, indent=2))


def get_settings():
    """Merged settings for GET."""
    prof = _load_yaml()
    ui = _load_ui()
    sources = prof.get("sources", {})
    filters = {
        "min_score_to_include": prof.get("min_score_to_include", 35),
        "max_age_days": prof.get("max_age_days", 30),
        "max_greenhouse_details_per_board": prof.get("max_greenhouse_details_per_board", 12),
        "keep_all_trinidad": bool(prof.get("keep_all_trinidad", True)),
        "trinidad_limit_per_source": prof.get("trinidad_limit_per_source", 40),
    }
    cover = prof.get("cover_letter", {"provider": "auto"})
    candidate = prof.get("candidate", {})
    search_terms = prof.get("search_terms", [])
    targets = prof.get("targets", {"tier_1": [], "tier_2": []})
    company_boards = prof.get("company_boards", {})
    bonus_domains = prof.get("bonus_domains", [])

    sheet_id = os.environ.get("SHEET_ID", "")
    links = {
        "sheet_id": sheet_id,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else "",
        "website": candidate.get("website", ""),
        "github": candidate.get("github", ""),
        "linkedin": candidate.get("linkedin", ""),
    }
    return {
        "preferences": ui,
        "sources": sources,
        "filters": filters,
        "cover_letter": cover,
        "candidate": {
            "name": candidate.get("name", ""),
            "email": candidate.get("email", ""),
            "location": candidate.get("location", ""),
            "website": candidate.get("website", ""),
            "github": candidate.get("github", ""),
            "linkedin": candidate.get("linkedin", ""),
        },
        "search_terms": search_terms,
        "targets": targets,
        "company_boards": company_boards,
        "bonus_domains": bonus_domains,
        "trinidad_custom_sites": prof.get("trinidad_custom_sites") or [],
        "links": links,
    }


def update_settings(payload):
    """Partial update. Returns merged settings. Raises ValueError on bad input."""
    if not isinstance(payload, dict):
        raise ValueError("settings payload must be an object")
    prof = _load_yaml()
    ui = _load_ui()

    # --- UI prefs (frontend only) ---
    if "preferences" in payload and isinstance(payload["preferences"], dict):
        for k, v in payload["preferences"].items():
            if k in DEFAULT_UI:
                # coerce bools/ints
                if isinstance(DEFAULT_UI[k], bool):
                    ui[k] = bool(v)
                elif isinstance(DEFAULT_UI[k], int):
                    ui[k] = int(v)
                else:
                    ui[k] = v
            else:
                raise ValueError(f"unknown preference: {k}")
        _save_ui(ui)

    # --- sources toggles ---
    if "sources" in payload:
        if not isinstance(payload["sources"], dict):
            raise ValueError("sources must be an object")
        prof_sources = prof.get("sources", {})
        for k, v in payload["sources"].items():
            prof_sources[k] = bool(v)
        prof["sources"] = prof_sources

    # --- filters ---
    if "filters" in payload:
        f = payload["filters"]
        if not isinstance(f, dict):
            raise ValueError("filters must be an object")
        if "min_score_to_include" in f:
            v = int(f["min_score_to_include"])
            if not (0 <= v <= 100):
                raise ValueError("min_score_to_include must be 0-100")
            prof["min_score_to_include"] = v
        if "max_age_days" in f:
            v = int(f["max_age_days"])
            if not (1 <= v <= 365):
                raise ValueError("max_age_days must be 1-365")
            prof["max_age_days"] = v
        if "keep_all_trinidad" in f:
            prof["keep_all_trinidad"] = bool(f["keep_all_trinidad"])
        if "trinidad_limit_per_source" in f:
            v = int(f["trinidad_limit_per_source"])
            if not (5 <= v <= 200):
                raise ValueError("trinidad_limit_per_source must be 5-200")
            prof["trinidad_limit_per_source"] = v
        if "max_greenhouse_details_per_board" in f:
            v = int(f["max_greenhouse_details_per_board"])
            if not (1 <= v <= 100):
                raise ValueError("max_greenhouse_details_per_board must be 1-100")
            prof["max_greenhouse_details_per_board"] = v

    # --- cover letter provider ---
    if "cover_letter" in payload:
        cl = payload["cover_letter"]
        if not isinstance(cl, dict):
            raise ValueError("cover_letter must be an object")
        prof_cl = prof.get("cover_letter", {})
        if "provider" in cl:
            if cl["provider"] not in ("auto", "claude_code", "ollama", "anthropic", "template"):
                raise ValueError("unknown provider")
            prof_cl["provider"] = cl["provider"]
        for k in ("ollama_model", "anthropic_model", "claude_code_model"):
            if k in cl:
                prof_cl[k] = str(cl[k])
        prof["cover_letter"] = prof_cl

    # --- search terms ---
    if "search_terms" in payload:
        st = payload["search_terms"]
        if not isinstance(st, list) or not all(isinstance(x, str) for x in st):
            raise ValueError("search_terms must be a list of strings")
        prof["search_terms"] = [s.strip() for s in st if s.strip()][:50]

    # --- targets ---
    if "targets" in payload:
        t = payload["targets"]
        if not isinstance(t, dict):
            raise ValueError("targets must be an object")
        prof_t = prof.get("targets", {})
        for k in ("tier_1", "tier_2"):
            if k in t:
                if not isinstance(t[k], list):
                    raise ValueError(f"targets.{k} must be a list")
                prof_t[k] = [str(x).strip() for x in t[k] if str(x).strip()][:50]
        prof["targets"] = prof_t

    # --- candidate links (website/github/linkedin editable) ---
    if "candidate" in payload:
        c = payload["candidate"]
        if not isinstance(c, dict):
            raise ValueError("candidate must be an object")
        prof_c = prof.get("candidate", {})
        for k in ("website", "github", "linkedin", "name", "email", "location"):
            if k in c:
                prof_c[k] = str(c[k])
        prof["candidate"] = prof_c

    # persist profile.yaml only if backend keys changed
    if any(k in payload for k in ("sources", "filters", "cover_letter", "search_terms", "targets", "candidate")):
        _save_yaml(prof)

    return get_settings()
