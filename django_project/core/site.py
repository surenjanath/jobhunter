"""Effective site-access settings: the Settings-page switches (core.SiteConfig) over the environment defaults.

Who may change them: an admin (is_staff) account. On a copy with no admin yet (a fresh local install), anyone may, and
the first signed-in person who does becomes the admin. "Require sign-in" can only be switched on while signed in,
so nobody can lock themselves out of their own copy."""
from __future__ import annotations

import time

_cache: dict = {"t": 0.0, "v": None}
_TTL = 3.0   # read on every request by the middleware; a short cache keeps that off the database


def get() -> dict:
    now = time.time()
    if _cache["v"] is not None and now - _cache["t"] < _TTL:
        return _cache["v"]
    from django.conf import settings
    from .models import SiteConfig
    row = SiteConfig.objects.filter(pk=1).first()
    v = {"allow_signup": settings.JOBHUNTER_ALLOW_SIGNUP if row is None or row.allow_signup is None else row.allow_signup,
         "require_signin": settings.JOBHUNTER_PRIVATE if row is None or row.require_signin is None else row.require_signin}
    _cache.update(t=now, v=v)
    return v


def invalidate() -> None:
    _cache.update(t=0.0, v=None)


def can_edit(user) -> bool:
    from django.contrib.auth.models import User
    if user is not None and user.is_authenticated and user.is_staff:
        return True
    return not User.objects.filter(is_staff=True).exists()
