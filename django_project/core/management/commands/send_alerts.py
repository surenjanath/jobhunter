"""manage.py send_alerts [--dry-run] [--account you@example.com]
Email/Telegram the new good-fit roles, follow-ups due and tracked roles closing soon. Each job is only ever announced
once. Configure a channel with environment variables (see jobhunt/src/alerts.py); without one it just reports."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core import alerts_service


class Command(BaseCommand):
    help = "Send the job alert (email / Telegram)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="print the message instead of sending it")
        parser.add_argument("--account", default="", help="use this account's pipeline (default: the owner, else the shared one)")

    def handle(self, *args, **opts):
        user = alerts_service.owner_user()
        if opts["account"]:
            user = User.objects.filter(username=opts["account"].strip().lower()).first()
            if not user:
                raise CommandError(f"no account {opts['account']}")
        out = alerts_service.run(user, dry_run=opts["dry_run"])
        if out.get("message") and opts["dry_run"]:
            self.stdout.write(out["message"]["subject"] + "\n\n" + out["message"]["text"])
        self.stdout.write(str({k: v for k, v in out.items() if k != "message"}))
