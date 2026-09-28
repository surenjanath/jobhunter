"""
sources_extra.py — more remote boards. Same contract as sources.py: each fetcher returns standard job dicts and never raises.

  weworkremotely   RSS, programming + devops + data + product categories  (location = the posting's "region")
  jobicy           JSON API, worldwide + LatAm feeds
  workingnomads    JSON API, remote jobs with a location string
  getonboard       Latin-America-focused board (English postings only)
  jooble           OPTIONAL — needs JOOBLE_API_KEY (free at jooble.org/api/about); searches Trinidad & Tobago itself

Remote boards state who a job is open to ("USA only", "Anywhere", "LATAM"), which matching.remote_scope reads.
"""

from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET

import requests

from src.sources import HEADERS, TIMEOUT, _get, _iso, safe, strip_html

_ES_WORDS = re.compile(r"\b(?:de|con|para|los|las|experiencia|años|trabajo|equipo|requisitos|empresa)\b", re.I)


def _mostly_spanish(text: str) -> bool:
    sample = (text or "")[:1500]
    return len(_ES_WORDS.findall(sample)) >= 8


@safe
def fetch_weworkremotely() -> list[dict]:
    """WeWorkRemotely RSS (one feed per category)."""
    feeds = ["remote-programming-jobs", "remote-devops-sysadmin-jobs", "remote-back-end-programming-jobs",
             "remote-full-stack-programming-jobs", "remote-product-jobs", "remote-data-jobs"]
    out, seen = [], set()
    for feed in feeds:
        try:
            r = requests.get(f"https://weworkremotely.com/categories/{feed}.rss", headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
        except Exception:  # noqa: BLE001
            continue
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            title_raw = html.unescape(item.findtext("title") or "").strip()
            if not link or link in seen or not title_raw:
                continue
            seen.add(link)
            company, _, title = title_raw.partition(": ")
            if not title:
                company, title = "", title_raw
            region = (item.findtext("region") or "").strip()
            out.append({
                "source": "weworkremotely", "job_id": "weworkremotely:" + re.sub(r"[^a-z0-9]+", "-", link.lower().split("/remote-jobs/")[-1])[:80],
                "title": title, "company": company or "Unknown", "location": region or "Remote", "remote": True, "salary": "",
                "url": link, "description": strip_html(item.findtext("description") or "")[:6000],
                "posted_at": _iso((item.findtext("pubDate") or "")[5:16] and _rfc_date(item.findtext("pubDate"))),
            })
    return out


def _rfc_date(s: str) -> str:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:  # noqa: BLE001
        return ""


@safe
def fetch_jobicy() -> list[dict]:
    """Jobicy — worldwide feed plus LatAm-restricted feed (the useful one for the Caribbean)."""
    out, seen = [], set()
    for geo in ("anywhere", "latam", "usa"):
        data = _get("https://jobicy.com/api/v2/remote-jobs", {"count": 50, "geo": geo})
        for j in (data or {}).get("jobs", []) if isinstance(data, dict) else []:
            jid = str(j.get("id") or "")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            lo, hi, cur = j.get("salaryMin"), j.get("salaryMax"), j.get("salaryCurrency") or "USD"
            per = (j.get("salaryPeriod") or "year").lower()
            salary = f"{cur} {int(lo):,} - {int(hi):,} per {per}" if lo and hi else ""
            out.append({
                "source": "jobicy", "job_id": f"jobicy:{jid}", "title": html.unescape(j.get("jobTitle", "")), "company": html.unescape(j.get("companyName", "")),
                "location": j.get("jobGeo") or "Anywhere", "remote": True, "salary": salary, "url": j.get("url", ""),
                "description": strip_html(j.get("jobDescription") or j.get("jobExcerpt") or "")[:6000], "posted_at": _iso(j.get("pubDate")),
            })
    return out


@safe
def fetch_workingnomads() -> list[dict]:
    """Working Nomads — public JSON export of current remote jobs."""
    data = _get("https://www.workingnomads.com/api/exposed_jobs/")
    out = []
    for j in data if isinstance(data, list) else []:
        url = j.get("url") or ""
        m = re.search(r"/job/go/(\d+)", url)
        if not m:
            continue
        out.append({
            "source": "workingnomads", "job_id": f"workingnomads:{m.group(1)}", "title": html.unescape(j.get("title", "")),
            "company": html.unescape(j.get("company_name", "")), "location": j.get("location") or "Remote", "remote": True, "salary": "",
            "url": url, "description": strip_html(j.get("description", ""))[:6000], "posted_at": _iso(j.get("pub_date")),
        })
    return out


@safe
def fetch_getonboard() -> list[dict]:
    """Get on Board — Latin America tech jobs. Spanish-language postings are skipped."""
    out, seen = [], set()
    for cat in ("programming", "data-science-analytics", "sysadmin-devops-qa", "machine-learning-ai"):
        data = _get(f"https://www.getonbrd.com/api/v0/categories/{cat}/jobs", {"per_page": 50, "expand": '["company"]'})
        for it in (data or {}).get("data", []) if isinstance(data, dict) else []:
            if it.get("id") in seen:          # the same job is listed under several categories
                continue
            seen.add(it.get("id"))
            a = it.get("attributes") or {}
            desc = strip_html((a.get("description") or "") + " " + (a.get("projects") or "") + " " + (a.get("functions") or ""))
            if _mostly_spanish(desc) or not a.get("title"):
                continue
            comp = ((a.get("company") or {}).get("data") or {}).get("attributes", {}).get("name") or ""
            countries = a.get("countries") or []
            modality = str(a.get("remote_modality") or "")
            lo, hi = a.get("min_salary"), a.get("max_salary")
            out.append({
                "source": "getonboard", "job_id": f"getonboard:{it.get('id')}", "title": a["title"], "company": comp or "Unknown",
                "location": ", ".join(countries) if countries else "Latin America", "remote": "remote" in modality or bool(a.get("remote")), "salary": f"US${lo:,} - US${hi:,} per month" if lo and hi else "",
                "url": (it.get("links") or {}).get("public_url") or f"https://www.getonbrd.com/jobs/{it.get('id')}", "description": desc[:6000],
                "posted_at": _iso(a.get("published_at")),
            })
    return out


@safe
def fetch_jooble() -> list[dict]:
    """Jooble — optional. Set JOOBLE_API_KEY. Searches Trinidad & Tobago directly (local roles)."""
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        return []
    out = []
    for page in (1, 2, 3):
        try:
            r = requests.post(f"https://jooble.org/api/{key}", json={"keywords": "", "location": "Trinidad and Tobago", "page": page},
                              headers=HEADERS, timeout=TIMEOUT)
            jobs = r.json().get("jobs", []) if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            jobs = []
        if not jobs:
            break
        for j in jobs:
            jid = str(j.get("id") or j.get("link") or "")
            if not jid:
                continue
            out.append({
                "source": "jooble", "job_id": f"jooble:{re.sub(r'[^a-z0-9]+', '-', jid.lower())[-60:]}", "title": html.unescape(j.get("title", "")),
                "company": html.unescape(j.get("company", "")) or "Unknown", "location": j.get("location") or "Trinidad & Tobago", "remote": False,
                "salary": j.get("salary") or "", "url": j.get("link", ""), "description": strip_html(j.get("snippet", ""))[:6000], "posted_at": _iso(j.get("updated")),
            })
    return out


EXTRA_SOURCES = {
    "weworkremotely": fetch_weworkremotely,
    "jobicy": fetch_jobicy,
    "workingnomads": fetch_workingnomads,
    "getonboard": fetch_getonboard,
    "jooble": fetch_jooble,
}
