"""
job_import.py — add a job you found yourself (LinkedIn, Indeed, a friend's link, a company site) to the ledger.

Three ways in, all ending in the same scoring as scanned jobs (score.score_job → the full matcher):
  * a link: the page's schema.org JobPosting data is read (most career sites and job boards publish it)
  * the "Save to JobHunter" browser button: sends the page's JobPosting data (or the text you selected) from YOUR
    browser, so pages behind a login (LinkedIn) work without the server ever fetching them
  * pasted text: title, company and the description, typed or pasted by hand

The server only ever fetches public http(s) addresses: never localhost or private networks (so a link can't be used
to probe your machine or network).
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from datetime import date
from urllib.parse import urlparse

from src import trinidad, tt_geo

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def _public_url(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
        return True
    except (ValueError, socket.gaierror, UnicodeError):
        return False


def _from_ld(ld: dict, url: str) -> dict:
    return {"title": trinidad.clean_text(ld.get("title") or ld.get("name"), 300),
            "company": trinidad.ld_company(ld),
            "location": trinidad.ld_location(ld) or ("Remote" if str(ld.get("jobLocationType", "")).upper() == "TELECOMMUTE" else ""),
            "description": trinidad.clean_text(ld.get("description"), 20000),
            "salary": trinidad.ld_salary(ld),
            "posted_at": str(ld.get("datePosted") or "")[:10],
            "expires_at": str(ld.get("validThrough") or "")[:10],
            "url": url}


def parse_page(html: str, url: str) -> dict:
    """What a job page says about itself: JobPosting JSON-LD if present, else its title and meta description."""
    ld = trinidad.jobposting_ld(html)
    if ld:
        return _from_ld(ld, url)
    title = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', html or "", re.I)
    return {"title": trinidad.clean_text(title.group(1) if title else "", 300), "company": "", "location": "",
            "description": trinidad.clean_text(desc.group(1) if desc else "", 20000), "url": url, "partial": True}


def fetch(url: str, timeout: int = 15) -> dict:
    """Fetch a public job page and read it. -> fields, or {"error": …} with what to do instead."""
    if not _public_url(url):
        return {"error": "That isn't a public web address."}
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return {"error": f"Couldn't open the page ({type(exc).__name__}). Paste the description instead, or use the Save to JobHunter button."}
    if r.status_code >= 400:
        return {"error": f"The site answered {r.status_code} (often a login wall). Use the Save to JobHunter button on that page, or paste the description."}
    if not _public_url(r.url):   # a redirect must not land on a private address either
        return {"error": "That link redirects somewhere private."}
    out = parse_page(r.text, r.url)
    if not out.get("title") or (out.get("partial") and len(out.get("description") or "") < 200):
        out["warning"] = "This page doesn't publish full job details. Check the title and company, and paste the description."
    return out


def from_ld_json(ld_text: str, url: str) -> dict | None:
    """The browser button sends the page's JSON-LD blocks; use the JobPosting among them."""
    try:
        data = json.loads(ld_text)
    except (TypeError, ValueError):
        return None
    ld = trinidad.jobposting_ld(f'<script type="application/ld+json">{json.dumps(data)}</script>')
    return _from_ld(ld, url) if ld else None


def build_job(fields: dict) -> dict:
    """A job dict shaped like the scanners' output, ready for score.score_job()."""
    title = (fields.get("title") or "").strip()[:300]
    company = (fields.get("company") or "").strip()[:150]
    url = (fields.get("url") or "").strip()
    desc = trinidad.clean_text(fields.get("description") or "", 20000)
    loc = (fields.get("location") or "").strip()[:150]
    key = url or f"{title}|{company}".lower()
    region = tt_geo.normalize_region(loc, desc[:400]) if tt_geo.is_trinidad(loc, desc[:400]) else ""
    return {"job_id": "manual:" + hashlib.sha1(key.encode()).hexdigest()[:16], "source": "manual", "title": title, "company": company,
            "location": loc or ("Remote" if re.search(r"\bremote\b", desc, re.I) else ""),
            "remote": bool(re.search(r"\bremote\b", f"{loc} {title}", re.I)), "salary": (fields.get("salary") or "")[:120],
            "url": url, "description": desc, "posted_at": (fields.get("posted_at") or date.today().isoformat())[:10],
            "expires_at": (fields.get("expires_at") or "")[:10], "seen_on": "added by you", "region": region,
            "category": tt_geo.classify_category(title, desc) if region else ""}
