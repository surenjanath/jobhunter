"""
ats_sources.py — read any employer's jobs straight from the applicant-tracking system they use, filtered to Trinidad & Tobago.

Most employers publish jobs through one of a handful of ATS products, each with a public JSON API:

    greenhouse · lever · ashby · smartrecruiters · workable · recruitee · workday

`detect(url)` looks at an employer's careers page and works out which system (and which board id) it uses, so adding an
employer is: paste the careers URL → Detect → Add. A custom site entry then looks like

    - {name: scotia, ats: workday, tenant: scotiabank, wd: 3, site: scotiabank_external, label: Scotiabank}
    - {name: acme,   ats: greenhouse, slug: acmeco}

Jobs are kept when their location mentions Trinidad & Tobago (or `all_locations: true`). Everything is normalised by
trinidad.build_job, so region / category / expiry work exactly as for the built-in boards.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

from src import trinidad as tt
from src.trinidad import SourceError, build_job, clean_text

log = logging.getLogger(__name__)

TT_LOCATION = re.compile(r"trinidad|tobago|port[- ]of[- ]spain|chaguanas|san fernando|couva|point lisas|arima|\bT&T\b|\bTTO?\b|st\.? augustine|"
                         r"diego martin|san juan|tunapuna|sangre grande|point fortin|marabella|piarco|trincity", re.I)
KINDS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "workday")


def _http(method: str, url: str, json_body=None):
    """JSON request through trinidad's retrying session. Returns parsed JSON or None."""
    try:
        r = tt._session.request(method, url, json=json_body, headers={**tt.HTML_HEADERS, "Accept": "application/json"}, timeout=tt.TIMEOUT)
        if r.status_code == 200:
            return r.json()
        log.info("  ats %s %s -> HTTP %s", method, url, r.status_code)
    except Exception as exc:  # noqa: BLE001
        log.info("  ats %s %s failed: %r", method, url, exc)
    return None


def _job(site, keep, *, location="", **kw):
    """build_job, marking the job local only if its location is in Trinidad & Tobago (matters when all_locations is on)."""
    return build_job(location=location, local=bool(TT_LOCATION.search(location or "")) or not site.get("all_locations"), **kw)


def _ms(v) -> str:
    try:
        return datetime.fromtimestamp(float(v) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _relative(text: str) -> str:
    """Workday: 'Posted 3 Days Ago' / 'Posted Today' -> ISO date."""
    return tt._relative_date((text or "").replace("Posted", "").replace("Ago", "ago").strip())


# ---------------------------------------------------------------------------
# one function per ATS: (site config) -> [normalised job dicts]
# ---------------------------------------------------------------------------

def _greenhouse(site, keep):
    d = _http("GET", f"https://boards-api.greenhouse.io/v1/boards/{site['slug']}/jobs?content=true")
    if d is None:
        raise SourceError(f"greenhouse board {site['slug']!r} not found")
    out = []
    for j in d.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        if keep(loc):
            out.append(_job(site, keep, source=site["name"], key=str(j["id"]), title=j.get("title", ""), company=site.get("label") or site["name"],
                                 url=j.get("absolute_url", ""), location=loc, description=j.get("content", ""),
                                 posted_at=j.get("first_published") or j.get("updated_at") or ""))
    return out


def _lever(site, keep):
    d = _http("GET", f"https://api.lever.co/v0/postings/{site['slug']}?mode=json")
    if d is None:
        raise SourceError(f"lever company {site['slug']!r} not found")
    out = []
    for j in d if isinstance(d, list) else []:
        cat = j.get("categories") or {}
        loc = ", ".join(x for x in [cat.get("location"), *(cat.get("allLocations") or [])] if x)
        if keep(loc):
            out.append(_job(site, keep, source=site["name"], key=j["id"], title=j.get("text", ""), company=site.get("label") or site["name"],
                                 url=j.get("hostedUrl", ""), location=loc, description=j.get("descriptionPlain") or j.get("description", ""),
                                 posted_at=_ms(j.get("createdAt")), remote=(j.get("workplaceType") == "remote") or None))
    return out


def _ashby(site, keep):
    d = _http("GET", f"https://api.ashbyhq.com/posting-api/job-board/{site['slug']}?includeCompensation=true")
    if d is None:
        raise SourceError(f"ashby board {site['slug']!r} not found")
    out = []
    for j in d.get("jobs", []):
        loc = ", ".join(x for x in [j.get("location"), (((j.get("address") or {}).get("postalAddress")) or {}).get("addressCountry")] if x)
        if keep(loc):
            comp = ((j.get("compensation") or {}).get("compensationTierSummary")) or ""
            out.append(_job(site, keep, source=site["name"], key=j["id"], title=j.get("title", ""), company=site.get("label") or site["name"],
                                 url=j.get("jobUrl", ""), location=loc, description=j.get("descriptionHtml") or j.get("descriptionPlain", ""),
                                 posted_at=j.get("publishedAt", ""), salary=comp, remote=j.get("isRemote")))
    return out


def _smartrecruiters(site, keep):
    d = _http("GET", f"https://api.smartrecruiters.com/v1/companies/{site['slug']}/postings?limit=100")
    if d is None:
        raise SourceError(f"smartrecruiters company {site['slug']!r} not found")
    out = []
    for j in d.get("content", []):
        l = j.get("location") or {}
        loc = ", ".join(x for x in [l.get("city"), l.get("region"), l.get("country")] if x)
        if not keep(loc + " " + str(l.get("country", ""))):
            continue
        detail = _http("GET", j.get("ref") or f"https://api.smartrecruiters.com/v1/companies/{site['slug']}/postings/{j['id']}") or {}
        secs = ((detail.get("jobAd") or {}).get("sections")) or {}
        desc = "\n".join(clean_text((secs.get(k) or {}).get("text", "")) for k in ("jobDescription", "qualifications", "additionalInformation"))
        out.append(_job(site, keep, source=site["name"], key=j["id"], title=j.get("name", ""), company=(j.get("company") or {}).get("name") or site.get("label") or site["name"],
                             url=detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{site['slug']}/{j['id']}", location=loc, description=desc,
                             posted_at=j.get("releasedDate", ""), remote=bool(l.get("remote")) or None))
    return out


def _workable(site, keep):
    d = _http("POST", f"https://apply.workable.com/api/v3/accounts/{site['slug']}/jobs", {"query": "", "location": [], "department": [], "worktype": [], "remote": []})
    if d is None:
        raise SourceError(f"workable account {site['slug']!r} not found")
    out = []
    for j in d.get("results", []):
        l = j.get("location") or {}
        loc = ", ".join(x for x in [l.get("city"), l.get("region"), l.get("country")] if x)
        if keep(loc):
            det = _http("GET", f"https://apply.workable.com/api/v2/accounts/{site['slug']}/jobs/{j['shortcode']}") or {}
            out.append(_job(site, keep, source=site["name"], key=j["shortcode"], title=j.get("title", ""), company=site.get("label") or site["name"],
                                 url=f"https://apply.workable.com/{site['slug']}/j/{j['shortcode']}/", location=loc,
                                 description=(det.get("description") or "") + "\n" + (det.get("requirements") or ""), posted_at=j.get("published", ""),
                                 remote=bool(j.get("remote")) or None))
    return out


def _recruitee(site, keep):
    d = _http("GET", f"https://{site['slug']}.recruitee.com/api/offers/")
    if d is None:
        raise SourceError(f"recruitee company {site['slug']!r} not found")
    out = []
    for j in d.get("offers", []):
        loc = ", ".join(x for x in [j.get("city"), j.get("country")] if x) or j.get("location", "")
        if keep(loc):
            out.append(_job(site, keep, source=site["name"], key=str(j["id"]), title=j.get("title", ""), company=j.get("company_name") or site.get("label") or site["name"],
                                 url=j.get("careers_url", ""), location=loc, description=(j.get("description") or "") + "\n" + (j.get("requirements") or ""),
                                 posted_at=j.get("created_at", ""), remote=bool(j.get("remote")) or None))
    return out


def _workday(site, keep):
    base = f"https://{site['tenant']}.wd{site.get('wd', 1)}.myworkdayjobs.com/wday/cxs/{site['tenant']}/{site['site']}"
    out, offset = [], 0
    while offset < 200:
        d = _http("POST", f"{base}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": site.get("search", "Trinidad")})
        if d is None:
            if offset == 0:
                raise SourceError(f"workday tenant {site['tenant']!r}/{site['site']!r} not found")
            break
        posts = d.get("jobPostings") or []
        for j in posts:
            loc = j.get("locationsText", "")
            if not keep(loc + " " + " ".join(j.get("bulletFields") or [])):
                continue
            det = (_http("GET", f"{base}{j['externalPath']}") or {}).get("jobPostingInfo", {})
            out.append(_job(site, keep, source=site["name"], key=re.sub(r"[^A-Za-z0-9]+", "-", j["externalPath"]).strip("-")[-60:], title=j.get("title", ""),
                                 company=site.get("label") or site["name"], url=det.get("externalUrl") or f"https://{site['tenant']}.wd{site.get('wd', 1)}.myworkdayjobs.com/{site['site']}{j['externalPath']}",
                                 location=det.get("location") or loc, description=det.get("jobDescription", ""), posted_at=det.get("startDate") or _relative(j.get("postedOn", "")),
                                 expires_at=""))
        if len(posts) < 20:
            break
        offset += 20
    return out


_FETCHERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby, "smartrecruiters": _smartrecruiters,
             "workable": _workable, "recruitee": _recruitee, "workday": _workday}


def fetch(site: dict, limit: int = tt.DEFAULT_LIMIT) -> list[dict]:
    """Jobs for one custom-site entry that has `ats:`. Raises SourceError when the board can't be read."""
    kind = (site.get("ats") or "").lower()
    if kind not in _FETCHERS:
        raise SourceError(f"unknown ats {kind!r}; use one of {', '.join(KINDS)}")
    need = {"workday": ("tenant", "site")}.get(kind, ("slug",))
    for k in need:
        if not site.get(k):
            raise SourceError(f"{kind} needs {k}")
    name = re.sub(r"[^a-z0-9_]+", "", (site.get("name") or "").lower())
    if not name:
        raise SourceError("custom site needs a name")
    site = {**site, "name": name}
    keep = (lambda loc: True) if site.get("all_locations") else (lambda loc: bool(TT_LOCATION.search(loc or "")))
    jobs = [j for j in _FETCHERS[kind](site, keep) if j]
    return jobs[:limit]


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

_DETECT = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)|boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I)),
    ("recruitee", re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I)),
]
_WORKDAY = re.compile(r"([a-z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I)
_SKIP = {"embed", "www", "api", "jobs", "careers", "v1", "boards"}


def detect(url: str) -> list[dict]:
    """Which ATS does this careers page use? Returns candidate site entries (without a name)."""
    if not re.match(r"^https?://", url or ""):
        url = "https://" + (url or "")
    pages = [url]
    root = re.match(r"^(https?://[^/]+)", url)
    if root:
        pages += [root.group(1) + p for p in ("/careers", "/jobs", "/careers/", "/about/careers")]
    seen, out = set(), []
    for p in dict.fromkeys(pages):
        text = p + "\n" + (tt.fetch(p) or "")      # the URL itself often names the ATS (e.g. …myworkdayjobs.com/site)
        for kind, rx in _DETECT:
            for m in rx.finditer(text):
                slug = next((g for g in m.groups() if g), "")
                if slug and slug.lower() not in _SKIP and (kind, slug.lower()) not in seen:
                    seen.add((kind, slug.lower()))
                    out.append({"ats": kind, "slug": slug})
        for m in _WORKDAY.finditer(text):
            key = ("workday", m.group(1).lower())
            if key not in seen:
                seen.add(key)
                out.append({"ats": "workday", "tenant": m.group(1), "wd": int(m.group(2)), "site": m.group(3)})
        if re.search(r'"@type"\s*:\s*"JobPosting"', text) and ("jsonld", p) not in seen:
            seen.add(("jsonld", p))
            out.append({"ats": "", "note": "This page publishes schema.org JobPosting data — add it as a sitemap/list site instead.", "list_url": p})
        if out:
            break
    return out
