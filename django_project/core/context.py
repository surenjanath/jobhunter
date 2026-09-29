"""Template context shared by every page: the navigation and the URL map the JavaScript uses to move between pages."""
import json

from django.urls import reverse

# key, label, url name. Order is the nav order. Keys are what the JS refers to (URLS.jobs, goto('analytics'), …).
PAGES = [
    ("home", "Conditions", "page-home"),
    ("jobs", "Ledger", "page-ledger"),
    ("pipeline", "Pipeline", "page-pipeline"),
    ("analytics", "Analytics", "page-analytics"),
    ("profile", "Profile", "page-profile"),
    ("interview", "Interview", "page-interview"),
    ("trinidad", "Trinidad", "page-trinidad"),
    ("settings", "Settings", "page-settings"),
]


def shell(request):
    nav = [{"key": k, "label": label, "url": reverse(name)} for k, label, name in PAGES]
    return {"nav": nav, "urls_json": json.dumps({n["key"]: n["url"] for n in nav})}
