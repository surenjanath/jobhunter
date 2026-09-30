"""
alerts.py — send the digest to you instead of waiting for you to open the app: new good-fit roles, follow-ups that
are due, and tracked roles closing soon. Email (any SMTP server) and/or Telegram.

Nothing is sent unless a channel is configured, and credentials only ever come from the environment:

    email     JOBHUNTER_SMTP_HOST, JOBHUNTER_SMTP_PORT (587), JOBHUNTER_SMTP_USER, JOBHUNTER_SMTP_PASSWORD,
              JOBHUNTER_ALERT_TO (your address), JOBHUNTER_ALERT_FROM (defaults to the SMTP user)
              Gmail: smtp.gmail.com, port 587, and an APP PASSWORD (Google Account > Security > App passwords).
    telegram  JOBHUNTER_TELEGRAM_TOKEN (from @BotFather), JOBHUNTER_TELEGRAM_CHAT_ID (message the bot, then see
              https://api.telegram.org/bot<token>/getUpdates for your chat id)

compose() is pure (tested without a network); send() does the delivery.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def channels() -> dict:
    """Which channels are configured (never the secrets themselves)."""
    e = os.environ
    return {"email": bool(e.get("JOBHUNTER_SMTP_HOST") and e.get("JOBHUNTER_SMTP_USER") and e.get("JOBHUNTER_SMTP_PASSWORD") and e.get("JOBHUNTER_ALERT_TO")),
            "telegram": bool(e.get("JOBHUNTER_TELEGRAM_TOKEN") and e.get("JOBHUNTER_TELEGRAM_CHAT_ID"))}


def compose(picks: list[dict], followups: list[dict], closing: list[dict], site_url: str = "") -> dict | None:
    """-> {subject, text} or None when there's nothing worth sending.
    picks: [{title, company, fit, verdict, where, url, advice}]  followups: [{title, company, followup_date}]
    closing: [{title, company, expires_at}]"""
    if not (picks or followups or closing):
        return None
    parts = []
    bits = []
    if picks:
        bits.append(f"{len(picks)} new role{'s' if len(picks) > 1 else ''}")
    if followups:
        bits.append(f"{len(followups)} follow-up{'s' if len(followups) > 1 else ''} due")
    if closing:
        bits.append(f"{len(closing)} closing soon")
    subject = "JobHunter: " + ", ".join(bits)
    if followups:
        parts.append("FOLLOW UP TODAY")
        parts += [f"- {f['title']} at {f['company']} (was due {f.get('followup_date') or 'today'})" for f in followups]
        parts.append("")
    if closing:
        parts.append("CLOSING SOON (you're tracking these)")
        parts += [f"- {c['title']} at {c['company']}, closes {c.get('expires_at')}" for c in closing]
        parts.append("")
    if picks:
        parts.append("NEW AND WORTH YOUR TIME")
        for p in picks:
            parts.append(f"- {p['title']} at {p['company']}: fit {p.get('fit', '?')}, {p.get('verdict', '').lower()} odds, {p.get('where', '')}")
            if p.get("advice"):
                parts.append(f"  {p['advice']}")
            if p.get("url"):
                parts.append(f"  {p['url']}")
        parts.append("")
    if site_url:
        parts.append(f"Open JobHunter: {site_url}")
    return {"subject": subject, "text": "\n".join(parts).strip() + "\n"}


def send(msg: dict, timeout: int = 20) -> dict:
    """Deliver to every configured channel. -> {channel: "sent" | "error: …"}. Never raises."""
    out = {}
    ch = channels()
    e = os.environ
    if ch["email"]:
        try:
            m = EmailMessage()
            m["Subject"], m["To"] = msg["subject"], e["JOBHUNTER_ALERT_TO"]
            m["From"] = e.get("JOBHUNTER_ALERT_FROM") or e["JOBHUNTER_SMTP_USER"]
            m.set_content(msg["text"])
            with smtplib.SMTP(e["JOBHUNTER_SMTP_HOST"], int(e.get("JOBHUNTER_SMTP_PORT") or 587), timeout=timeout) as s:
                s.starttls()
                s.login(e["JOBHUNTER_SMTP_USER"], e["JOBHUNTER_SMTP_PASSWORD"])
                s.send_message(m)
            out["email"] = "sent"
        except Exception as exc:  # noqa: BLE001
            out["email"] = f"error: {type(exc).__name__}: {str(exc)[:120]}"
    if ch["telegram"]:
        try:
            import requests
            text = f"{msg['subject']}\n\n{msg['text']}"[:4000]   # Telegram's limit is 4096 characters
            r = requests.post(f"https://api.telegram.org/bot{e['JOBHUNTER_TELEGRAM_TOKEN']}/sendMessage",
                              json={"chat_id": e["JOBHUNTER_TELEGRAM_CHAT_ID"], "text": text, "disable_web_page_preview": True}, timeout=timeout)
            out["telegram"] = "sent" if r.ok else f"error: HTTP {r.status_code}: {r.text[:120]}"
        except Exception as exc:  # noqa: BLE001
            out["telegram"] = f"error: {type(exc).__name__}"
    return out
