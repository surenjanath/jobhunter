"""
config.py — centralized, typed configuration.
Single source of truth for all settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "port": 5111,
    "host": "127.0.0.1",
    "db_path": str(ROOT / "output" / "jobhunt.db"),
    "max_greenhouse_details": 12,
    "max_age_days": 30,
    "min_score": 35,
    "parallel": True,
}

def load_profile() -> dict:
    p = ROOT / "config" / "profile.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}

def get(key: str, default: Any = None) -> Any:
    # Env overrides: JOBHUNT_PORT, JOBHUNT_DB, etc.
    env_key = f"JOBHUNT_{key.upper()}"
    if env_key in os.environ:
        v = os.environ[env_key]
        # try int
        try:
            return int(v)
        except ValueError:
            if v.lower() in ("true","false"):
                return v.lower() == "true"
            return v
    return DEFAULTS.get(key, default)

def is_trinidad_enabled(profile: dict | None = None) -> bool:
    prof = profile or load_profile()
    return bool(prof.get("sources", {}).get("trinidad", True))
