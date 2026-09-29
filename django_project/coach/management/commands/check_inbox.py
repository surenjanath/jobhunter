"""
manage.py check_inbox — read recent email over IMAP and turn recruiter replies (interview invites, rejections,
offers, assessments) for jobs you're tracking into pipeline SUGGESTIONS on the Interview page. Nothing is applied
automatically: each suggestion waits for you to confirm or dismiss it.

Read-only by construction: the mailbox is opened with readonly=True and messages are fetched with BODY.PEEK, so
nothing is marked read, moved or deleted. Only a short snippet of a matched email is stored, never whole messages.

Credentials come from the environment, never from settings files:
    JOBHUNT_IMAP_HOST      e.g. imap.gmail.com
    JOBHUNT_IMAP_USER      your address
    JOBHUNT_IMAP_PASSWORD  an APP PASSWORD (Gmail: Google Account > Security > App passwords), not your real password
    JOBHUNT_IMAP_FOLDER    optional, default INBOX

    python manage.py check_inbox --days 14 [--account you@example.com]
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from coach.views import suggest_from_email


def _text(msg) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    plain, html = [], []
    for p in parts:
        ct = p.get_content_type()
        if p.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            payload = p.get_payload(decode=True)
            s = payload.decode(p.get_content_charset() or "utf-8", errors="replace") if payload else ""
        except Exception:  # noqa: BLE001
            continue
        (plain if ct == "text/plain" else html if ct == "text/html" else []).append(s)
    if plain:
        return "\n".join(plain)
    return re.sub(r"<[^>]+>", " ", "\n".join(html))


class Command(BaseCommand):
    help = "Suggest pipeline updates from recruiter emails (read-only IMAP; you confirm each suggestion)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--account", default="", help="attribute suggestions to this account's email (default: the shared guest pipeline)")
        parser.add_argument("--limit", type=int, default=300)

    def handle(self, *args, **opts):
        host, user, pw = (os.environ.get(k, "") for k in ("JOBHUNT_IMAP_HOST", "JOBHUNT_IMAP_USER", "JOBHUNT_IMAP_PASSWORD"))
        if not (host and user and pw):
            raise CommandError("Set JOBHUNT_IMAP_HOST, JOBHUNT_IMAP_USER and JOBHUNT_IMAP_PASSWORD (use an app password).")
        owner = None
        if opts["account"]:
            owner = get_user_model().objects.filter(email__iexact=opts["account"]).first()
            if not owner:
                raise CommandError(f"no account with email {opts['account']}")
        since = (datetime.now() - timedelta(days=opts["days"])).strftime("%d-%b-%Y")
        m = imaplib.IMAP4_SSL(host)
        try:
            m.login(user, pw)
            m.select(os.environ.get("JOBHUNT_IMAP_FOLDER", "INBOX"), readonly=True)
            typ, data = m.search(None, "SINCE", since)
            ids = (data[0].split() if typ == "OK" and data and data[0] else [])[-opts["limit"]:]
            made = seen = 0
            for i in ids:
                typ, msg_data = m.fetch(i, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                seen += 1
                subject = str(make_header(decode_header(msg.get("Subject", ""))))
                try:
                    received = parsedate_to_datetime(msg.get("Date"))
                except Exception:  # noqa: BLE001
                    received = None
                out = suggest_from_email(owner, subject, _text(msg)[:20000], msg.get("From", ""), msg.get("Message-ID", "") or f"{host}:{i.decode()}", received)
                if out.get("suggestion_id"):
                    made += 1
                    self.stdout.write(f"  {out['kind']:<10} {subject[:70]}  ->  {out['matches'][0]['company']}")
            self.stdout.write(self.style.SUCCESS(f"Read {seen} emails from the last {opts['days']} days; {made} new suggestion(s). Confirm them on the Interview page."))
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass
