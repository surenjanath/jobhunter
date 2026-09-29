"""Account registration, login, logout — Django's own auth (User model, hashed passwords, session cookies).
The username field holds the email address; there's no separate username concept in this app.

No email verification and no password-reset-by-email: this project ships with no outbound mail configured
(it's a local-first tool, not a hosted service). See docs/ACCOUNTS.md for what that means in practice."""
import re

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _user_out(user) -> dict:
    from .models import UserProfile
    has_profile = UserProfile.objects.filter(user=user).exclude(data={}).exists()
    return {"email": user.email, "has_profile": has_profile}


@api_view(["GET"])
def me(request):
    if request.user.is_authenticated:
        return Response({"authenticated": True, **_user_out(request.user)})
    return Response({"authenticated": False})


@api_view(["POST"])
def register(request):
    email = str(request.data.get("email") or "").strip().lower()
    password = str(request.data.get("password") or "")
    if not EMAIL_RE.match(email):
        return Response({"error": "enter a valid email address"}, status=400)
    if len(email) > 150:
        return Response({"error": "that email is too long"}, status=400)
    if User.objects.filter(username=email).exists():
        return Response({"error": "an account with that email already exists — sign in instead"}, status=409)
    try:
        validate_password(password)
    except ValidationError as e:
        return Response({"error": " ".join(e.messages)}, status=400)
    user = User.objects.create_user(username=email, email=email, password=password)
    login(request, user)
    migrated = False
    if str(request.data.get("keep_current_resume", "true")).lower() != "false":
        migrated = _migrate_anonymous_profile(user)
    return Response({"ok": True, **_user_out(user), "migrated_current_resume": migrated}, status=201)


@api_view(["POST"])
def login_view(request):
    email = str(request.data.get("email") or "").strip().lower()
    password = str(request.data.get("password") or "")
    user = authenticate(request, username=email, password=password)
    if not user:
        return Response({"error": "wrong email or password"}, status=401)
    login(request, user)
    return Response({"ok": True, **_user_out(user)})


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"ok": True})


def _migrate_anonymous_profile(user) -> bool:
    """On registration, carry over whatever resume is active anonymously right now — the point of "test it,
    then create a profile to keep it". Best-effort: a failure here must never break registration itself."""
    try:
        from src import profile_store
        prof = profile_store.active_profile()
        if not prof:
            return False
        text = profile_store.get_resume_text(prof["_resume_id"])
        from .models import UserProfile
        UserProfile.objects.update_or_create(user=user, defaults={
            "data": prof, "resume_text": text, "resume_filename": prof.get("_filename", ""),
            "preferences": profile_store.get_prefs(),
        })
        from . import context
        context.invalidate(user)
        context.rescore_user(user)   # so the Ledger shows this account's real fit/odds immediately, not the shared scores
        return True
    except Exception:  # noqa: BLE001
        return False
