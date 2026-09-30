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
