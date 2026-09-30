"""
manage.py boot_hosted — make a hosted copy (Render etc.) usable from a blank disk, on every start.

On a host without a persistent disk (Render's free plan) every restart begins empty, so this rebuilds what matters:

1. your account, from JOBHUNTER_OWNER_EMAIL + JOBHUNTER_OWNER_PASSWORD (created, or its password kept in sync);
2. your private config, from Secret Files (never the public repo), in JOBHUNTER_SECRETS_DIR (default /etc/secrets):
     profile.yaml            -> jobhunt/config/profile.yaml   (search terms, targets, preferences)
     resume.md|.txt|.pdf|.docx -> your resume, for the owner account and the shared profile
3. a first job scan in the background when the jobs database is empty (the site is usable while it runs).

Safe to run repeatedly. Prints what it did; never prints secrets.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

ROOT = Path(__file__).resolve().parents[4] / "jobhunt"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class Command(BaseCommand):
    help = "Bootstrap a hosted copy: owner account, secret-file config and resume, first scan."

    def add_arguments(self, parser):
        parser.add_argument("--no-scan", action="store_true", help="don't start the first scan")

    def handle(self, *args, **opts):
        owner = self._owner()
        secrets = Path(os.environ.get("JOBHUNTER_SECRETS_DIR", "/etc/secrets"))
        self._config(secrets)
        self._resume(secrets, owner)
        if not opts["no_scan"] and os.environ.get("JOBHUNTER_BOOT_SCAN", "1") != "0":
            self._first_scan()

    def _owner(self):
        from django.contrib.auth.models import User
        email = os.environ.get("JOBHUNTER_OWNER_EMAIL", "").strip().lower()
        pw = os.environ.get("JOBHUNTER_OWNER_PASSWORD", "")
        if not email or not pw:
            self.stdout.write("owner: JOBHUNTER_OWNER_EMAIL / JOBHUNTER_OWNER_PASSWORD not set, skipped")
            return None
        if len(pw) < 12:
            self.stderr.write("owner: JOBHUNTER_OWNER_PASSWORD must be at least 12 characters; not created")
            return None
        u, created = User.objects.get_or_create(username=email, defaults={"email": email})
        if created or not u.check_password(pw) or not u.is_staff:
            u.set_password(pw)
            u.email = email
            u.is_staff = True          # the owner can change site access from the Settings page
            u.save()
        self.stdout.write(f"owner: {'created' if created else 'ready'} ({email})")
        return u

    def _config(self, secrets: Path):
        src = secrets / "profile.yaml"
        dst = ROOT / "config" / "profile.yaml"
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            self.stdout.write("config: profile.yaml loaded from secret files")
        else:
            from src import localfiles
            localfiles.ensure()
            self.stdout.write("config: no profile.yaml secret file; using the example config")

    def _resume(self, secrets: Path, owner):
        from src import profile_store
        found = next((p for ext in ("md", "txt", "pdf", "docx") for p in [secrets / f"resume.{ext}"] if p.is_file()), None)
        if not found:
            self.stdout.write("resume: no resume.* secret file; upload one on the Profile page")
            return
        if not profile_store.active_profile():
            profile_store.import_resume(found.read_bytes(), found.name, source="secret-file", embed=False)
            self.stdout.write(f"resume: {found.name} imported")
        if owner is not None:
            from accounts.models import UserProfile
            from accounts.views import _migrate_anonymous_profile
            if not UserProfile.objects.filter(user=owner).exclude(data={}).exists():
                _migrate_anonymous_profile(owner)
                self.stdout.write("resume: attached to the owner account")

    def _first_scan(self):
        from src import db
        try:
            c = db._conn()
            n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            c.close()
        except Exception:  # noqa: BLE001  (no table yet: the scan creates it)
            n = 0
        if n:
            self.stdout.write(f"scan: {n} jobs already stored, skipped")
            return
        log = ROOT / "output" / "boot_scan.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([sys.executable, "-m", "src.run", "--dry-run"], cwd=ROOT, stdout=open(log, "w"), stderr=subprocess.STDOUT,
                         start_new_session=True)
        self.stdout.write("scan: first scan started in the background (jobhunt/output/boot_scan.log)")
