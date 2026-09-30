# Job alerts

JobHunter can message you when there's something to act on: **new good-fit roles** (fit 55+ by default), **follow-ups
that are due**, and **roles you're tracking that close within 3 days**. Each job is only announced once. Nothing is sent
until you set up a channel, and the credentials only live in environment variables (your `.env` locally, or the
service's Environment on Render), never in the database or the repository.

## Telegram (easiest)

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token it gives you.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<token>/getUpdates` in a browser and copy
   the `chat` → `id` number.
3. Set `JOBHUNTER_TELEGRAM_TOKEN` and `JOBHUNTER_TELEGRAM_CHAT_ID`.

## Email

Any SMTP server. For Gmail, use an **app password** (Google Account → Security → App passwords), never your real one:

```
JOBHUNTER_SMTP_HOST=smtp.gmail.com
JOBHUNTER_SMTP_PORT=587
JOBHUNTER_SMTP_USER=you@gmail.com
JOBHUNTER_SMTP_PASSWORD=<app password>
JOBHUNTER_ALERT_TO=you@gmail.com
```

## When alerts go out

- **Settings page → Job alerts**: preview the next alert, send a test, or send now.
- **After every scheduled scan**: `scripts/scan-cron.sh` (your computer) and the Render re-scan loop both run
  `python manage.py send_alerts` afterwards.
- By hand: `cd django_project && python manage.py send_alerts --dry-run` prints the message without sending.

`JOBHUNTER_ALERT_MIN_FIT` (default 55) sets how good a new role has to be to make the alert.
