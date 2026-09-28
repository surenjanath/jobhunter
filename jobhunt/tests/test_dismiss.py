"""
test_dismiss.py — the "dismiss with reason" feature at the db layer: db.update_status stores a reason when you pass
on a role, and clears it automatically if the role is later re-opened (moved off "Passed on it").
Called from test_pipeline.main(); runnable alone via test_pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(check, cfg):
    print("\n11. DISMISS WITH REASON")
    from src import db

    jid = "dismiss-test-job"

    def row():
        c = db._conn()
        r = c.execute("SELECT status, dismiss_reason, notes FROM app_status WHERE job_id=?", (jid,)).fetchone()
        c.close()
        return dict(r) if r else None

    db.update_status(jid, status="Passed on it", dismiss_reason="Pay too low")
    r = row()
    check("dismiss reason is stored alongside the status", (r["status"], r["dismiss_reason"]) == ("Passed on it", "Pay too low"), str(r))

    db.update_status(jid, status="Shortlisted")
    r = row()
    check("re-opening the role clears the stale reason", (r["status"], r["dismiss_reason"]) == ("Shortlisted", ""), str(r))

    db.update_status(jid, status="Passed on it", dismiss_reason="Wrong seniority")
    db.update_status(jid, notes="reconsidering")  # a save that doesn't touch status must not disturb the reason
    r = row()
    check("a status-less update leaves the reason alone", (r["status"], r["dismiss_reason"]) == ("Passed on it", "Wrong seniority"), str(r))

    c = db._conn()
    c.execute("DELETE FROM app_status WHERE job_id=?", (jid,))
    c.commit()
    c.close()
