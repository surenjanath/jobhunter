"""
sheets.py — sync ranked jobs into Google Sheets, non-destructively.

The critical guarantee: columns you edit by hand (Status, Applied Date,
Cover Letter, Follow-up, Notes) are NEVER overwritten by the scraper. The
script owns columns A-M; you own N-R. A job you marked "Applied" three weeks
ago keeps that status forever, even as its score is refreshed.

Auth: a Google Cloud service account. See README for the 10-minute setup.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Columns A-M are machine-owned. N-R are yours.
BOT_HEADERS = [
    "Job ID",
    "First Seen",
    "Fit",
    "Tier",
    "Title",
    "Company",
    "Location",
    "Salary",
    "Source",
    "Posted",
    "Link",
    "Why It Matched",
    "Flags",
    "Also Listed On",
]
USER_HEADERS = [
    "Status",
    "Applied Date",
    "Cover Letter",
    "Follow-up Date",
    "Notes",
]
HEADERS = BOT_HEADERS + USER_HEADERS

BOT_COLS = len(BOT_HEADERS)          # 14
TOTAL_COLS = len(HEADERS)            # 19

STATUS_OPTIONS = [
    "New",
    "Shortlisted",
    "Cover letter drafted",
    "Applied",
    "Screening",
    "Interviewing",
    "Offer",
    "Rejected",
    "Passed on it",
]


def _client() -> gspread.Client:
    """
    Build an authorised gspread client.

    Looks for credentials in this order:
      1. GOOGLE_SERVICE_ACCOUNT_JSON  (raw JSON string — used by GitHub Actions)
      2. GOOGLE_APPLICATION_CREDENTIALS (path to a file — used locally)
      3. ./service_account.json
    """
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        info = json.loads(raw)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No Google credentials found. Set GOOGLE_SERVICE_ACCOUNT_JSON, or put "
            f"a service account key at {path!r}. See README section 2."
        )
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)


def _open_sheet(client: gspread.Client, sheet_id: str, tab: str) -> gspread.Worksheet:
    book = client.open_by_key(sheet_id)
    try:
        ws = book.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=tab, rows=1000, cols=TOTAL_COLS)
        log.info("Created tab %r", tab)
    return ws


def _ensure_headers(ws: gspread.Worksheet) -> None:
    existing = ws.row_values(1)
    if existing[:TOTAL_COLS] == HEADERS:
        return
    ws.update(range_name=f"A1:{chr(64 + TOTAL_COLS)}1", values=[HEADERS])
    ws.format(
        f"A1:{chr(64 + TOTAL_COLS)}1",
        {
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "backgroundColor": {"red": 0.16, "green": 0.22, "blue": 0.34},
            "horizontalAlignment": "LEFT",
        },
    )
    ws.freeze(rows=1)
    log.info("Headers written")


def _apply_formatting(ws: gspread.Worksheet) -> None:
    """Status dropdown + colour scale on Fit. Best-effort; never fatal."""
    try:
        sid = ws.id
        requests = [
            # Status dropdown on column N
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": 1,
                        "startColumnIndex": 14,
                        "endColumnIndex": 15,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": s} for s in STATUS_OPTIONS],
                        },
                        "showCustomUi": True,
                        "strict": False,
                    },
                }
            },
            # Red→green gradient on Fit (column C)
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [
                            {
                                "sheetId": sid,
                                "startRowIndex": 1,
                                "startColumnIndex": 2,
                                "endColumnIndex": 3,
                            }
                        ],
                        "gradientRule": {
                            "minpoint": {
                                "color": {"red": 0.96, "green": 0.80, "blue": 0.80},
                                "type": "NUMBER",
                                "value": "35",
                            },
                            "maxpoint": {
                                "color": {"red": 0.72, "green": 0.88, "blue": 0.75},
                                "type": "NUMBER",
                                "value": "85",
                            },
                        },
                    },
                    "index": 0,
                }
            },
        ]
        ws.spreadsheet.batch_update({"requests": requests})
    except Exception as exc:  # noqa: BLE001
        log.info("Formatting skipped (%s)", repr(exc)[:120])


def sync(jobs: list[dict], sheet_id: str, tab: str = "Jobs") -> dict:
    """
    Upsert jobs into the sheet.

    Returns {"new": int, "updated": int, "total": int}
    """
    client = _client()
    ws = _open_sheet(client, sheet_id, tab)
    _ensure_headers(ws)

    existing = ws.get_all_values()
    body = existing[1:] if len(existing) > 1 else []

    # job_id -> (row_number, user_owned_values)
    index: dict[str, tuple[int, list[str]]] = {}
    for i, row in enumerate(body, start=2):
        if not row or not row[0]:
            continue
        padded = row + [""] * (TOTAL_COLS - len(row))
        index[row[0]] = (i, padded[BOT_COLS:TOTAL_COLS])

    today = date.today().isoformat()
    updates: list[dict] = []
    appends: list[list] = []
    new_count = 0

    for job in jobs:
        jid = job["job_id"]
        link = job.get("url", "")
        # HYPERLINK keeps the cell clickable and the text readable.
        link_cell = (
            f'=HYPERLINK("{link}","Open posting")' if link.startswith("http") else link
        )

        prior = index.get(jid)
        first_seen = today
        if prior:
            row_num, _user_vals = prior
            existing_first_seen = body[row_num - 2][1] if len(body[row_num - 2]) > 1 else ""
            first_seen = existing_first_seen or today

        bot_values = [
            jid,
            first_seen,
            job.get("fit_score", 0),
            job.get("tier", ""),
            job.get("title", "")[:250],
            job.get("company", "")[:120],
            job.get("location", "")[:120],
            job.get("salary", "")[:80],
            job.get("source", ""),
            job.get("posted_at", ""),
            link_cell,
            job.get("why", "")[:450],
            job.get("flags", "")[:450],
            job.get("seen_on", "")[:120],
        ]

        if prior:
            row_num, _ = prior
            # Only columns A-M. N-R are untouched — that's the whole point.
            updates.append(
                {"range": f"A{row_num}:N{row_num}", "values": [bot_values]}
            )
        else:
            appends.append(bot_values + ["New", "", "", "", ""])
            new_count += 1

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        log.info("Refreshed %d existing rows", len(updates))

    if appends:
        appends.sort(key=lambda r: -int(r[2] or 0))
        ws.append_rows(appends, value_input_option="USER_ENTERED")
        log.info("Appended %d new jobs", len(appends))

    _apply_formatting(ws)

    return {"new": new_count, "updated": len(updates), "total": len(jobs)}
