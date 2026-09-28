"""
sources.py — fetchers for each job board.

Every fetcher returns a list of dicts with this shape:

    {
      "source":       str,   # which board it came from
      "job_id":       str,   # stable-ish id from the source
      "title":        str,
      "company":      str,
      "location":     str,
      "remote":       bool,
      "salary":       str,   # "" if not disclosed
      "url":          str,   # DIRECT apply/posting link
      "description":  str,   # plain-ish text, used for scoring
      "posted_at":    str,   # ISO date, "" if unknown
    }

Design notes
------------
* Every fetcher is wrapped so one dead board never kills the run.
* All parsing is defensive: boards change their JSON shape without notice.
* No API keys required for any source here.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
TIMEOUT = 30


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def strip_html(raw: str | None) -> str:
    """
    Turn an HTML blob into something scoreable. Not pretty, just useful.

    Order matters. Greenhouse double-encodes its content (`&lt;p&gt;`), so if
    you strip tags before unescaping you end up *creating* real tags from the
    entities and leaving them in the output. Unescape first, strip, then
    unescape again for any remaining `&amp;` style entities.
    """
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)  # catches tags revealed by the second pass
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _get(url: str, params: dict | None = None, retries: int = 2) -> Any:
    """GET returning parsed JSON, with a couple of polite retries."""
    last = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 404:
                log.info("404 (board likely retired): %s", url)
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - we genuinely want everything
            last = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    log.warning("giving up on %s (%s)", url, repr(last)[:160])
    return None


def _iso(value: Any) -> str:
    """Best-effort normalise assorted date formats to an ISO date string."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        ts = float(value)
        # Lever (and some others) return epoch MILLISECONDS. Anything past
        # ~1973 in seconds terms is really milliseconds; without this the
        # conversion overflows and the date is silently lost.
        if ts > 1e11:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    # Common shapes: 2026-08-01, 2026-08-01T12:00:00Z, 2026-08-01T12:00:00+00:00
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.replace("Z", "+0000"), fmt).date().isoformat()
        except ValueError:
            continue
    return text[:10] if len(text) >= 10 else ""


def _looks_remote(*fields: str) -> bool:
    blob = " ".join(f.lower() for f in fields if f)
    return any(w in blob for w in ("remote", "anywhere", "distributed", "work from home"))


def safe(fn: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    """Decorator: a failing source logs and returns [] instead of exploding."""

    def wrapper(*args, **kwargs) -> list[dict]:
        name = fn.__name__.replace("fetch_", "")
        try:
            rows = fn(*args, **kwargs) or []
            log.info("  %-16s %3d postings", name, len(rows))
            return rows
        except Exception as exc:  # noqa: BLE001
            log.warning("  %-16s FAILED: %s", name, repr(exc)[:200])
            return []

    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# aggregator boards
# ---------------------------------------------------------------------------

@safe
def fetch_remotive(search_terms: Iterable[str]) -> list[dict]:
    """Remotive — curated remote jobs. Free JSON API, no key."""
    out: list[dict] = []
    seen: set[str] = set()
    for term in search_terms:
        data = _get("https://remotive.com/api/remote-jobs", {"search": term, "limit": 60})
        if not data:
            continue
        for j in (data.get("jobs") or []):
            jid = str(j.get("id", ""))
            if not jid or jid in seen:
                continue
            seen.add(jid)
            out.append(
                {
                    "source": "remotive",
                    "job_id": f"remotive:{jid}",
                    "title": j.get("title", ""),
                    "company": j.get("company_name", ""),
                    "location": j.get("candidate_required_location", "") or "Remote",
                    "remote": True,
                    "salary": j.get("salary", "") or "",
                    "url": j.get("url", ""),
                    "description": strip_html(j.get("description", "")),
                    "posted_at": _iso(j.get("publication_date")),
                }
            )
        time.sleep(0.6)  # be a good citizen
    return out


@safe
def fetch_remoteok() -> list[dict]:
    """RemoteOK — single endpoint returning everything. First row is metadata."""
    data = _get("https://remoteok.com/api")
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue  # skips the legal/metadata header row
        jid = str(j.get("id") or j.get("slug") or "")
        if not jid:
            continue
        salary = ""
        lo, hi = j.get("salary_min"), j.get("salary_max")
        if lo and hi:
            salary = f"${int(lo):,} - ${int(hi):,}"
        out.append(
            {
                "source": "remoteok",
                "job_id": f"remoteok:{jid}",
                "title": j.get("position", ""),
                "company": j.get("company", ""),
                "location": j.get("location", "") or "Remote",
                "remote": True,
                "salary": salary,
                "url": j.get("url") or f"https://remoteok.com/l/{jid}",
                "description": strip_html(j.get("description", ""))
                + " "
                + " ".join(j.get("tags", []) or []),
                "posted_at": _iso(j.get("date")),
            }
        )
    return out


@safe
def fetch_arbeitnow() -> list[dict]:
    """Arbeitnow — EU-heavy but flags visa sponsorship, which matters for you."""
    out = []
    for page in (1, 2, 3):
        data = _get("https://www.arbeitnow.com/api/job-board-api", {"page": page})
        if not data or not data.get("data"):
            break
        for j in (data.get("data") or []):
            slug = j.get("slug", "")
            if not slug:
                continue
            tags = " ".join(j.get("tags", []) or []) + " " + " ".join(j.get("job_types", []) or [])
            desc = strip_html(j.get("description", ""))
            if j.get("visa_sponsorship"):
                desc += " visa sponsorship available"
            out.append(
                {
                    "source": "arbeitnow",
                    "job_id": f"arbeitnow:{slug}",
                    "title": j.get("title", ""),
                    "company": j.get("company_name", ""),
                    "location": j.get("location", ""),
                    "remote": bool(j.get("remote")),
                    "salary": "",
                    "url": j.get("url", ""),
                    "description": f"{desc} {tags}",
                    "posted_at": _iso(j.get("created_at")),
                }
            )
        time.sleep(0.6)
    return out


@safe
def fetch_himalayas() -> list[dict]:
    """Himalayas — remote-first board with a generous public API."""
    data = _get("https://himalayas.app/jobs/api", {"limit": 100})
    if not data:
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else data
    out = []
    for j in jobs or []:
        jid = str(j.get("guid") or j.get("id") or j.get("slug") or "")
        if not jid:
            continue
        locs = j.get("locationRestrictions") or j.get("locations") or []
        if isinstance(locs, str):
            locs = [locs]
        out.append(
            {
                "source": "himalayas",
                "job_id": f"himalayas:{jid}",
                "title": j.get("title", ""),
                "company": j.get("companyName") or j.get("company", ""),
                "location": ", ".join(str(x) for x in locs) or "Remote",
                "remote": True,
                "salary": str(j.get("salary") or ""),
                "url": j.get("applicationLink") or j.get("url", ""),
                "description": strip_html(j.get("description", "")),
                "posted_at": _iso(j.get("pubDate") or j.get("publishedDate")),
            }
        )
    return out


@safe
def fetch_hn_whoishiring() -> list[dict]:
    """
    Hacker News 'Who is hiring?' — the best source for small companies that
    will actually hire an international contractor.

    IMPORTANT: use `search_by_date`, not `search`. The plain `/search` endpoint
    ranks by relevance, and verified against the live API it returns the
    *March 2020* thread first. Filtering on the `author_whoishiring` tag and
    sorting by date is the only way to reliably get the current month.
    """
    search = _get(
        "https://hn.algolia.com/api/v1/search_by_date",
        {
            "tags": "story,author_whoishiring",
            "query": "hiring",
            "restrictSearchableAttributes": "title",
            "hitsPerPage": 5,
        },
    )
    if not search or not search.get("hits"):
        return []

    story_id = None
    for hit in search["hits"]:
        title = (hit.get("title") or "").lower()
        # "Who wants to be hired?" is the candidates thread, not the jobs one.
        if "who is hiring" in title and "wants to be hired" not in title:
            story_id = hit.get("objectID")
            log.info("  HN thread: %s", hit.get("title"))
            break
    if not story_id:
        return []

    thread = _get(f"https://hn.algolia.com/api/v1/items/{story_id}")
    if not thread:
        return []

    out = []
    for child in thread.get("children", []) or []:
        text = strip_html(child.get("text") or "")
        if len(text) < 60:
            continue
        # HN convention: "Company | Role | Location | REMOTE | stack"
        headline = text.split("\n")[0][:200]
        parts = [p.strip() for p in headline.split("|")]
        company = parts[0][:80] if parts else "Unknown"
        title_guess = parts[1][:120] if len(parts) > 1 else "See posting"
        location = parts[2][:80] if len(parts) > 2 else ""
        out.append(
            {
                "source": "hn_whoishiring",
                "job_id": f"hn:{child.get('id')}",
                "title": title_guess,
                "company": company,
                "location": location,
                "remote": _looks_remote(text),
                "salary": "",
                "url": f"https://news.ycombinator.com/item?id={child.get('id')}",
                "description": text[:6000],
                "posted_at": _iso(child.get("created_at")),
            }
        )
    return out


# ---------------------------------------------------------------------------
# company ATS boards — highest signal, direct apply links
# ---------------------------------------------------------------------------

def _title_is_relevant(title: str, cfg_targets: dict) -> bool:
    """Cheap pre-filter so we only pay for descriptions we might actually want."""
    t = title.lower()
    for tier in ("tier_1", "tier_2"):
        for target in cfg_targets.get(tier, []):
            if target.lower() in t:
                return True
    return any(
        w in t
        for w in (
            "engineer", "developer", "python", "django", "backend", "data",
            "solutions", "automation", "ai", "llm", "platform", "software",
        )
    )


@safe
def fetch_greenhouse(tokens: Iterable[str], targets: dict | None = None,
                     max_details_per_board: int = 25) -> list[dict]:
    """
    Greenhouse, in two phases.

    Verified against the live API (Aug 2026): the board LIST endpoint does NOT
    return job descriptions, even with `content=true`. It returns only
    absolute_url, location, id, updated_at, requisition_id, title,
    company_name and first_published. Scoring on title alone is close to
    useless, so we pre-filter titles and then fetch `content` per job from
    /jobs/{id}, capped so we stay polite.
    """
    targets = targets or {}
    out = []
    for token in tokens:
        data = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
        if not data:
            continue

        listings = data.get("jobs") or []
        candidates = [j for j in listings if _title_is_relevant(j.get("title", ""), targets)]
        log.info(
            "  greenhouse:%-14s %3d listed, %3d title-relevant",
            token, len(listings), len(candidates),
        )

        for j in candidates[:max_details_per_board]:
            jid = j.get("id")
            loc = (j.get("location") or {}).get("name", "")
            detail = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}")
            # Greenhouse triple-encodes content (&lt; -> &lt; -> <);
            # strip_html unescapes twice, which handles it.
            content = strip_html((detail or {}).get("content", ""))

            meta = " ".join(
                f"{m.get('name','')} {m.get('value','')}"
                for m in (j.get("metadata") or [])
                if isinstance(m, dict) and m.get("value")
            )
            out.append(
                {
                    "source": f"greenhouse:{token}",
                    "job_id": f"gh:{token}:{jid}",
                    "title": j.get("title", "").strip(),
                    "company": j.get("company_name") or token,
                    "location": loc,
                    "remote": _looks_remote(loc, meta, j.get("title", "")),
                    "salary": "",
                    "url": j.get("absolute_url", ""),
                    "description": f"{content} {meta}".strip(),
                    "posted_at": _iso(j.get("updated_at") or j.get("first_published")),
                }
            )
            time.sleep(0.25)
        time.sleep(0.4)
    return out


@safe
def fetch_lever(tokens: Iterable[str]) -> list[dict]:
    out = []
    for token in tokens:
        data = _get(f"https://api.lever.co/v0/postings/{token}", {"mode": "json"})
        if not isinstance(data, list):
            continue
        for j in data:
            cats = j.get("categories") or {}
            loc = cats.get("location", "") or ""
            out.append(
                {
                    "source": f"lever:{token}",
                    "job_id": f"lever:{token}:{j.get('id')}",
                    "title": j.get("text", ""),
                    "company": token,
                    "location": loc,
                    "remote": _looks_remote(loc, cats.get("commitment", "")),
                    "salary": "",
                    "url": j.get("hostedUrl", ""),
                    # Lever splits requirements into `lists`, where the real
                    # text lives under `content` (HTML), not `text` (the
                    # heading). Reading only `text` loses the requirements.
                    "description": strip_html(
                        (j.get("descriptionPlain") or j.get("description") or "")
                        + " "
                        + " ".join(
                            f"{s.get('text', '')} {s.get('content', '')}"
                            for s in (j.get("lists") or [])
                        )
                    ),
                    "posted_at": _iso(j.get("createdAt")),
                }
            )
        time.sleep(0.4)
    return out


@safe
def fetch_ashby(tokens: Iterable[str]) -> list[dict]:
    out = []
    for token in tokens:
        data = _get(
            f"https://api.ashbyhq.com/posting-api/job-board/{token}",
            {"includeCompensation": "true"},
        )
        if not data:
            continue
        for j in data.get("jobs", []) or []:
            comp = j.get("compensation") or {}
            summary = comp.get("compensationTierSummary") or "" if isinstance(comp, dict) else ""
            out.append(
                {
                    "source": f"ashby:{token}",
                    "job_id": f"ashby:{token}:{j.get('id')}",
                    "title": j.get("title", ""),
                    "company": j.get("organizationName") or token,
                    "location": j.get("location", "") or "",
                    "remote": bool(j.get("isRemote")),
                    "salary": summary,
                    "url": j.get("jobUrl") or j.get("applyUrl", ""),
                    "description": strip_html(j.get("descriptionHtml") or j.get("descriptionPlain", "")),
                    "posted_at": _iso(j.get("publishedAt")),
                }
            )
        time.sleep(0.4)
    return out


# ---------------------------------------------------------------------------

def fetch_all(cfg: dict) -> list[dict]:
    """Run every enabled source and return the combined, un-deduped list."""
    import concurrent.futures as _cf
    import os as _os

    enabled = cfg.get("sources", {})
    boards = cfg.get("company_boards", {})
    terms = cfg.get("search_terms", [])

    rows: list[dict] = []
    log.info("Fetching from enabled sources:")

    # Parallelize the fast aggregator boards — 5 I/O-bound fetches that
    # were previously sequential (8s+) now run concurrently (~3s).
    # ATS boards (greenhouse/lever/ashby) stay sequential to stay polite
    # and avoid hammering the same domains.
    parallel = _os.environ.get("JOBHUNT_PARALLEL", "1") != "0"
    agg_tasks: list[tuple[str, callable]] = []
    if enabled.get("remotive"):
        agg_tasks.append(("remotive", lambda: fetch_remotive(terms)))
    if enabled.get("remoteok"):
        agg_tasks.append(("remoteok", fetch_remoteok))
    if enabled.get("arbeitnow"):
        agg_tasks.append(("arbeitnow", fetch_arbeitnow))
    if enabled.get("himalayas"):
        agg_tasks.append(("himalayas", fetch_himalayas))
    from src import sources_extra as _x
    for _name, _fn in _x.EXTRA_SOURCES.items():          # weworkremotely, jobicy, workingnomads, getonboard, jooble
        if enabled.get(_name):
            agg_tasks.append((_name, _fn))
    if enabled.get("hn_whoishiring"):
        agg_tasks.append(("hn_whoishiring", fetch_hn_whoishiring))

    if agg_tasks and parallel:
        with _cf.ThreadPoolExecutor(max_workers=6) as ex:
            fut_map = {ex.submit(fn): name for name, fn in agg_tasks}
            for fut in _cf.as_completed(fut_map):
                try:
                    rows += fut.result() or []
                except Exception as exc:  # noqa: BLE001
                    log.warning("  %-16s FAILED (parallel): %s", fut_map[fut], repr(exc)[:200])
    else:
        for name, fn in agg_tasks:
            rows += fn()

    if enabled.get("greenhouse"):
        rows += fetch_greenhouse(
            boards.get("greenhouse", []),
            cfg.get("targets", {}),
            cfg.get("max_greenhouse_details_per_board", 25),
        )
    if enabled.get("lever"):
        rows += fetch_lever(boards.get("lever", []))
    if enabled.get("ashby"):
        rows += fetch_ashby(boards.get("ashby", []))

    # Trinidad & Tobago local boards — see trinidad.py (registry, health tracking, custom sites)
    if enabled.get("trinidad", True):
        try:
            from src import trinidad as _tt
            rows += _tt.fetch_all_trinidad(cfg)
        except ImportError:
            log.info("  trinidad fetchers not available (trinidad.py missing)")
        except Exception as exc:  # noqa: BLE001
            log.warning("  trinidad fetch failed: %s", repr(exc)[:200])

    log.info("Total fetched (pre-dedupe): %d", len(rows))
    return rows
