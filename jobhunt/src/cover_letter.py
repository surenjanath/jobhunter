"""
cover_letter.py — draft a tailored cover letter for one job.

Two modes:
  * Claude API (set ANTHROPIC_API_KEY) — tailored, reads the posting properly.
  * Template fallback (no key needed) — a solid skeleton with the right
    evidence blocks selected by keyword. Always works, costs nothing.

Everything is grounded in config/fact_bank.md. The system prompt forbids
inventing anything not in that file, and explicitly bans overselling.

Usage:
    python -m src.cover_letter --job-id remotive:12345
    python -m src.cover_letter --url https://... --title "..." --company "..."
    python -m src.cover_letter --interactive
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUTPUT = ROOT / "output"
CACHE = OUTPUT / "jobs_latest.json"

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
You are drafting a cover letter in the first person as {name}{background}.

You will be given (a) a fact bank and (b) a job posting. These are your only \
sources. Follow these rules absolutely:

GROUNDING
- Use only facts from the fact bank. Invent nothing: no metrics, no \
technologies, no experiences, no team sizes, no dates.
- If the job asks for something the candidate hasn't done, do not imply they \
have. Either name the closest real equivalent, or acknowledge the gap in one \
short clause.
- Respect status language exactly. Systems described as "in testing" or "in \
pilot" must never be described as live, shipped, deployed, or in production.

TONE (this matters more than anything else)
- Write the candidate as competent, specific, and grounded. The evidence \
should do the work. Do not make them sound like a genius.
- Banned: passionate, thrilled, excited to, rockstar, ninja, 10x, obsessed, \
world-class, elite, exceptional, unparalleled, cutting-edge, leverage (as a \
verb), synergy, "I was blown away", "perfect fit", "I'd love the opportunity".
- No opening line about how impressive the company is. Start with something \
concrete.
- Short declarative sentences. Plain words. Contractions are fine.
- Never use em dashes. Use commas, full stops, or restructure the sentence.

STRUCTURE
- Under 300 words. Three or four short paragraphs. No bullet lists.
- Para 1: the single most relevant thing they have built, stated concretely, \
and why it maps to this specific role. No preamble.
- Para 2: one more piece of evidence, ideally the one that is unusual for the \
role.
- Para 3: something specific about this company or posting, showing it was read.
- Para 4 (optional, one or two sentences): an honest note on something they'd \
be picking up in the role, if the posting clearly calls for a known gap. This \
builds credibility, so include it when there is an obvious gap.
- Sign off simply. No "I look forward to hearing from you at your earliest \
convenience."

OUTPUT
- Return only the letter body. No subject line, no address block, no commentary.
"""


# ---------------------------------------------------------------------------

def load_fact_bank() -> str:
    path = CONFIG / "fact_bank.md"
    if not path.exists():
        raise FileNotFoundError(f"Fact bank missing at {path}")
    return path.read_text(encoding="utf-8")


def load_profile() -> dict:
    with open(CONFIG / "profile.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_cached_jobs() -> list[dict]:
    if not CACHE.exists():
        return []
    with open(CACHE, encoding="utf-8") as fh:
        return json.load(fh)


def find_job(job_id: str) -> dict | None:
    for job in load_cached_jobs():
        if job.get("job_id") == job_id:
            return job
    return None


# ---------------------------------------------------------------------------
# Claude path
# ---------------------------------------------------------------------------

def build_prompt(job: dict) -> str:
    return f"""JOB POSTING
Title:    {job.get('title','')}
Company:  {job.get('company','')}
Location: {job.get('location','')}
Salary:   {job.get('salary','not disclosed')}
Link:     {job.get('url','')}

Description:
{(job.get('description') or '')[:9000]}
"""


def generate_with_llm(job: dict, fact_bank: str, cfg: dict | None = None):
    """
    Try the configured LLM backends. Returns (text, backend) or (None, reason).

    Backends are Claude Code CLI, local Ollama, and the Anthropic API. All get
    the same system prompt, so the fact-bank grounding and the tone rules apply
    no matter which one runs.
    """
    from src import llm

    prof = load_profile()
    cand = prof.get("candidate") or {}
    background = ""
    try:
        from src import profile_store
        p = profile_store.active_profile()
        if p and p.get("summary"):
            background = ", " + p["summary"][:240].rstrip(".")
    except Exception:  # noqa: BLE001
        pass
    system = SYSTEM_PROMPT.format(name=cand.get("name") or "the candidate", background=background)

    user = (
        f"<fact_bank>\n{fact_bank}\n</fact_bank>\n\n"
        f"<posting>\n{build_prompt(job)}\n</posting>\n\n"
        "Draft the cover letter."
    )
    try:
        text, backend = llm.generate(system, user, cfg)
        return text, backend
    except llm.LLMUnavailable as exc:
        log.info("no LLM backend available (%s); using template", exc)
        return None, str(exc)


# ---------------------------------------------------------------------------
# Template fallback (no LLM): assembled from the candidate's own material
# ---------------------------------------------------------------------------

_PAST = re.compile(r"^(?:built|developed|designed|led|ran|wrote|created|automated|deployed|delivered|engineered|recovered|owned|"
                   r"reduced|migrated|launched|implemented|managed|maintained|integrated|shipped|scaled|introduced|streamlined)\b", re.I)


def _first_person(text: str) -> str:
    """'Built X.' -> 'I built X.'; other text is left as a plain statement."""
    text = re.sub(r"\s+", " ", text).strip().rstrip(".") + "."
    if _PAST.match(text):
        return "I " + text[0].lower() + text[1:]
    return text


def candidate_material() -> tuple[list[str], set[str]]:
    """(evidence sentences, skills the candidate has). From the active resume when there is one, else the fact bank."""
    from src import skills_taxonomy as tax
    try:
        from src import profile_store
        p = profile_store.active_profile()
    except Exception:  # noqa: BLE001
        p = None
    if p:
        units = [b for r in p.get("roles", []) for b in r.get("bullets", [])] + [f"{x.get('name', '')}: {x.get('text', '')}" for x in p.get("projects", [])]
        return [u for u in units if len(u) > 30], set(p.get("skills", {}))
    try:
        fb = load_fact_bank()
    except FileNotFoundError:
        return [], set()
    built = fb.split("## Honest weaknesses")[0]                     # what they have done, not what they lack
    units = [re.sub(r"\*\*", "", m.group(1)).strip() for m in re.finditer(r"^- (.{40,400}?)(?=\n- |\n\n|\n#|\Z)", built, re.M | re.S)]
    return [re.sub(r"\s+", " ", u) for u in units], set(tax.find_skills(built))


def _pick_evidence(job: dict, units: list[str], n: int = 2) -> list[str]:
    """The n pieces of the candidate's material closest to what the posting asks for."""
    from src import retrieval
    if not units:
        return []
    blob = f"{job.get('title', '')} {job.get('description', '')}"
    idx = retrieval.BM25(units)
    scores = idx.score(blob)
    ranked = sorted(range(len(units)), key=lambda i: -scores[i])
    return [units[i] for i in ranked[:n]]


def _gap_note(job: dict, have: set[str]) -> str | None:
    """One honest sentence about the most important required skill the candidate lacks."""
    from src import matching
    from src import skills_taxonomy as tax
    if not have:
        return None
    a = matching.analyze_job(job)
    for name, meta in a["skills"].items():
        if meta["kind"] == "required" and name not in have and name not in tax.SOFT:
            rel = sorted(tax.related(name) & have)
            return (f"One honest note: I haven't used {name} in a role yet"
                    + (f", though I've worked with {rel[0]}, which is close" if rel else "")
                    + ". I'd be picking it up properly here.")
    return None


def generate_with_template(job: dict, profile: dict) -> str:
    company = job.get("company") or "your team"
    title = job.get("title") or "this role"
    cand = profile.get("candidate") or {}
    units, have = candidate_material()
    picks = _pick_evidence(job, units)

    paras = ["Hello,"]
    first = f"I'm applying for the {title} role at {company}."
    if picks:
        first += " " + _first_person(picks[0])
    paras.append(first)
    if len(picks) > 1:
        paras.append(_first_person(picks[1]))

    wa = (cand.get("work_authorization") or "").strip()
    says_where = bool(cand.get("location")) and cand["location"].split(",")[0].lower() in wa.lower()   # authorisation text already names the place
    where = " ".join(x for x in [
        (f"I'm based in {cand['location']}" + (f" on {cand['timezone']}" if cand.get("timezone") else "") + ".") if cand.get("location") and not says_where else
        (f"I'm on {cand['timezone']}." if cand.get("timezone") else ""),
        (cand.get("timezone_note") or "").rstrip(".") + "." if cand.get("timezone_note") else "",
        wa,
    ] if x)
    if where:
        paras.append(where)
    gap = _gap_note(job, have)
    if gap:
        paras.append(gap)
    sign = cand.get("name") or ""
    if cand.get("website"):
        sign += f"\n{cand['website']}"
    paras.append(f"Thanks for reading.\n\n{sign}".rstrip())

    body = re.sub(r"\s*[—–]\s*", ", ", "\n\n".join(paras))      # the letter rules forbid em dashes; source text may contain them
    body += (
        "\n\n---\n"
        "[TEMPLATE DRAFT — no LLM backend was reachable. Start Ollama, install the "
        "Claude Code CLI, or set ANTHROPIC_API_KEY for a tailored draft. Either way, "
        "edit the middle paragraphs to reference something specific from the posting "
        "before sending.]"
    )
    return body


# ---------------------------------------------------------------------------

def write_letter(job: dict, text: str, backend: str = "template") -> Path:
    OUTPUT.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{job.get('company','x')}-{job.get('title','role')}".lower())
    slug = slug.strip("-")[:70]
    path = OUTPUT / f"cover_{date.today().isoformat()}_{slug}.md"

    header = (
        f"# Cover letter — {job.get('title','')} at {job.get('company','')}\n\n"
        f"**Posting:** {job.get('url','')}  \n"
        f"**Fit score:** {job.get('fit_score','n/a')} ({job.get('tier','')})  \n"
        f"**Flags:** {job.get('flags','') or 'none'}  \n"
        f"**Drafted:** {date.today().isoformat()} via {backend}\n\n---\n\n"
    )
    path.write_text(header + text + "\n", encoding="utf-8")
    return path


def generate(job: dict) -> tuple[str, Path, str]:
    """Returns (text, path, backend_used)."""
    fact_bank = load_fact_bank()
    profile = load_profile()
    cfg = profile.get("cover_letter") or {}

    text, backend = generate_with_llm(job, fact_bank, cfg)
    if text is None:
        text = generate_with_template(job, profile)
        backend = "template"
    return text, write_letter(job, text, backend), backend


def _interactive() -> dict:
    jobs = load_cached_jobs()
    if not jobs:
        print("No cached jobs. Run `python -m src.run` first.")
        sys.exit(1)
    top = jobs[:25]
    print("\nTop matches:\n")
    for i, j in enumerate(top, 1):
        print(f"{i:>3}. [{j.get('fit_score')}] {j.get('title')} — {j.get('company')}")
    choice = input("\nWhich number? ").strip()
    try:
        return top[int(choice) - 1]
    except (ValueError, IndexError):
        print("Not a valid choice.")
        sys.exit(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Draft a cover letter for one job.")
    ap.add_argument("--job-id", help="job_id from the sheet or cached results")
    ap.add_argument("--interactive", action="store_true", help="pick from top matches")
    ap.add_argument("--url")
    ap.add_argument("--title")
    ap.add_argument("--company")
    ap.add_argument("--description", help="paste the posting text")
    ap.add_argument("--description-file", help="or point at a file containing it")
    args = ap.parse_args()

    if args.interactive:
        job = _interactive()
    elif args.job_id:
        job = find_job(args.job_id)
        if not job:
            print(f"No cached job with id {args.job_id!r}. Run `python -m src.run` first.")
            sys.exit(1)
    elif args.title:
        desc = args.description or ""
        if args.description_file:
            desc = Path(args.description_file).read_text(encoding="utf-8")
        job = {
            "job_id": "manual",
            "title": args.title,
            "company": args.company or "",
            "url": args.url or "",
            "location": "",
            "salary": "",
            "description": desc,
        }
    else:
        ap.error("give --interactive, --job-id, or at least --title")

    text, path, backend = generate(job)
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)
    print(f"\nBackend: {backend}")
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
