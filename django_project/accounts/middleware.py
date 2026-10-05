"""Make every resume read during a signed-in request see THAT account's resume.

The scanner package reads "the resume" through src.profile_store (active_profile, get_resume_text, get_prefs,
active_index) and src.matching.current_context. For a signed-in account with its own resume, this installs that
resume for the length of the request (a ContextVar — per request, never shared between threads), so interview
practice, the AI features, the job-dialog tabs, cover letters and analytics all use the account's own data instead
of the shared guest resume. Guests, and accounts that haven't uploaded a resume, are untouched.
"""
from .context import build_context, has_profile


class AccountResumeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not (user is not None and user.is_authenticated and has_profile(user)):
            return self.get_response(request)
        from src import profile_store
        from .context import DEFAULT_PREFS
        up = user.profile
        token = profile_store.use_request_resume(
            up.data, up.resume_text, {**DEFAULT_PREFS(), **(up.preferences or {})},
            ctx_fn=lambda: build_context(user))   # lazy: built (and cached briefly) only if something asks
        try:
            return self.get_response(request)
        finally:
            profile_store.reset_request_resume(token)


class AccountLLMMiddleware:
    """A signed-in account's own AI keys and choices apply to everything its request does. Where the account has set
    nothing, the site-wide settings (added by an admin) are used, as they are for guests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        own = user.profile.llm if user is not None and user.is_authenticated and hasattr(user, "profile") else None
        if not own:
            return self.get_response(request)
        from src import llm
        with llm.scoped(own):
            return self.get_response(request)


class PrivateSiteMiddleware:
    """settings.JOBHUNTER_PRIVATE: every page and API needs a signed-in user. Pages redirect to /login/, API calls get
    a JSON 401. Only sign-in itself, the health check and static files stay open. Off by default (local use)."""
    OPEN = ("/login/", "/api/auth/login/", "/api/auth/me/", "/health", "/static/", "/favicon")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core import site
        if request.path.startswith(self.OPEN) or not site.get()["require_signin"]:
            return self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return self.get_response(request)
        if request.path.startswith("/api/"):
            from django.http import JsonResponse
            return JsonResponse({"error": "sign in required"}, status=401)
        from urllib.parse import quote
        from django.shortcuts import redirect
        return redirect(f"/login/?next={quote(request.get_full_path())}")
