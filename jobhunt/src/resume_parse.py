"""
resume_parse.py — turn an uploaded resume (PDF / DOCX / MD / TXT) into a structured profile.

Deterministic first: text extraction -> section split -> roles with date ranges -> education ->
skills (via the shared taxonomy, with years-of-use estimated from the roles that mention them) ->
seniority, domains, quantified achievements. No LLM is needed. `enrich_with_llm` can optionally add a
summary / target titles on top, but nothing depends on it.

Nothing here invents facts: every skill records where it was found (evidence), and the profile is
editable by the user afterwards (see profile_store).
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from src import skills_taxonomy as tax

MAX_BYTES = 8 * 1024 * 1024


class ResumeError(ValueError):
    """The file could not be read as a resume."""


# ---------------------------------------------------------------------------
# text extraction
# ---------------------------------------------------------------------------

def extract_text(data: bytes, filename: str) -> str:
    if not data:
        raise ResumeError("the file is empty")
    if len(data) > MAX_BYTES:
        raise ResumeError("file is larger than 8 MB")
    ext = Path(filename or "").suffix.lower()
    if ext in (".md", ".txt", ".markdown", ".text", ""):
        text = data.decode("utf-8", errors="replace")
    elif ext == ".docx":
        text = _docx_text(data)
    elif ext == ".pdf" or data[:4] == b"%PDF":
        text = _pdf_text(data)
    elif ext in (".doc", ".rtf", ".odt", ".html", ".htm"):
        text = _textutil(data, ext)
    else:
        raise ResumeError(f"unsupported file type {ext!r} — upload PDF, DOCX, MD or TXT")
    text = normalise(text)
    if len(text) < 80:
        raise ResumeError("could not read any text from that file (is it a scanned image? try a text-based PDF or DOCX)")
    return text


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ResumeError("not a valid .docx file") from exc
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    import html
    return html.unescape(xml)


def _pdf_text(data: bytes) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ResumeError("PDF reading needs poppler's `pdftotext` (brew install poppler) — or upload DOCX/MD/TXT instead")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.pdf"
        src.write_bytes(data)
        try:
            out = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(src), "-"], capture_output=True, timeout=45)
        except subprocess.TimeoutExpired as exc:
            raise ResumeError("PDF took too long to read") from exc
        if out.returncode != 0:
            raise ResumeError("could not read that PDF (encrypted or corrupt?)")
        text = out.stdout.decode("utf-8", errors="replace")
    # -layout keeps two-column CVs readable but leaves wide gaps
    return re.sub(r" {3,}", "  ", text)


def _textutil(data: bytes, ext: str) -> str:
    exe = shutil.which("textutil")
    if not exe:
        raise ResumeError(f"{ext} files need macOS textutil — save the resume as DOCX or PDF instead")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{ext}"
        src.write_bytes(data)
        out = subprocess.run([exe, "-convert", "txt", "-stdout", str(src)], capture_output=True, timeout=30)
        if out.returncode != 0:
            raise ResumeError(f"could not convert {ext} file")
        return out.stdout.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------

SECTION_ALIASES = {
    "summary": ("summary", "profile", "professional summary", "objective", "about", "about me", "career summary", "personal statement"),
    "experience": ("experience", "work experience", "professional experience", "employment", "work history",
                   "employment history", "career history", "relevant experience"),
    "skills": ("skills", "technical skills", "core competencies", "key skills", "competencies", "technologies",
               "skills & tools", "skills and tools", "areas of expertise", "expertise"),
    "education": ("education", "academic background", "education & training", "qualifications", "academic qualifications"),
    "projects": ("projects", "selected projects", "personal projects", "key projects", "open source"),
    "certifications": ("certifications", "certificates", "licenses", "licences", "training", "courses", "certifications & training"),
    "awards": ("awards", "achievements", "honors", "honours", "accomplishments"),
    "other": ("references", "interests", "hobbies", "languages", "volunteer", "volunteering", "publications"),
}
_HEADING_TO_KEY = {alias: key for key, aliases in SECTION_ALIASES.items() for alias in aliases}


_HEADING_HINTS = [(r"\bappendix\b|\blinks?\b|\breferences?\b", "other"), (r"\bprojects?\b|open[- ]source|published work|portfolio", "projects"),
                  (r"\bawards?\b|highlights|achievements|leadership", "awards"), (r"certificat", "certifications")]


def _strip_md(line: str) -> str:
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
    line = re.sub(r"[*_`]{1,3}", "", line)
    return line.strip()


def _heading_key(line: str) -> str | None:
    t = _strip_md(line).strip(":").strip().lower()
    t = re.sub(r"\s+", " ", t)
    if not t or len(t) > 60:
        return None
    if t in _HEADING_TO_KEY:
        return _HEADING_TO_KEY[t]
    if not re.match(r"^\s{0,3}#{1,2}\s", line):
        return None
    # a top-level markdown heading that isn't a stock name: go by what it is about, so a long resume's extra sections
    # ("Independent & Side Projects (2025 – 2026)", "Awards & Leadership", "Appendix: Full Project Catalogue") end the
    # section before them instead of being read as more employment or more education
    t = re.sub(r"\s*\(.*?\)\s*$", "", t)
    if t in _HEADING_TO_KEY:
        return _HEADING_TO_KEY[t]
    for rx, key in _HEADING_HINTS:
        if re.search(rx, t):
            return key
    return None


def split_sections(text: str) -> dict[str, str]:
    """{'header': ..., 'summary': ..., 'experience': ...}. Unknown text before the first heading is 'header'."""
    out: dict[str, list[str]] = {"header": []}
    cur = "header"
    for line in text.split("\n"):
        key = _heading_key(line)
        if key and (line.strip().startswith("#") or line.strip().isupper() or len(line.strip()) < 32):
            cur = key
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append(line)
    return {k: "\n".join(v).strip() for k, v in out.items() if "\n".join(v).strip()}


# ---------------------------------------------------------------------------
# dates & roles
# ---------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE = rf"(?:{_MON}\.?,?\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
_PRESENT = r"(?:present|current|now|to date|ongoing|today)"
RANGE_RE = re.compile(rf"({_DATE})\s*(?:[-–—]|to|until)\s*({_DATE}|{_PRESENT})", re.I)


def _to_month(tok: str, *, end: bool = False, today: date | None = None) -> int | None:
    """Month index (year*12+month-1) for a date token."""
    today = today or date.today()
    t = tok.strip().lower().rstrip(".,")
    if re.fullmatch(_PRESENT, t):
        return today.year * 12 + today.month - 1
    m = re.fullmatch(rf"({_MON})\.?,?\s+(\d{{4}})", t)
    if m:
        return int(m.group(2)) * 12 + _MONTHS[m.group(1)[:3]] - 1
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)) * 12 + int(m.group(1)) - 1
    m = re.fullmatch(r"(\d{4})", t)
    if m:  # a bare year: start = January, end = December
        return int(m.group(1)) * 12 + (11 if end else 0)
    return None


def month_label(idx: int | None) -> str:
    if idx is None:
        return ""
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def union_months(intervals: list[tuple[int, int]]) -> int:
    """Total months covered by possibly-overlapping (start, end) intervals (end inclusive)."""
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e + 1:
            if cur_e is not None:
                total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s + 1
    return total


_TITLE_WORDS = ("engineer", "developer", "analyst", "manager", "officer", "assistant", "director", "consultant", "specialist",
                "architect", "administrator", "coordinator", "lead", "head", "supervisor", "technician", "scientist", "designer",
                "accountant", "executive", "representative", "associate", "intern", "clerk", "teacher", "lecturer", "advisor",
                "adviser", "programmer", "founder", "owner", "agent", "planner", "auditor", "controller", "trainee")


def _looks_like_title(s: str) -> bool:
    return any(w in s.lower() for w in _TITLE_WORDS)


def _clean_line(s: str) -> str:
    s = _strip_md(s)
    return re.sub(r"\s+", " ", s).strip(" \t·|•-–—,;:")


def parse_roles(exp_text: str, today: date | None = None) -> list[dict]:
    lines = exp_text.split("\n")
    idx = [i for i, ln in enumerate(lines) if RANGE_RE.search(_strip_md(ln)) and not ln.strip().startswith(("-", "•", "*  "))
           and not re.match(r"^\s*[-•]", ln)]
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    heads = []
    for i in idx:
        line = _strip_md(lines[i])
        ms = list(RANGE_RE.finditer(line))
        # "Analyst (2021 – 2023), then Engineer (2023 – Present)": one header, one stretch of time
        ss = [_to_month(m.group(1), today=today) for m in ms]
        es = [_to_month(m.group(2), end=True, today=today) for m in ms]
        s = min((x for x in ss if x is not None), default=None)
        e = min(max((x for x in es if x is not None), default=-1), now)   # "2025 – 2026" can't end after today
        head = _clean_line(re.sub(r"\(\s*\)", "", RANGE_RE.sub(" ", line)).replace(" ,", ","))
        heads.append((i, s, e if e >= 0 else None, head, ms[-1].group(2)))
    roles: list[dict] = []
    umbrella = ""
    for n, (i, s, e, head, end_tok) in enumerate(heads):
        if s is None or e is None or e < s:
            continue
        end_line = idx[n + 1] - 1 if n + 1 < len(idx) else len(lines)
        n_bullets = sum(1 for b in lines[i + 1:end_line] if re.match(r"^\s*[-•*]\s+", b))
        nxt = heads[n + 1] if n + 1 < len(heads) else None
        table = lines[i].lstrip().startswith("|")
        # an employer line with its overall dates, followed by the roles held there: context, not a role of its own
        if (not table and head and not _looks_like_title(head) and n_bullets < 2 and nxt and nxt[1] is not None and nxt[2] is not None
                and s <= nxt[1] and nxt[2] <= e):
            umbrella = re.sub(r"\s*\(.*$", "", head)
            continue
        prev = ""
        for j in range(i - 1, max(-1, i - 3), -1):
            cand = _clean_line(lines[j]) if j >= 0 else ""
            if cand and not re.match(r"^\s*[-•|]", lines[j]) and not RANGE_RE.search(cand):
                prev = cand
                break
        if table:   # a "| Role, Employer | Dates |" row
            head = _clean_line(head.split("|")[0])
            first, _, rest = head.partition(", ")
            if rest and _looks_like_title(first):
                head, prev = first, rest
        title, company = "", ""
        parts = [p.strip() for p in re.split(r"\s+(?:at|@)\s+|\s*[|·•]\s*|\s+[—–]\s+", head) if p.strip()]
        if head and _looks_like_title(head) and len(parts) <= 1:
            title, company = head, prev
        elif len(parts) >= 2:
            tparts = [p for p in parts if _looks_like_title(p)]
            title = tparts[0] if tparts else parts[0]
            rest = [p for p in parts if p != title]
            company = rest[0] if rest else prev
        elif head:
            company, title = head, prev if _looks_like_title(prev) else ""
        else:
            company, title = prev, ""
        # bullets follow the header, but a company line that PRECEDES the next header belongs to that next role
        body_lines = lines[i + 1:end_line]
        while body_lines and body_lines[-1].strip() and not re.match(r"^\s*[-•*]", body_lines[-1]) and n + 1 < len(idx):
            body_lines.pop()
        bullets = [_clean_line(b) for b in body_lines if re.match(r"^\s*[-•*]\s+", b) or len(b.strip()) > 60]
        bullets = [b for b in bullets if b]
        roles.append({
            "title": title[:120], "company": (re.sub(r"\s*\(.*?\)\s*$", "", company)[:120] if company else "") or umbrella[:120],
            "start": month_label(s), "end": "" if re.fullmatch(_PRESENT, end_tok.strip(), re.I) else month_label(e),
            "current": bool(re.fullmatch(_PRESENT, end_tok.strip(), re.I)),
            "months": e - s + 1, "bullets": bullets, "_span": (s, e),
        })
    return roles


# ---------------------------------------------------------------------------
# education, contact, misc
# ---------------------------------------------------------------------------

_DEGREES = [
    ("doctorate", r"\b(ph\.?d|doctorate|doctor of)\b"),
    ("master", r"\b(m\.?sc|m\.?s\b|m\.?a\b|mba|master'?s|masters|master of)\b"),
    ("bachelor", r"\b(b\.?sc|b\.?s\b|b\.?a\b|b\.?eng|bachelor'?s?|bachelor of|undergraduate degree|b\.?tech)\b"),
    ("associate", r"\b(associate'?s?|a\.?a\.?s?\b|diploma|higher national)\b"),
    ("secondary", r"\b(cape|csec|a-?levels?|o-?levels?|high school|secondary school|ged)\b"),
]
DEGREE_RANK = {"secondary": 1, "associate": 2, "bachelor": 3, "master": 4, "doctorate": 5}


def parse_education(text: str) -> list[dict]:
    out = []
    for raw in re.split(r"\n{1,}", text):
        ln = _clean_line(raw)
        if len(ln) < 6:
            continue
        for level, rx in _DEGREES:
            if re.search(rx, ln, re.I):
                yrs = re.findall(r"(?:19|20)\d{2}", ln)
                inst = re.search(r"(university[^,.\n·|–—]*|college[^,.\n·|–—]*|institute[^,.\n·|–—]*|school[^,.\n·|–—]*)", ln, re.I)
                out.append({"level": level, "text": ln[:200], "institution": inst.group(1).strip()[:100] if inst else "",
                            "year": int(yrs[-1]) if yrs else None})
                break
    return out


def parse_contact(text: str) -> dict:
    head = "\n".join(text.split("\n")[:12])
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", head)
    phone = re.search(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", head)
    links = re.findall(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/|github\.com/)[\w./-]+|[\w-]+\.dev\b", head)
    name = ""
    for ln in text.split("\n")[:5]:
        c = _clean_line(ln)
        if 3 <= len(c) <= 50 and not re.search(r"[@\d]|resume|curriculum|cv\b", c, re.I) and len(c.split()) <= 5:
            name = c.title() if c.isupper() else c
            break
    return {"name": name, "email": email.group(0) if email else "", "phone": phone.group(0).strip() if phone else "",
            "links": list(dict.fromkeys(links))[:5]}


def quantified_achievements(text: str, limit: int = 12) -> list[str]:
    out = []
    for ln in text.split("\n"):
        c = _clean_line(ln)
        if re.search(r"\d[\d,.]*\s*(?:\+|%|k\b|m\b|hours?|hrs|policies|territories|users|clients|customers|renewals|locations|million)|TT\$|US\$|\$\s?\d", c, re.I) and len(c) > 25:
            out.append(c[:260])
    return out[:limit]


_DOMAIN_SKILLS = {"Insurance", "Claims", "Underwriting", "Actuarial", "Policy Administration", "Regulatory Reporting",
                  "Banking", "Fintech", "Accounting", "Financial Reporting", "Telecommunications", "Energy", "Government",
                  "Healthcare", "Retail", "Hospitality", "Manufacturing", "Education", "Real Estate", "Maritime", "Non-profit",
                  "Supply Chain", "Risk Management", "Auditing"}


def seniority(years: float, titles: list[str]) -> str:
    t = " ".join(titles).lower()
    t = re.sub(r"\b(?:to|of) the [a-z ]*?(?:director|chief|vp|president)\b", " ", t)   # "Assistant to the Managing Director" isn't one
    if re.search(r"\b(principal|staff|director|head of|chief|vp)\b", t):
        return "lead"
    if re.search(r"\b(senior|sr\.?|lead)\b", t) or years >= 8:
        return "senior"
    if years < 1.5:
        return "entry"
    if years < 4:
        return "mid"
    return "mid-senior"


# ---------------------------------------------------------------------------
# the whole profile
# ---------------------------------------------------------------------------

def parse_resume(text: str, *, today: date | None = None) -> dict:
    today = today or date.today()
    secs = split_sections(text)
    contact = parse_contact(text)
    roles = parse_roles(secs.get("experience", ""), today)

    spans = [r.pop("_span") for r in roles] if roles else []
    for r in roles:
        r.pop("_span", None)
    # recompute spans for skills-years (pop above removed them from dicts; keep parallel list)
    total_months = union_months(spans)
    years = round(total_months / 12, 1)

    skills_sec = secs.get("skills", "")
    body_without_headings = "\n".join(ln for ln in text.split("\n") if not _heading_key(ln))
    found = tax.find_skills(body_without_headings)
    in_skills = set(tax.find_skills(skills_sec))
    skills: dict[str, dict] = {}
    # what each role used: the skills it names plus what those imply (a "Django" role is a Python role)
    role_skills = []
    for r in roles:
        named = set(tax.find_skills(" ".join(r["bullets"]) + " " + r["title"]))
        role_skills.append(named | tax.implied(named))
    found = {**{s: 0 for s in tax.implied(found)}, **found}
    # A long resume mentions many things in passing ("syncs live inventory", "a teaching assistant app"). A word from a
    # broad business/domain area is only a skill when the Skills section lists it or the resume keeps coming back to it.
    need = max(1, round(len(text) / 15000))
    for canon, n in found.items():
        cat = tax.CATEGORY.get(canon, "Other")
        if cat in tax.BROAD_CATEGORIES and canon not in in_skills and n < need:
            continue
        role_spans = []
        recent = 0
        for used, sp in zip(role_skills, spans):
            if canon in used:
                role_spans.append(sp)
                recent = max(recent, sp[1])
        yrs = round(union_months(role_spans) / 12, 1) if role_spans else 0.0
        used_recent = bool(role_spans) and recent >= today.year * 12 + today.month - 1 - 18
        skills[canon] = {"category": cat, "mentions": n, "in_skills_section": canon in in_skills,
                         "years": yrs, "recent": used_recent if role_spans else canon in in_skills,
                         "source": "resume"}

    domains = sorted(s for s in skills if s in _DOMAIN_SKILLS)
    titles = [r["title"] for r in roles if r["title"]]
    edu = parse_education(secs.get("education", "")) or parse_education("\n".join(text.split("\n")))
    highest = max((e["level"] for e in edu), key=lambda l: DEGREE_RANK[l], default="")
    certs = [_clean_line(x) for x in secs.get("certifications", "").split("\n") if len(_clean_line(x)) > 4][:15]
    projects = []
    for ln in secs.get("projects", "").split("\n"):
        c = _clean_line(ln)
        if len(c) > 20:
            name, _, rest = c.partition(" — ") if " — " in c else c.partition(": ")
            projects.append({"name": name[:80], "text": (rest or c)[:300]})
    summary = _clean_line(secs.get("summary", "").replace("\n", " "))[:900]

    return {
        "contact": contact,
        "headline": titles[0] if titles else "",
        "summary": summary,
        "years_experience": years,
        "roles": roles,
        "titles": list(dict.fromkeys(titles)),
        "education": edu,
        "highest_education": highest,
        "skills": skills,
        "domains": domains,
        "certifications": certs,
        "projects": projects[:12],
        "achievements": quantified_achievements(text),
        "seniority": seniority(years, titles),
        "sections_found": [k for k in secs if k != "header"],
        "chars": len(text),
    }


def enrich_with_llm(text: str, profile: dict, cfg: dict | None = None) -> dict:
    """
    OPTIONAL: ask an LLM for a headline, target titles and honest strengths/gaps. Adds `llm` to the profile;
    never overwrites deterministic fields. Only call when the user asked (the resume text goes to the provider).
    """
    import json
    from src import llm

    system = ("You extract structured data from a resume. Answer with ONE JSON object and nothing else. "
              "Use only facts present in the resume; if unsure, leave a field empty.")
    user = (
        "Return JSON with keys: headline (string), target_titles (up to 8 job titles this person is qualified for), "
        "strengths (up to 5 short strings), gaps (up to 5 short strings, honest), summary (2 sentences).\n\n"
        f"RESUME:\n{text[:9000]}"
    )
    raw, backend = llm.generate(system, user, cfg or {})
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ResumeError("the AI did not return JSON")
    data = json.loads(m.group(0))
    clean = {
        "headline": str(data.get("headline") or "")[:120],
        "target_titles": [str(x)[:80] for x in (data.get("target_titles") or []) if str(x).strip()][:8],
        "strengths": [str(x)[:200] for x in (data.get("strengths") or [])][:5],
        "gaps": [str(x)[:200] for x in (data.get("gaps") or [])][:5],
        "summary": str(data.get("summary") or "")[:500],
        "backend": backend,
    }
    profile["llm"] = clean
    return profile
