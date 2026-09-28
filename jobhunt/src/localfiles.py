"""
localfiles.py — first-run setup: personal config lives in git-ignored files created from the *.example templates.

    config/profile.example.yaml       -> config/profile.yaml
    config/fact_bank.example.md       -> config/fact_bank.md
    config/form_answers.example.md    -> config/form_answers.md
    config/ui_settings.example.json   -> config/ui_settings.json

Nothing is ever overwritten. Imported by `src/__init__.py`, so any entry point (scan, Django, tests) triggers it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config"
PAIRS = {
    "profile.example.yaml": "profile.yaml",
    "fact_bank.example.md": "fact_bank.md",
    "form_answers.example.md": "form_answers.md",
    "ui_settings.example.json": "ui_settings.json",
}


def ensure() -> list[str]:
    """Create any missing local config file from its template. Returns the names created."""
    made = []
    for example, real in PAIRS.items():
        src, dst = CONFIG / example, CONFIG / real
        if src.exists() and not dst.exists():
            try:
                shutil.copyfile(src, dst)
                made.append(real)
            except OSError:  # read-only checkout: callers fall back to defaults
                pass
    return made
