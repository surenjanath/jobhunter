#!/usr/bin/env python3
"""
check_llm.py — confirm the cover-letter engine works, end to end.

Run this after `claude /login`. It probes every backend, generates a real
letter through the configured one, and audits the output against the tone and
honesty rules in the fact bank.

    python check_llm.py                 # use the configured provider
    python check_llm.py --provider ollama
    python check_llm.py --keep          # save the letter to output/
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import cover_letter as cl  # noqa: E402
from src import llm  # noqa: E402

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

BANNED = [
    "passionate", "thrilled", "excited to", "rockstar", "ninja", "10x",
    "obsessed", "world-class", "elite", "exceptional", "unparalleled",
    "cutting-edge", "synergy", "perfect fit", "look forward to hearing",
]

# A realistic posting that deliberately touches a known gap (evals), so we can
# check the letter acknowledges it instead of bluffing.
SAMPLE = {
    "job_id": "check:1",
    "title": "Forward Deployed Engineer",
    "company": "Sierra",
    "location": "Remote - Americas",
    "salary": "$180,000 - $240,000",
    "url": "https://jobs.ashbyhq.com/sierra/example",
    "fit_score": 78,
    "flags": "Hires internationally via EOR (good) | Wants LLM evals - your known gap",
    "description": (
        "We deploy conversational AI agents into large insurance and financial "
        "services customers. You will work directly with those customers, write "
        "production Python, build RAG and multi-agent orchestration, design evals "
        "and observability for agent behaviour, and own delivery end to end. "
        "5+ years engineering experience. We hire internationally through an "
        "employer of record and support US Eastern overlap."
    ),
}


def verdict(ok: bool, msg: str, warn: bool = False) -> bool:
    colour = YELLOW if warn else (GREEN if ok else RED)
    tag = "WARN" if warn else ("OK  " if ok else "FAIL")
    print(f"  {colour}[{tag}]{RESET} {msg}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", help="override the configured provider")
    ap.add_argument("--keep", action="store_true", help="save the letter to output/")
    args = ap.parse_args()

    print("=" * 72)
    print("  COVER LETTER ENGINE CHECK")
    print("=" * 72)

    print("\n1. BACKEND AVAILABILITY")
    avail = llm.describe()
    for name, info in avail.items():
        verdict(info["available"], f"{name:<12} {info['detail']}",
                warn=not info["available"] and name != "template")

    profile = cl.load_profile()
    cfg = dict(profile.get("cover_letter") or {})
    if args.provider:
        cfg["provider"] = args.provider
    provider = cfg.get("provider", "auto")
    print(f"\n  configured provider: {provider}")

    if provider == "claude_code" and not avail["claude_code"]["available"]:
        print(f"\n  {RED}Claude Code is the configured provider but isn't ready.{RESET}")
        print(f"  {avail['claude_code']['detail']}")
        print("\n  Fix: run `claude` in a terminal, then `/login`. Then re-run this.\n")
        return 1

    print("\n2. GENERATING A REAL LETTER")
    print(f"  {DIM}posting: {SAMPLE['title']} at {SAMPLE['company']}{RESET}")
    print(f"  {DIM}this can take 20-60s...{RESET}")

    if provider in ("template", "none"):
        text, backend = cl.generate_with_template(SAMPLE, profile), "template"
        verdict(True, "generated via template (no LLM, by configuration)")
    else:
        text, backend = cl.generate_with_llm(SAMPLE, cl.load_fact_bank(), cfg)
        if text is None:
            print(f"\n  {RED}No LLM produced a letter.{RESET}\n  Reason: {backend}")
            print(f"  {DIM}Falling back to the template so you can still see output.{RESET}\n")
            text, backend = cl.generate_with_template(SAMPLE, profile), "template"
        else:
            verdict(True, f"generated via {backend}")

    print("\n" + "-" * 72)
    print(text)
    print("-" * 72)

    print("\n3. AUDITING THE OUTPUT")
    body = text.split("---")[0]
    words = len(body.split())
    ok = True

    hits = [w for w in BANNED if w in body.lower()]
    ok &= verdict(not hits, f"no hype language {DIM}{hits or ''}{RESET}")
    ok &= verdict(words < 320, f"length {words} words (target under 300)",
                  warn=280 <= words < 320)
    ok &= verdict("—" not in body, "no em dashes")

    over = re.search(r"(?<!not yet )in production", body)
    ok &= verdict(over is None,
                  "does not claim the claims system is in production"
                  + (f" {DIM}(found: {over.group(0)}){RESET}" if over else ""))

    grounded = any(
        s in body for s in ("claims adjudication", "rules engine", "insurance",
                            "29,000", "TT$1.5M", "Django", "nginx")
    )
    ok &= verdict(grounded, "grounded in real fact-bank evidence")

    invented = [
        n for n in ("Kubernetes", "dbt", "Airflow", "Snowflake", "React",
                    "TypeScript", "PyTorch", "Terraform")
        if re.search(rf"\b{n}\b", body, re.I)
    ]
    ok &= verdict(not invented,
                  f"claims no tech he doesn't have {DIM}{invented or ''}{RESET}")

    read_it = any(
        s in body.lower() for s in ("sierra", "agent", "customer", "insurance", "eval")
    )
    ok &= verdict(read_it, "references something specific from the posting")

    honest = any(
        s in body.lower()
        for s in ("eval", "haven't", "have not", "honest", "picking that up",
                  "would be learning", "gap")
    )
    verdict(honest, "acknowledges the evals gap honestly", warn=not honest)

    if args.keep:
        path = cl.write_letter(SAMPLE, text, backend)
        print(f"\n  saved to {path.relative_to(ROOT)}")

    print("\n" + "=" * 72)
    if ok:
        print(f"  {GREEN}Engine works. Letters are grounded and on-tone.{RESET}")
    else:
        print(f"  {RED}Letter generated but failed one or more checks above.{RESET}")
        print("  Tighten the rules in config/fact_bank.md, or try a stronger model.")
    print("=" * 72 + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
