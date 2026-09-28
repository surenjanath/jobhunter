#!/usr/bin/env python3
"""
live_check.py — hit every real endpoint and prove the pipeline works.

No mocks, no fixtures. This calls the live APIs, runs the production parsers
over whatever comes back, and asserts the results are actually usable. Run it
first, and run it again any time a source looks wrong.

    python live_check.py                # all sources
    python live_check.py --source hn    # just one
    python live_check.py --save         # dump raw payloads to output/raw/

Exit code is 0 only if every enabled source returned usable rows.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import score as scoring  # noqa: E402
from src import sources  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("live")

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
)

results: dict[str, dict] = {}


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n  {text}\n{'=' * 76}")


def verdict(ok: bool, msg: str, warn: bool = False) -> None:
    colour = YELLOW if warn else (GREEN if ok else RED)
    tag = "WARN" if warn else ("OK  " if ok else "FAIL")
    print(f"  {colour}[{tag}]{RESET} {msg}")


def load_cfg() -> dict:
    with open(ROOT / "config" / "profile.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def audit(name: str, rows: list[dict], save: bool = False) -> bool:
    """Check a source's real output for the things that actually break."""
    print(f"\n{DIM}--- {name} {'-' * (68 - len(name))}{RESET}")

    if not rows:
        verdict(False, f"{name} returned 0 rows")
        results[name] = {"rows": 0, "ok": False}
        return False

    verdict(True, f"{len(rows)} postings returned")

    problems = []

    no_url = [r for r in rows if not (r.get("url") or "").startswith("http")]
    if no_url:
        problems.append(f"{len(no_url)} rows with no usable URL")

    no_title = [r for r in rows if not (r.get("title") or "").strip()]
    if no_title:
        problems.append(f"{len(no_title)} rows with no title")

    # An empty description means the job can only be scored on its title,
    # which is how the original Greenhouse bug hid for so long.
    thin = [r for r in rows if len(r.get("description") or "") < 120]
    if thin:
        pct = round(len(thin) / len(rows) * 100)
        if pct > 50:
            problems.append(f"{pct}% of descriptions under 120 chars")
        else:
            verdict(True, f"{pct}% thin descriptions (acceptable)", warn=pct > 20)

    leftover = [r for r in rows if "<" in (r.get("description") or "")[:2000]]
    if leftover:
        problems.append(f"{len(leftover)} rows still contain raw HTML tags")

    dated = [r for r in rows if r.get("posted_at")]
    if not dated:
        problems.append("no row carries a posted_at date")
    else:
        bad = [r["posted_at"] for r in dated if not r["posted_at"][:4].isdigit()]
        if bad:
            problems.append(f"unparsed dates: {bad[:3]}")
        else:
            years = sorted({r["posted_at"][:4] for r in dated})
            recent = [
                r for r in dated
                if r["posted_at"] >= (date.today() - timedelta(days=90)).isoformat()
            ]
            verdict(
                True,
                f"dates parse; years={years}; {len(recent)}/{len(dated)} within 90 days",
                warn=not recent,
            )
            if not recent:
                problems.append("NO postings from the last 90 days - stale source?")

    ids = [r.get("job_id") for r in rows]
    if len(set(ids)) != len(ids):
        problems.append(f"duplicate job_ids within source ({len(ids) - len(set(ids))})")

    sample = rows[0]
    print(f"  {DIM}sample: {sample.get('title','')[:52]}")
    print(f"          {sample.get('company','')} | {sample.get('location','')[:32]}")
    print(f"          {sample.get('url','')[:70]}")
    print(f"          desc {len(sample.get('description') or '')} chars, "
          f"posted {sample.get('posted_at') or 'unknown'}{RESET}")

    for p in problems:
        verdict(False, p)

    if save:
        outdir = ROOT / "output" / "raw"
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"{name.replace(':', '_')}.json"
        path.write_text(json.dumps(rows, indent=2)[:2_000_000], encoding="utf-8")
        print(f"  {DIM}saved -> {path.relative_to(ROOT)}{RESET}")

    ok = not problems
    results[name] = {"rows": len(rows), "ok": ok, "problems": problems}
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="test only one source")
    ap.add_argument("--save", action="store_true", help="write raw parsed rows to output/raw/")
    args = ap.parse_args()

    cfg = load_cfg()
    boards = cfg.get("company_boards", {})
    terms = cfg.get("search_terms", [])[:4]  # keep the live run quick

    banner("LIVE ENDPOINT CHECK — real APIs, real parsers, no mocks")
    print(f"  {datetime.now(timezone.utc).isoformat(timespec='seconds')}")

    plan = {
        "remotive": lambda: sources.fetch_remotive(terms),
        "remoteok": sources.fetch_remoteok,
        "arbeitnow": sources.fetch_arbeitnow,
        "himalayas": sources.fetch_himalayas,
        "hn_whoishiring": sources.fetch_hn_whoishiring,
        **{k: v for k, v in __import__("src.sources_extra", fromlist=["EXTRA_SOURCES"]).EXTRA_SOURCES.items()},
        "greenhouse": lambda: sources.fetch_greenhouse(
            boards.get("greenhouse", [])[:3], cfg.get("targets", {}), 5
        ),
        "lever": lambda: sources.fetch_lever(boards.get("lever", [])[:3]),
        "ashby": lambda: sources.fetch_ashby(boards.get("ashby", [])[:3]),
    }

    # Trinidad & Tobago boards: tt:<name> for each built-in board and custom site.
    from src import trinidad as tt
    for tsrc in tt.TT_SOURCES.values():
        plan[f"tt:{tsrc.name}"] = lambda t=tsrc: t.fn(15)
    for site in tt.custom_sites(cfg):
        plan[f"tt:{site['name']}"] = lambda st=site: tt.fetch_custom_site(st, 15)
    MAY_BE_EMPTY = {"tt:findworktt", "tt:digicel", "jooble"}  # legitimately have no real postings at times

    if args.source:
        if args.source == "tt":
            plan = {k: v for k, v in plan.items() if k.startswith("tt:")}
        elif args.source not in plan:
            print(f"Unknown source. Options: tt, {', '.join(plan)}")
            return 2
        else:
            plan = {args.source: plan[args.source]}

    all_rows: list[dict] = []
    for name, fn in plan.items():
        try:
            rows = fn()
        except Exception as exc:  # noqa: BLE001
            verdict(False, f"{name} raised: {exc!r}")
            results[name] = {"rows": 0, "ok": False, "problems": [repr(exc)]}
            continue
        if name in MAY_BE_EMPTY and not rows:
            verdict(True, f"{name}: no real postings right now (allowed)", warn=True)
            results[name] = {"rows": 0, "ok": True, "problems": [], "allowed_empty": True}
            continue
        audit(name, rows, save=args.save)
        if name.startswith("tt:") and rows:
            no_region = [r for r in rows if not r.get("region")]
            unknown_co = [r for r in rows if r.get("company") in ("", "Unknown")]
            if no_region:
                results[name]["ok"] = False
                results[name].setdefault("problems", []).append(f"{len(no_region)} rows missing region")
                verdict(False, f"{len(no_region)} rows missing region")
            if unknown_co and len(unknown_co) > len(rows) / 2:
                verdict(True, f"{len(unknown_co)}/{len(rows)} rows have no company name", warn=True)
        all_rows.extend(rows)

    # ---- pipeline over genuinely live data -------------------------------
    banner("PIPELINE OVER LIVE DATA")
    if not all_rows:
        verdict(False, "nothing fetched, cannot exercise the pipeline")
        return 1

    ranked = scoring.rank(all_rows, cfg)
    verdict(True, f"{len(all_rows)} fetched -> {len(scoring.dedupe(all_rows))} deduped -> {len(ranked)} above threshold")

    if ranked:
        scores = [r["fit_score"] for r in ranked]
        verdict(
            len(set(scores)) > 3,
            f"score spread {min(scores)}-{max(scores)} across {len(set(scores))} distinct values",
            warn=len(set(scores)) <= 3,
        )
        flagged = [r for r in ranked if r.get("flags")]
        verdict(True, f"{len(flagged)}/{len(ranked)} carry at least one flag")

        print(f"\n  {DIM}Top live matches:{RESET}")
        for r in ranked[:12]:
            print(f"    [{r['fit_score']:>3}] {r['title'][:46]:<46} {r['company'][:22]}")
            print(f"          {DIM}{r['url'][:88]}{RESET}")

        # Prove a real letter can be produced from a real posting.
        from src import cover_letter
        text = cover_letter.generate_with_template(ranked[0], cover_letter.load_profile())
        body = text.split("---")[0]
        banned = [w for w in ("passionate", "thrilled", "rockstar", "world-class")
                  if w in body.lower()]
        verdict(not banned and len(body.split()) < 300,
                f"cover letter for '{ranked[0]['title'][:36]}': "
                f"{len(body.split())} words, banned={banned or 'none'}")

    # ---- summary ---------------------------------------------------------
    banner("SUMMARY")
    good = [n for n, r in results.items() if r["ok"] and (r["rows"] or r.get("allowed_empty"))]
    empty = [n for n, r in results.items() if not r["rows"] and not r.get("allowed_empty")]
    broken = [n for n, r in results.items() if r["rows"] and not r["ok"]]

    for n in good:
        verdict(True, f"{n}: {results[n]['rows']} rows, clean")
    for n in broken:
        verdict(False, f"{n}: {results[n]['rows']} rows but {'; '.join(results[n]['problems'])}")
    for n in empty:
        verdict(False, f"{n}: returned nothing")

    print(f"\n  {len(good)}/{len(results)} sources healthy, {len(ranked)} scored jobs\n")

    if empty or broken:
        print(f"  {YELLOW}A dead source is usually one of three things:{RESET}")
        print("    1. The board changed a field name  -> fix the parser in src/sources.py")
        print("    2. The board is rate-limiting you  -> wait and re-run")
        print("    3. An ATS token is stale           -> fix it in config/profile.yaml")
        print("  Re-run with --save to inspect exactly what came back.\n")

    return 0 if not (empty or broken) else 1


if __name__ == "__main__":
    sys.exit(main())
