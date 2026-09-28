"""Helpers for tests that need the scanner tables (jobs, app_status, source_runs) in the test 'jobhunt' database."""
import sys
from datetime import date, timedelta
from pathlib import Path

from django.db import connections
from django.test import TestCase

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _migrate(raw) -> None:
    """Apply the same in-place column additions the scanner does at startup (src.db._MIGRATIONS)."""
    from src import db
    for table, cols in db._MIGRATIONS.items():
        have = {r[1] for r in raw.execute(f"PRAGMA table_info({table})")}
        for name, ddl in cols.items():
            if name not in have:
                raw.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _schema() -> str:
    from src import db
    return db._SCHEMA


class ScannerDBTestCase(TestCase):
    """TestCase whose 'jobhunt' alias has the real scanner schema (the models are unmanaged)."""
    databases = {"default", "jobhunt"}

    @classmethod
    def setUpClass(cls):
        conn = connections["jobhunt"]
        conn.ensure_connection()
        raw = conn.connection
        if not raw.execute("SELECT name FROM sqlite_master WHERE name='jobs'").fetchone():
            raw.executescript(_schema())
            _migrate(raw)
            raw.commit()
        super().setUpClass()

    def make_job(self, job_id, **kw):
        from jobs.models import Job
        today = date.today()
        base = dict(job_id=job_id, source="jobstt", title="Role", company="Acme", location="Port of Spain, Trinidad & Tobago",
                    remote=False, salary="", url="https://x.tt/" + job_id, description="", posted_at=today.isoformat(),
                    fit_score=40, tier="", why="", flags="", alt_urls="", seen_on="", first_seen=today.isoformat(),
                    updated_at="now", expires_at=(today + timedelta(days=10)).isoformat(), last_seen=today.isoformat(),
                    region="Port of Spain", category="Other")
        base.update(kw)
        return Job.objects.using("jobhunt").create(**base)
