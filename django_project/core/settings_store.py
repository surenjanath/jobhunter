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
            if cl["provider"] not in _llm().PROVIDERS:
                raise ValueError("unknown provider")
            prof_cl["provider"] = cl["provider"]
        for k in MODEL_KEYS():
            if k in cl:
                prof_cl[k] = str(cl[k]).strip()[:120]
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


# --- AI providers (Settings page; API keys live in config/llm_keys.json and never leave the server) ---------------------

def _llm():
    from src import llm
    return llm


def MODEL_KEYS() -> list[str]:
    return [f"{name}_model" for name in _llm().ORDER]


def get_llm(account: dict | None = None, show_keys: bool = False, show_usage: bool = False) -> dict:
    """Every provider with its model, readiness and the last characters of the caller's own key.

    account=None describes the site-wide settings. With an account's settings ({"keys", "cfg"}) it describes what that
    account's requests use: its own keys and choices first, the site's wherever it has set nothing."""
    llm = _llm()
    own_cfg = (account or {}).get("cfg") or {}
    site_only = account is None
    with llm.scoped(account):
        cfg = llm.effective()
        avail, where = llm.describe(cfg), llm.privacy(cfg)
        mine = cfg if site_only else own_cfg        # the values this scope itself holds (and so can edit)
        inherited = {} if site_only else llm.site_cfg()
        rows, used = [], llm.usage() if show_usage else {}
        for name in llm.ORDER:
            row = {"name": name, "label": llm.LABELS[name], "available": bool(avail[name]["available"]),
                   "detail": avail[name]["detail"], "privacy": where.get(name, ""), "model": str(mine.get(f"{name}_model") or ""),
                   "default_model": str(inherited.get(f"{name}_model") or ""), "takes_key": name in llm.KEY_ENV,
                   "key_env": llm.KEY_ENV.get(name, ""), "has_key": False, "key_source": "", "key_hint": "", "keys_url": "",
                   "base_url": "", "editable_url": False, "key_optional": False, "usage": used.get(name) or None}
            if name in llm.KEY_ENV:
                key, source = llm.api_key(name)
                own = source == ("saved" if site_only else "account")     # only your own key gets a hint
                row.update(has_key=bool(key), key_source=source, key_hint=key[-4:] if show_keys and own and len(key) >= 12 else "")
            if name in llm.OPENAI_COMPAT:
                row.update(base_url=llm.endpoint(name, cfg)["base_url"], keys_url=llm.OPENAI_COMPAT[name]["keys_url"],
                           editable_url=name == "custom", key_optional=name == "custom",
                           default_model=row["default_model"] or llm.OPENAI_COMPAT[name]["model"])
                if name == "custom":
                    row.update(base_url=str(mine.get("custom_base_url") or ""), default_base_url=str(inherited.get("custom_base_url") or ""))
            elif name == "ollama":
                row.update(default_model=row["default_model"] or llm.DEFAULT_OLLAMA_MODEL, base_url=llm.OLLAMA_HOST)
            rows.append(row)
        pinned = (cfg.get("provider") or "auto").strip().lower()
        return {"provider": pinned, "own_provider": str(mine.get("provider") or ""),
                "site_provider": (inherited.get("provider") or "auto") if not site_only else "",
                "active": llm.active_provider(cfg, {n: bool(avail[n]["available"]) for n in llm.ORDER}),   # as llm.generate() chooses
                "providers": rows, "options": llm.options(cfg),
                "option_limits": {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi) in llm.OPTION_LIMITS.items()}}


def update_llm(payload, account: dict | None = None, allow_private_urls: bool = True) -> dict | None:
    """{provider?, options: {temperature?, max_tokens?, timeout?, fallback?}, providers: {name: {api_key?, model?,
    base_url?}}}. An empty api_key forgets the saved key; an empty model, base URL or provider goes back to the default.

    account=None writes the site-wide settings (profile.yaml + llm_keys.json). Otherwise the account's own settings
    dict is changed and returned for the caller to store; an account that leaves something empty inherits the site's."""
    llm = _llm()
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    site_only = account is None
    prof = _load_yaml() if site_only else {}
    cl = (prof.get("cover_letter") or {}) if site_only else dict((account or {}).get("cfg") or {})
    own_keys = {} if site_only else dict((account or {}).get("keys") or {})

    def put(key, value):          # an account stores only what it chose; the site keeps explicit values
        if value in ("", None) and not site_only:
            cl.pop(key, None)
        else:
            cl[key] = value

    if "provider" in payload:
        want = payload["provider"] or ""
        if want == "" and not site_only:
            cl.pop("provider", None)
        elif want not in llm.PROVIDERS:
            raise ValueError("unknown provider")
        else:
            cl["provider"] = want
    if "options" in payload:
        opts = payload["options"]
        if not isinstance(opts, dict):
            raise ValueError("options must be an object")
        for key, (default, lo, hi) in llm.OPTION_LIMITS.items():
            if key in opts:
                try:
                    v = type(default)(opts[key])
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be a number") from None
                if not lo <= v <= hi:
                    raise ValueError(f"{key} must be between {lo} and {hi}")
                cl[key] = v
        if "fallback" in opts:
            cl["fallback"] = bool(opts["fallback"])
    rows = payload.get("providers") or {}
    if not isinstance(rows, dict):
        raise ValueError("providers must be an object")
    keys = []
    for name, row in rows.items():
        if name not in llm.ORDER or not isinstance(row, dict):
            raise ValueError(f"unknown provider: {name}")
        if "model" in row:
            put(f"{name}_model", str(row["model"] or "").strip()[:120])
        if "base_url" in row:
            if name != "custom":
                raise ValueError("only the custom endpoint has an editable base URL")
            url = llm.clean_base_url(str(row["base_url"] or ""))
            if url and not allow_private_urls and not _public_url(url):
                raise ValueError("that address is private or unreachable: only an admin can point the custom endpoint at a local network")
            put("custom_base_url", url)
        if "api_key" in row:
            if name not in llm.KEY_ENV:
                raise ValueError(f"{llm.LABELS[name]} does not take an API key")
            key = str(row["api_key"] or "").strip()
            if len(key) > 400 or any(c.isspace() for c in key):
                raise ValueError("that does not look like an API key")
            keys.append((name, key))
    if site_only:
        prof["cover_letter"] = cl
        _save_yaml(prof)
        for name, key in keys:
            llm.set_key(name, key)
        return None
    for name, key in keys:
        if key:
            own_keys[name] = key
        else:
            own_keys.pop(name, None)
    return {"keys": own_keys, "cfg": cl}


def _public_url(url: str) -> bool:
    from src import job_import
    return job_import._public_url(url)
