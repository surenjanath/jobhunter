import sys
from pathlib import Path

from django.apps import AppConfig


class JobsConfig(AppConfig):
    name = 'jobs'

    def ready(self):
        """Upgrade the scanner database in place (new columns/tables) so the models above always match it."""
        if "test" in sys.argv:
            return
        try:
            root = Path(__file__).resolve().parent.parent.parent / "jobhunt"
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from src import db  # noqa: F401  (importing creates tables + runs migrations)
        except Exception:  # never block Django startup on the scanner db
            pass
