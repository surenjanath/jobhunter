"""
trinidad.py — Trinidad & Tobago local job board fetchers.

Boards covered (all public, no keys, no login):

  caribbeanjobs      RSS (several keyword queries) + JobPosting JSON-LD detail
  jobstt             sitemap (newest first) + JobPosting JSON-LD
  trinidadjob        sitemap (newest first) + JobPosting JSON-LD
  employtt           government portal: listing page + detail page text
  findworktt         JSON API (demo/placeholder rows are filtered out)
  evecaribbean       Eve Anderson Recruitment: sitemap + detail page text
  islandjobhunt      paginated listing + JobPosting JSON-LD
  caribbeanjobsonline  regional board, T&T listing + detail page text
  digicel            Digicel careers (SuccessFactors) — Trinidad postings only

Plus any number of user-defined sites (`trinidad_custom_sites` in profile.yaml)
that publish schema.org JobPosting data, via `fetch_custom_site`.

Design rules
------------
* One shared JobPosting JSON-LD parser: most boards publish it, and it gives
  company / dates / expiry / salary without brittle HTML scraping.
* Job ids come from the site's own slug or numeric id — never `hash()`, which
  is randomised per process and made every scan create duplicate rows.
* Expired postings (validThrough in the past) are dropped at the source.
* Fetchers *raise* `SourceError` when a board is unreachable or its layout has
  drifted (links found but nothing parsed). `run_source` turns that into
  health data (count / ms / error) so a broken board is visible, not silent.
"""

from __future__ import annotations

import concurrent.futures as _cf
import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src import tt_geo
from src.sources import HEADERS, _iso, _looks_remote, strip_html

log = logging.getLogger(__name__)

TIMEOUT = 25
DEFAULT_LIMIT = 40      # newest N postings per board (polite + fast)
WORKERS = 4             # concurrent detail-page fetches per board
HTML_HEADERS = {**HEADERS, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


class SourceError(RuntimeError):
    """A board could not be read (network failure or the layout changed)."""


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=2, read=0, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))))
_session.mount("http://", _session.get_adapter("https://"))


def fetch(url: str, params: dict | None = None, *, required: bool = False, timeout: int = TIMEOUT) -> str | None:
    """GET text. Returns None on failure, or raises SourceError when `required`."""
    try:
        r = _session.get(url, params=params, headers=HTML_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        msg = f"HTTP {r.status_code} for {url}"
    except requests.RequestException as exc:
        msg = f"{type(exc).__name__} for {url}"
    log.info("  tt fetch failed: %s", msg)
    if required:
        raise SourceError(msg)
    return None


def _pmap(fn: Callable, items: list, workers: int = WORKERS) -> list:
    """Run fn over items concurrently, dropping Nones and swallowing per-item errors."""
    out = []
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in [ex.submit(fn, it) for it in items]:
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001
                log.debug("  tt detail failed: %r", exc)
                continue
            if res:
                out.append(res)
    return out


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------

_LD_RE = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def clean_text(raw: str | None, limit: int = 6000) -> str:
    """Unescape (possibly multiply-escaped) HTML, strip tags, tidy whitespace."""
    if not raw:
        return ""
    text = raw
    for _ in range(4):  # some boards escape the markup 2-3 times
        new = html.unescape(text)
        if new == text:
            break
        text = new
    text = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h\d)\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n• ", text)
    text = re.sub(r"<[^>]+>", " ", text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()[:limit]


def page_text(page: str) -> list[str]:
    """Visible text of an HTML page as a list of non-empty lines."""
    body = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page)
    body = re.sub(r"(?i)<\s*(br|/p|/div|/li|/tr|/h\d|/option|/span)\s*/?>", "\n", body)
    body = html.unescape(re.sub(r"<[^>]+>", "\n", body))
    return [ln.strip() for ln in body.replace("\xa0", " ").splitlines() if ln.strip()]


def jobposting_ld(page: str) -> dict | None:
    """First schema.org JobPosting object in a page's JSON-LD (handles @graph and lists)."""
    for blob in _LD_RE.findall(page or ""):
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop(0)
            if not isinstance(node, dict):
                continue
            kind = node.get("@type")
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                return node
            if "@graph" in node:
                stack.extend(node["@graph"] if isinstance(node["@graph"], list) else [node["@graph"]])
    return None


def _first(*vals) -> str:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def ld_company(ld: dict) -> str:
    org = ld.get("hiringOrganization")
    if isinstance(org, list):
        org = org[0] if org else {}
    if isinstance(org, dict):
        return clean_text(org.get("name"), 150)
    return clean_text(org, 150) if isinstance(org, str) else ""


def ld_location(ld: dict) -> str:
    loc = ld.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    parts: list[str] = []
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [addr.get("streetAddress"), addr.get("addressLocality"), addr.get("addressRegion")]
        elif isinstance(addr, str):
            parts = [addr]
    seen: list[str] = []
    for p in parts:
        p = clean_text(p, 100) if isinstance(p, str) else ""
        # skip exact repeats and a region already contained in an earlier (longer) part
        if p and not any(p.lower() in s.lower() for s in seen):
            seen.append(p)
    return ", ".join(seen)


def ld_salary(ld: dict) -> str:
    base = ld.get("baseSalary")
    if not isinstance(base, dict):
        return ""
    cur = (base.get("currency") or "").upper()
    val = base.get("value")
    if not isinstance(val, dict):
        return ""
    lo, hi, one = val.get("minValue"), val.get("maxValue"), val.get("value")

    def num(x):
        try:
            n = float(str(x).replace(",", ""))
            return n if n > 0 else None
        except ValueError:
            return None

    lo, hi, one = num(lo), num(hi), num(one)
    unit = (val.get("unitText") or "").lower()
    cur = "TT$" if cur in ("TTD", "") else (cur + " ")
    per = f" / {unit}" if unit else ""
    if lo and hi:
        return f"{cur}{lo:,.0f} - {cur}{hi:,.0f}{per}"
    if lo or hi or one:
        return f"{cur}{(lo or hi or one):,.0f}{per}"
    return ""


def _d(value) -> str:
    """Normalise anything date-like to YYYY-MM-DD ('' if unknown)."""
    if not value:
        return ""
    text = str(value).strip()
    m = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)  # dd/mm/yyyy (caribbeanjobsonline)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return ""
    for fmt in ("%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%d %b %Y", "%a %b %d %H:%M:%S UTC %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return _iso(value)


def is_expired(expires_at: str) -> bool:
    if not expires_at:
        return False
    try:
        return date.fromisoformat(expires_at) < datetime.now().date()
    except ValueError:
        return False


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return re.sub(r"[^a-z0-9]+", "-", (path.split("/")[-1] if path else "").lower()).strip("-")[:80]


def build_job(*, source: str, key: str, title: str, company: str, url: str, location: str = "",
              description: str = "", posted_at: str = "", expires_at: str = "", salary: str = "",
              remote: bool | None = None, employment_type: str = "", local: bool = True) -> dict | None:
    """Assemble the standard job dict. Returns None for junk / expired postings."""
    title = clean_text(title, 200)
    if len(title) < 3 or not key:
        return None
    expires_at = _d(expires_at)
    if is_expired(expires_at):
        return None
    company = clean_text(company, 150) or "Unknown"
    description = clean_text(description)
    location = clean_text(location, 150)
    region = tt_geo.normalize_region(location, title) if local else ""
    if local and not location:
        location = "Trinidad & Tobago"
    elif local and "trinidad" not in location.lower() and "tobago" not in location.lower():
        location = f"{location}, Trinidad & Tobago"
    if not description:
        description = f"{title} at {company} in {location or 'remote'} via {source}."
    if employment_type:
        description = f"Employment type: {employment_type}\n{description}"
    return {
        "source": source,
        "job_id": f"{source}:{key}",
        "title": title,
        "company": company,
        "location": location,
        "remote": bool(_looks_remote(title, description[:500]) if remote is None else remote),
        "salary": salary[:120],
        "url": url,
        "description": description,
        "posted_at": _d(posted_at),
        "expires_at": expires_at,
        "region": region,
        "category": tt_geo.classify_category(title, description),
    }


def job_from_ld(ld: dict, *, source: str, key: str, url: str, fallback_company: str = "",
                fallback_location: str = "", lastmod: str = "") -> dict | None:
    posted = _d(ld.get("datePosted"))
    lm = _d(lastmod)
    if lm and (not posted or lm > posted):
        posted = lm  # boards re-stamp renewed listings via lastmod; datePosted can be years old
    emp = ld.get("employmentType")
    emp = ", ".join(emp) if isinstance(emp, list) else (emp or "")
    return build_job(
        source=source, key=key, title=ld.get("title") or "", company=ld_company(ld) or fallback_company,
        url=url, location=ld_location(ld) or fallback_location, description=ld.get("description") or "",
        posted_at=posted, expires_at=ld.get("validThrough") or "", salary=ld_salary(ld),
        employment_type=(emp.replace("_", " ").title() if emp and emp != "Default" else ""))


def sitemap_entries(url: str, url_re: str, *, required: bool = True) -> list[tuple[str, str]]:
    """(loc, lastmod) for sitemap urls matching url_re, newest first."""
    text = fetch(url, required=required)
    if not text:
        return []
    out = []
    for block in re.findall(r"<url>(.*?)</url>", text, re.S) or [text]:
        loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block)
        if not loc or not re.search(url_re, loc.group(1)):
            continue
        lm = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block)
        out.append((html.unescape(loc.group(1)), lm.group(1) if lm else ""))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _sitemap_ld_source(source: str, sitemap: str, url_re: str, limit: int, *, key_fn=slug_from_url,
                       fallback_company: str = "") -> list[dict]:
    entries = sitemap_entries(sitemap, url_re)
    if not entries:
        raise SourceError(f"sitemap empty or unreadable: {sitemap}")
    entries = entries[: max(limit * 2, limit + 10)]  # headroom for expired/unparseable rows

    def one(entry):
        url, lastmod = entry
        page = fetch(url)
        ld = jobposting_ld(page) if page else None
        if not ld:
            return None
        return job_from_ld(ld, source=source, key=key_fn(url), url=url, lastmod=lastmod,
                           fallback_company=fallback_company)

    jobs = _pmap(one, entries)
    _check_layout(source, len(entries), jobs)
    return jobs[:limit]


def _check_layout(source: str, candidates: int, jobs: list) -> None:
    """Links were found but nothing parsed and nothing was merely expired → layout drift."""
    if candidates >= 5 and not jobs:
        raise SourceError(f"{source}: found {candidates} postings but parsed 0 — site layout may have changed")


# ---------------------------------------------------------------------------
# individual boards
# ---------------------------------------------------------------------------

_CJ_KEYWORDS = ["", "engineer", "developer", "analyst", "manager", "officer", "technician", "accountant",
                "sales", "assistant", "supervisor", "customer"]


def fetch_caribbeanjobs(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """CaribbeanJobs — RSS (Location=124 is Trinidad) across several keyword queries, then JSON-LD detail."""
    seen: dict[str, dict] = {}
    got_any = False
    for kw in _CJ_KEYWORDS:
        params = {"Location": 124}
        if kw:
            params["Keywords"] = kw
        text = fetch("https://www.caribbeanjobs.com/rss.aspx", params)
        if text is None:
            continue
        got_any = True
        for item in re.findall(r"<item>(.*?)</item>", text, re.S):
            link = re.search(r"<link>\s*([^<]+?)\s*</link>", item)
            title = re.search(r"<title>\s*(.*?)\s*</title>", item, re.S)
            desc = re.search(r"<description>\s*(.*?)\s*</description>", item, re.S)
            jid = re.search(r"Id=(\d+)", link.group(1)) if link else None
            if not (jid and title):
                continue
            meta = html.unescape(desc.group(1)) if desc else ""
            m = re.search(r"Company:\s*(.*?),\s*Location:\s*(.*?),\s*Salary:\s*(.*)$", meta, re.S)
            seen.setdefault(jid.group(1), {
                "id": jid.group(1), "url": link.group(1), "title": html.unescape(title.group(1)),
                "company": m.group(1).strip() if m else "", "location": m.group(2).strip() if m else "",
                "salary": (m.group(3).strip() if m else ""),
            })
        if len(seen) >= limit * 2:
            break
    if not got_any:
        raise SourceError("caribbeanjobs RSS unreachable")
    rows = sorted(seen.values(), key=lambda r: -int(r["id"]))[: limit * 2]  # higher Id == newer

    def one(row):
        page = fetch(f"https://www.caribbeanjobs.com/JobDesc.aspx?Id={row['id']}")
        ld = jobposting_ld(page) if page else None
        sal = row["salary"] if row["salary"] and not re.search(r"not disclosed|negotiable|confidential", row["salary"], re.I) else ""
        if ld:
            job = job_from_ld(ld, source="caribbeanjobs", key=row["id"], url=ld.get("url") or row["url"],
                              fallback_company=row["company"], fallback_location=row["location"])
            if job and not job["salary"]:
                job["salary"] = sal
            return job
        return build_job(source="caribbeanjobs", key=row["id"], title=row["title"], company=row["company"],
                         url=row["url"], location=row["location"], salary=sal)

    jobs = _pmap(one, rows)
    _check_layout("caribbeanjobs", len(rows), jobs)
    return jobs[:limit]


def fetch_jobstt(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """JobsTT — sitemap (newest first) + JSON-LD."""
    return _sitemap_ld_source("jobstt", "https://jobstt.com/sitemap-job.xml",
                              r"^https://jobstt\.com/job/[^/]+/?$", limit)


def fetch_trinidadjob(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """TrinidadJob (WordPress + WP Job Manager) — job_listing sitemap + JSON-LD."""
    return _sitemap_ld_source("trinidadjob", "https://trinidadjob.com/job_listing-sitemap.xml",
                              r"^https://trinidadjob\.com/job/[^/]+/?$", limit)


def fetch_islandjobhunt(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """IslandJobHunt — paginated T&T listing (50/page) + JSON-LD."""
    base = "https://islandjobhunt.com"
    links: list[str] = []
    for page_no in range(1, 4):
        text = fetch(f"{base}/jobs/in-trinidad-and-tobago", {"page": page_no} if page_no > 1 else None,
                     required=(page_no == 1))
        if not text:
            break
        new = [urljoin(base, h) for h in re.findall(r'href="(/jobs/\d+-[^"/]+)"', text)]
        links += [u for u in dict.fromkeys(new) if u not in links]
        if len(links) >= limit * 2:
            break
    if not links:
        raise SourceError("islandjobhunt listing had no job links")
    links = links[: limit * 2]

    def one(url):
        page = fetch(url)
        ld = jobposting_ld(page) if page else None
        if not ld:
            return None
        m = re.search(r"/jobs/(\d+)-", url)
        return job_from_ld(ld, source="islandjobhunt", key=m.group(1) if m else slug_from_url(url), url=url)

    jobs = _pmap(one, links)
    _check_layout("islandjobhunt", len(links), jobs)
    return jobs[:limit]


def fetch_employtt(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """EmployTT (Government of T&T) — real listing + detail pages (was homepage-title guessing)."""
    base = "https://employtt.gov.tt"
    text = fetch(f"{base}/jobs/list", required=True)
    ids = sorted(set(re.findall(r"/jobs/view/(\d+)", text)), key=int, reverse=True)[: limit * 2]
    if not ids:
        raise SourceError("employtt listing had no job links")

    def one(jid):
        url = f"{base}/jobs/view/{jid}"
        page = fetch(url)
        if not page:
            return None
        lines = page_text(page)
        try:
            i = lines.index("Jobs Listing")
        except ValueError:
            return None
        title = lines[i + 1] if len(lines) > i + 1 else ""
        company = lines[i + 3] if len(lines) > i + 3 else ""
        blob = "\n".join(lines[i:])

        def grab(label):
            m = re.search(rf"{label}\s*:?\s*\n(.+)", blob)
            return m.group(1).strip() if m else ""

        exp = _d(grab("Expires"))
        loc = grab("Work Location")
        salary = grab(r"Salary \(Monthly\)")
        salary = "" if re.search(r"conceal|not disclosed", salary, re.I) else salary
        j = blob.find("Job Description")
        desc = "\n".join(lines[i:][blob[:j].count("\n") + 1:]) if j >= 0 else blob
        posted = ""
        pm = re.search(r"Posted:\s*\n(.+)", blob)
        if pm:
            posted = _relative_date(pm.group(1))
        return build_job(source="employtt", key=jid, title=title, company=company or "Government of T&T",
                         url=url, location=loc, description=desc, posted_at=posted, expires_at=exp,
                         salary=salary, employment_type=", ".join(filter(None, [grab("Type"), grab("Term")])).title(),
                         remote=False)

    jobs = _pmap(one, ids)
    _check_layout("employtt", len(ids), jobs)
    return jobs[:limit]


def _relative_date(text: str) -> str:
    """'1 week ago' / '3 days ago' / 'today' -> YYYY-MM-DD."""
    t = (text or "").lower().strip()
    today = datetime.now().date()
    if "today" in t or "just now" in t or "hour" in t or "minute" in t:
        return today.isoformat()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*(day|week|month)", t)
    if not m:
        m2 = re.match(r"(a|an|one)\s+(day|week|month)", t)
        if not m2:
            return _d(text)
        n, unit = 1, m2.group(2)
    else:
        n, unit = int(m.group(1)), m.group(2)
    return (today - timedelta(days=n * {"day": 1, "week": 7, "month": 30}[unit])).isoformat()


def fetch_findworktt(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """FindWorkTT — JSON API. The launch database contains only [DEMO] rows; those are skipped."""
    text = fetch("https://www.findworktt.com/api/jobs", {"limit": max(limit, 50)}, required=True)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SourceError("findworktt returned non-JSON") from exc
    rows = data.get("jobs") if isinstance(data, dict) else data
    out = []
    demo = 0
    for j in rows or []:
        title = j.get("title") or ""
        if "[DEMO]" in title or "DEMO DATA ONLY" in (j.get("description") or ""):
            demo += 1
            continue
        jid = j.get("id") or j.get("slug")
        salary = ""
        if j.get("salary_min") and j.get("salary_max"):
            try:
                salary = f"TT${int(j['salary_min']):,} - TT${int(j['salary_max']):,}"
            except (TypeError, ValueError):
                pass
        job = build_job(
            source="findworktt", key=str(jid), title=title, company=j.get("company_name") or j.get("company") or "",
            url=j.get("application_url") or f"https://www.findworktt.com/jobs/{jid}",
            location=j.get("location") or "", description=j.get("description") or "",
            posted_at=j.get("created_at") or "", salary=salary,
            remote=_looks_remote(j.get("work_arrangement") or "", j.get("location") or "", title))
        if job:
            out.append(job)
    if demo and not out:
        log.info("  findworktt: only %d [DEMO] placeholder rows published — no real listings yet", demo)
    return out[:limit]


def fetch_evecaribbean(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Eve Anderson Recruitment — Trinidad postings from job-sitemap.xml + detail page text."""
    entries = sitemap_entries("https://evecaribbean.com/job-sitemap.xml", r"^https://evecaribbean\.com/tt/job/[^/]+/?$")
    if not entries:
        raise SourceError("evecaribbean sitemap empty")
    entries = entries[: limit * 2]

    def one(entry):
        url, lastmod = entry
        page = fetch(url)
        if not page:
            return None
        lines = page_text(page)
        og = re.search(r'<meta property="og:title" content="([^"]+)"', page)
        h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
        title = clean_text(h1.group(1) if h1 else (og.group(1) if og else ""), 200)
        title = re.sub(r"\s*[-|–]\s*(Eve Anderson|Caribbean).*$", "", title)
        listed = next((ln for ln in lines if ln.startswith("Listed ")), "")
        start = next((i for i, ln in enumerate(lines) if ln.startswith("Listed ")), 0)
        end = next((i for i, ln in enumerate(lines) if i > start and re.match(r"(?i)^(apply|share|related jobs|similar jobs)", ln)),
                   len(lines))
        desc = "\n".join(lines[start + 1:end])
        loc = ""
        for k in range(max(0, start - 6), start):
            if lines[k] == "Based in" and k + 1 < start and lines[k + 1] != ",":
                loc = lines[k + 1].strip(" ,")
        return build_job(source="evecaribbean", key=slug_from_url(url), title=title,
                         company="Eve Anderson Recruitment (client)", url=url, location=loc, description=desc,
                         posted_at=_d(listed.replace("Listed", "").strip()) or lastmod, remote=False)

    jobs = _pmap(one, entries)
    _check_layout("evecaribbean", len(entries), jobs)
    return jobs[:limit]


def fetch_caribbeanjobsonline(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Caribbean Jobs Online — T&T listing + detail page (no JSON-LD on this board)."""
    base = "https://www.caribbeanjobsonline.com"
    text = fetch(f"{base}/jobs/trinidad-tobago", required=True, timeout=15)
    urls = list(dict.fromkeys(re.findall(r'href="(https://www\.caribbeanjobsonline\.com/job/[^"]+\.htm)"', text)))
    if not urls:
        raise SourceError("caribbeanjobsonline listing had no job links")
    urls = urls[: limit * 2]

    def one(url):
        page = fetch(url, timeout=15)
        if not page:
            return None
        og = re.search(r'<meta property="og:title" content="([^"]+)"', page)
        lines = page_text(page)
        try:
            i = lines.index("Organisation")
        except ValueError:
            return None

        def nxt(label):
            try:
                return lines[lines.index(label, i) + 1]
            except (ValueError, IndexError):
                return ""

        posted, expiry = _d(nxt("Date Posted")), _d(nxt("Expiry Date"))
        j = lines.index("Expiry Date", i) + 2 if "Expiry Date" in lines[i:] else i + 8
        desc = "\n".join(ln for ln in lines[j:j + 80] if ln != "&nbsp;")
        m = re.search(r"-(\d+)\.htm$", url)
        return build_job(source="caribbeanjobsonline", key=m.group(1) if m else slug_from_url(url),
                         title=og.group(1) if og else "", company=nxt("Organisation"), url=url,
                         location=nxt("Location"), description=desc, posted_at=posted, expires_at=expiry,
                         employment_type=nxt("Contract Type"), remote=False)

    jobs = _pmap(one, urls)
    _check_layout("caribbeanjobsonline", len(urls), jobs)
    return jobs[:limit]


_DIGICEL_TT = re.compile(r"Port-of-Spain|Trinidad|Chaguanas|San-Fernando|Couva|Arima|Point-Lisas|Tobago", re.I)


def fetch_digicel(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Digicel careers (SuccessFactors) — only postings located in Trinidad & Tobago."""
    base = "https://careers.digicelgroup.com"
    entries = [(u, lm) for u, lm in sitemap_entries(f"{base}/sitemap.xml", r"/job/") if _DIGICEL_TT.search(u)]
    if not entries:
        return []  # Digicel often has no Trinidad opening — not an error
    entries = entries[:limit]

    def one(entry):
        url, _ = entry
        page = fetch(url)
        if not page:
            return None
        ld = jobposting_ld(page)
        if ld:
            m = re.search(r"/(\d+)/?$", url)
            return job_from_ld(ld, source="digicel", key=m.group(1) if m else slug_from_url(url), url=url,
                               fallback_company="Digicel")
        h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
        m = re.search(r"/job/([^/]+)/(\d+)/?$", url)
        loc = re.search(r'class="jobGeoLocation">\s*([^<]+?)\s*<', page)
        posted = re.search(r'itemprop="datePosted" content="([^"]+)"', page)
        valid = re.search(r'itemprop="validThrough" content="([^"]+)"', page)
        start = page.find('class="jobdescription"')
        chunk = page[start:start + 20000] if start >= 0 else ""
        cut = re.search(r'(?i)<a[^>]*class="[^"]*apply', chunk)
        desc = chunk[: cut.start()] if cut else chunk[:8000]
        return build_job(source="digicel", key=m.group(2) if m else slug_from_url(url),
                         title=h1.group(1) if h1 else "", company="Digicel",
                         url=url, location=(loc.group(1) if loc else "").replace(", TT", ""),
                         description=re.sub(r'^[^>]*>', "", desc), posted_at=posted.group(1) if posted else "",
                         expires_at=valid.group(1) if valid else "", remote=False)

    jobs = _pmap(one, entries)
    return jobs[:limit]


# ---------------------------------------------------------------------------
# generic "paste any careers page" fallback — used by fetch_custom_site's list_url mode when a job's detail
# page publishes no schema.org JobPosting data, so a title still gets through instead of the job being dropped.
# ---------------------------------------------------------------------------

GENERIC_JOB_PATTERN = r"(?:/(?:jobs?|careers?|vacanc(?:y|ies)|openings?|positions?|opportunit(?:y|ies))(?:/|$|[/?#-])|[?&](?:job|position)id=)"

_A_TEXT_RE = re.compile(r'<a\b[^>]*\bhref="([^"#]+)"[^>]*>(.*?)</a>', re.I | re.S)
_NAV_WORDS = {"home", "about", "about us", "contact", "contact us", "careers", "jobs", "all jobs", "view all jobs",
             "apply now", "apply", "login", "log in", "sign in", "register", "sign up", "privacy policy", "privacy",
             "terms", "terms of service", "faq", "blog", "news", "our team", "team", "learn more", "read more",
             "view all", "see all", "see more", "search jobs", "search", "menu", "back to careers", "back",
             "next", "previous", "current openings"}


def _anchor_title(fragment: str) -> str:
    """The first line of an anchor's cleaned inner text — nested tags (h3 + span for a location, say) become
    separate lines, and the title is normally the first one."""
    text = clean_text(fragment, 300)
    return next((ln.strip() for ln in text.split("\n") if ln.strip()), "")


def _looks_like_job_title(text: str) -> bool:
    t = (text or "").strip().strip("»›→·-:").strip()
    if not (4 <= len(t) <= 140):
        return False
    if t.lower() in _NAV_WORDS:
        return False
    return bool(re.search(r"[A-Za-z]{3,}", t))


def _page_title_guess(page: str) -> str:
    """A job title from the detail page itself, when the listing page's link text wasn't usable."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.I | re.S)
    if m:
        t = clean_text(m.group(1), 200)
        if _looks_like_job_title(t):
            return t
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    if m:
        t = re.split(r"\s*[|–—-]\s*", clean_text(m.group(1), 200))[0].strip()
        if _looks_like_job_title(t):
            return t
    return ""


def _meta_description(page: str) -> str:
    m = (re.search(r'<meta[^>]+name=["\']description["\'][^>]+content="([^"]*)"', page, re.I)
         or re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content="([^"]*)"', page, re.I))
    return clean_text(m.group(1), 1000) if m else ""


def _company_from_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    host = re.sub(r"^(www\.|careers\.|jobs\.)", "", netloc.split(":")[0])  # drop a port, then a common subdomain
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host) or host in ("localhost", ""):
        return ""   # an IP or localhost is not a company name — build_job falls back to "Unknown"
    base = host.split(".")[0]
    return base.replace("-", " ").title() if len(base) > 1 else ""


def fetch_custom_site(site: dict, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """
    Any T&T board/employer. Structured data (schema.org JobPosting) is used when a site publishes it, for full
    quality (real posted/closing dates, salary, description); otherwise the listing page's own link text (or the
    job page's <h1>/<title>) becomes the title — enough to add "any career page" even without structured data.

        trinidad_custom_sites:
          - name: republic          # becomes the job source
            sitemap: https://example.tt/job-sitemap.xml
            url_pattern: "/jobs?/"  # regex a job url must match (default: /job)
            company: Example Ltd    # optional fallback company
          - name: acme
            list_url: https://acme.tt/careers     # or scrape a listing page instead of a sitemap
            url_pattern: "/careers/[a-z0-9-]+"
    """
    if site.get("ats"):
        from src import ats_sources
        return ats_sources.fetch(site, limit)
    name = re.sub(r"[^a-z0-9_]+", "", (site.get("name") or "").lower())
    if not name:
        raise SourceError("custom site needs a name")
    pattern = site.get("url_pattern") or r"/jobs?/"
    fallback = site.get("company") or ""
    if site.get("sitemap"):
        return _sitemap_ld_source(name, site["sitemap"], pattern, limit, fallback_company=fallback)
    if site.get("list_url"):
        list_url = site["list_url"]
        text = fetch(list_url, required=True)
        seen: set[str] = set()
        candidates: list[tuple[str, str]] = []
        for href, inner in _A_TEXT_RE.findall(text or ""):
            if href.lower().startswith(("mailto:", "tel:", "javascript:")):
                continue
            url = urljoin(list_url, href)
            if url in seen or url.split("#")[0] == list_url.split("#")[0] or not re.search(pattern, url):
                continue
            seen.add(url)
            candidates.append((url, _anchor_title(inner)))
        if not candidates:
            raise SourceError(f"{name}: no links matching {pattern!r} on {list_url}")
        candidates = candidates[: limit * 2]

        def one(item: tuple[str, str]):
            url, anchor_text = item
            page = fetch(url)
            ld = jobposting_ld(page) if page else None
            if ld:
                return job_from_ld(ld, source=name, key=slug_from_url(url), url=url, fallback_company=fallback)
            title = anchor_text if _looks_like_job_title(anchor_text) else (_page_title_guess(page) if page else "")
            if not title:
                return None
            return build_job(source=name, key=slug_from_url(url), title=title,
                             company=fallback or _company_from_domain(url), url=url,
                             description=_meta_description(page) if page else "")

        jobs = _pmap(one, candidates)
        _check_layout(name, len(candidates), jobs)
        return jobs[:limit]
    raise SourceError(f"{name}: needs 'sitemap' or 'list_url'")


# ---------------------------------------------------------------------------
# registry + health
# ---------------------------------------------------------------------------

@dataclass
class TTSource:
    name: str
    label: str
    url: str
    fn: Callable[[int], list[dict]]
    kind: str = "board"           # board | recruiter | government | employer
    trust: int = 80
    config_key: str = ""

    def __post_init__(self):
        self.config_key = self.config_key or f"trinidad_{self.name}"


TT_SOURCES: dict[str, TTSource] = {s.name: s for s in [
    TTSource("caribbeanjobs", "CaribbeanJobs", "https://www.caribbeanjobs.com/Trinidad-and-Tobago", fetch_caribbeanjobs, "board", 80),
    TTSource("jobstt", "JobsTT", "https://jobstt.com", fetch_jobstt, "board", 85),
    TTSource("trinidadjob", "TrinidadJob", "https://trinidadjob.com", fetch_trinidadjob, "board", 85),
    TTSource("employtt", "EmployTT (Govt)", "https://employtt.gov.tt", fetch_employtt, "government", 95),
    TTSource("findworktt", "FindWorkTT", "https://www.findworktt.com", fetch_findworktt, "board", 90),
    TTSource("islandjobhunt", "IslandJobHunt", "https://islandjobhunt.com/jobs/in-trinidad-and-tobago", fetch_islandjobhunt, "board", 75),
    TTSource("caribbeanjobsonline", "Caribbean Jobs Online", "https://www.caribbeanjobsonline.com/jobs/trinidad-tobago", fetch_caribbeanjobsonline, "board", 70),
    TTSource("evecaribbean", "Eve Anderson Recruitment", "https://evecaribbean.com/tt/job/", fetch_evecaribbean, "recruiter", 85),
    TTSource("digicel", "Digicel Careers", "https://careers.digicelgroup.com", fetch_digicel, "employer", 100),
]}

# last run outcome per source, in-process (also persisted by run.py -> db.record_source_runs)
HEALTH: dict[str, dict] = {}


def run_source(name: str, fn: Callable[[], list[dict]], label: str = "") -> list[dict]:
    """Run a fetcher, timing it and recording its outcome. Never raises."""
    t0 = time.time()
    rec = {"name": name, "label": label or name, "ok": True, "count": 0, "error": "", "ms": 0,
           "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    rows: list[dict] = []
    try:
        rows = fn() or []
        rec["count"] = len(rows)
    except SourceError as exc:
        rec.update(ok=False, error=str(exc)[:300])
    except Exception as exc:  # noqa: BLE001
        rec.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
    rec["ms"] = int((time.time() - t0) * 1000)
    HEALTH[name] = rec
    level = logging.INFO if rec["ok"] else logging.WARNING
    log.log(level, "  %-20s %3d postings  %5dms  %s", name, rec["count"], rec["ms"], rec["error"])
    return rows


def enabled_sources(profile_sources: dict | None) -> list[TTSource]:
    cfg = profile_sources or {}
    if not cfg.get("trinidad", True):
        return []
    return [s for s in TT_SOURCES.values() if cfg.get(s.config_key, True)]


def custom_sites(cfg: dict) -> list[dict]:
    return [s for s in (cfg.get("trinidad_custom_sites") or []) if isinstance(s, dict) and s.get("name")]


def fetch_all_trinidad(cfg: dict, limit: int | None = None) -> list[dict]:
    """Run every enabled T&T source concurrently. `limit` = newest N per board."""
    limit = int(limit or cfg.get("trinidad_limit_per_source") or DEFAULT_LIMIT)
    tasks: list[tuple[str, str, Callable[[], list[dict]]]] = []
    for s in enabled_sources(cfg.get("sources")):
        tasks.append((s.name, s.label, lambda s=s: s.fn(limit)))
    if (cfg.get("sources") or {}).get("trinidad", True):
        for site in custom_sites(cfg):
            nm = re.sub(r"[^a-z0-9_]+", "", site["name"].lower())
            tasks.append((nm, site.get("label") or site["name"], lambda site=site: fetch_custom_site(site, limit)))
    rows: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(run_source, n, fn, lab) for n, lab, fn in tasks]
        for f in futs:
            rows += f.result()
    return rows
