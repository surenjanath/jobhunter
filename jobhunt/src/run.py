"""
run.py — the daily entrypoint.

    fetch  ->  dedupe  ->  score  ->  filter  ->  Google Sheet + local JSON/CSV

Run locally:
    python -m src.run                 # full run, syncs to the sheet
    python -m src.run --dry-run       # fetch and score only, no sheet write
    python -m src.run --limit 40      # cap output while testing

Environment:
    SHEET_ID                        required unless --dry-run
    GOOGLE_SERVICE_ACCOUNT_JSON     service account key as raw JSON (CI)
    GOOGLE_APPLICATION_CREDENTIALS  or a path to the key file (local)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import score as scoring  # noqa: E402
from src import sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jobhunt")


def load_config() -> dict:
    with open(ROOT / "config" / "profile.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def save_local(jobs: list[dict]) -> None:
    OUTPUT.mkdir(exist_ok=True)

    with open(OUTPUT / "jobs_latest.json", "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2, ensure_ascii=False)

    cols = [
        "fit_score", "tier", "title", "company", "location",
        "salary", "source", "posted_at", "url", "why", "flags", "job_id",
    ]
    with open(OUTPUT / "jobs_latest.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(jobs)

    log.info("Wrote output/jobs_latest.json and .csv")


def print_summary(jobs: list[dict], limit: int = 15) -> None:
    if not jobs:
        log.info("Nothing cleared the score threshold today.")
        return

    tier1 = [j for j in jobs if j["fit_score"] >= 65]
    tier2 = [j for j in jobs if 50 <= j["fit_score"] < 65]

    print("\n" + "=" * 78)
    print(f"  {len(jobs)} jobs kept   |   {len(tier1)} tier-1   |   {len(tier2)} tier-2")
    print("=" * 78)
    for j in jobs[:limit]:
        print(f"\n  [{j['fit_score']:>3}] {j['title']}")
        print(f"        {j['company']}  ·  {j.get('location') or 'n/a'}  ·  {j['source']}")
        if j.get("salary"):
            print(f"        {j['salary']}")
        print(f"        {j['url']}")
        if j.get("flags"):
            print(f"        ! {j['flags']}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="skip the Google Sheet write")
    ap.add_argument("--limit", type=int, default=0, help="cap the number of jobs kept")
    ap.add_argument("--tab", default="Jobs")
    ap.add_argument("--digest", action="store_true", help="print what is new and worth your time when the scan finishes")
    ap.add_argument("--rescore", action="store_true", help="re-score stored jobs with the current profile (no network)")
    args = ap.parse_args()

    if args.rescore:
        from src import db as _db
        cfg = load_config()
        n = _db.rescore_all(lambda j: scoring.score_job(j, cfg))
        log.info("Re-scored %d stored jobs", n)
        from src import snapshot
        snapshot.record()
        return 0

    started = datetime.now()
    cfg = load_config()
    try:  # first run: adopt docs/ resume so profile-driven scoring works out of the box
        from src import profile_store
        if profile_store.bootstrap_if_empty():
            log.info("Imported docs/ resume as the starting profile (upload yours in the Profile tab)")
    except Exception as exc:  # noqa: BLE001
        log.warning("profile bootstrap skipped: %s", exc)

    raw = sources.fetch_all(cfg)
    if not raw:
        log.error(
            "No postings came back from any source. Check your network, and note "
            "that some boards rate-limit. Re-run in a few minutes."
        )
        return 1

    jobs = scoring.rank(raw, cfg)
    if args.limit:
        jobs = jobs[: args.limit]

    log.info("Kept %d jobs after dedupe, scoring and filtering", len(jobs))
    save_local(jobs)
    # also persist to SQLite backend (actual backend)
    try:
        from src import db as _db
        _db.upsert_jobs(jobs)
        log.info("Persisted %d jobs to SQLite (%s)", len(jobs), _db.DB_PATH)
        from src import trinidad as _tt
        if _tt.HEALTH:
            _db.record_source_runs(list(_tt.HEALTH.values()))
            ok_sources = [n for n, h in _tt.HEALTH.items() if h.get("ok") and h.get("count")]
            legacy = _db.purge_legacy_trinidad(ok_sources)
            if legacy:
                log.info("Removed %d legacy Trinidad rows from earlier fetcher versions", legacy)
        try:
            from src import snapshot
            snapshot.record()
        except Exception as exc:  # noqa: BLE001
            log.warning("snapshot failed: %s", exc)
        gone = _db.purge_expired()
        if gone:
            log.info("Removed %d expired postings", gone)
    except Exception as exc:  # noqa: BLE001
        log.warning("DB persist failed: %s", exc)
    print_summary(jobs)

    if args.dry_run:
        log.info("Dry run: nothing written to Google Sheets.")
    else:
        sheet_id = os.environ.get("SHEET_ID")
        if not sheet_id:
            log.error("SHEET_ID not set. Export it, or use --dry-run.")
            return 1
        from src import sheets  # imported late so --dry-run needs no gspread

        result = sheets.sync(jobs, sheet_id, tab=args.tab)
        log.info(
            "Sheet synced: %d new, %d refreshed, %d total",
            result["new"], result["updated"], result["total"],
        )

    if args.digest:
        try:
            from src import digest as _dg
            print(_dg.to_markdown(_dg.build(days=1)))
        except Exception as exc:  # noqa: BLE001
            log.warning("digest failed: %s", exc)

    log.info("Done in %.1fs", (datetime.now() - started).total_seconds())
    return 0


if __name__ == "__main__":
    sys.exit(main())
