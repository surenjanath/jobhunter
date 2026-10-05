"""
Per-account data. Everything here lives in Django's own 'default' database (auth_user + these tables), never in
the scanner's 'jobhunt' database — that one stays a single shared cache of scanned postings, the same for every
account and for anyone not signed in at all. An account is what makes a resume, its match scores, and the
pipeline PRIVATE to one person instead of the one shared instance-wide profile every earlier version of this
app had (and which anonymous/no-account use still has, unchanged — see accounts/context.py).
"""
from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """The parsed-resume profile (what matching.get_context() needs) plus search preferences, for one account.
    One per user; re-uploading a resume replaces `data` in place (no multi-version history here — that stays a
    feature of the shared/anonymous profile for now; see docs/ACCOUNTS.md)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    data = models.JSONField(default=dict, blank=True)            # the parsed resume profile dict
    resume_text = models.TextField(blank=True, default="")       # raw text, for evidence retrieval
    resume_filename = models.TextField(blank=True, default="")
    preferences = models.JSONField(default=dict, blank=True)     # targets / min_score / salary floor / work_mode
    llm = models.JSONField(default=dict, blank=True)             # own AI settings: {keys: {provider: key}, cfg: {...}}
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"profile · {self.user}"


class UserJobStatus(models.Model):
    """One account's tracking state for one job — the private analogue of app_status. job_id references a row in
    the shared 'jobhunt' database's jobs table; it's a plain string, not a Django FK, because the two live in
    different databases (SQLite doesn't support cross-database foreign keys, and Django won't either)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="job_statuses")
    job_id = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=40, default="New")
    applied_date = models.CharField(max_length=20, blank=True, default="")
    followup_date = models.CharField(max_length=20, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    starred = models.BooleanField(default=False)
    dismiss_reason = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "job_id")]
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.user} · {self.job_id} · {self.status}"


class UserJobMatch(models.Model):
    """One account's fit/odds for one job, against THEIR resume — a cache refreshed by rescore_user() in
    accounts/context.py, not computed on every page load. Falls back to the shared jobs.fit_score (whoever
    scanned last computed it against the single shared profile) until an account has rescored at least once."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="job_matches")
    job_id = models.CharField(max_length=255, db_index=True)
    fit_score = models.IntegerField(default=0)
    likelihood = models.IntegerField(default=0)
    interview_chance = models.IntegerField(default=0)
    match_json = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "job_id")]
        indexes = [models.Index(fields=["user", "fit_score"])]


class InterviewSession(models.Model):
    """One finished mock interview (the Interview page): scores, the wrap-up, and every question's result.
    user is NULL for the shared/no-account instance, the same way the rest of the app treats guests."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="interview_sessions")
    job_id = models.CharField(max_length=255, blank=True, default="")
    job_title = models.TextField(blank=True, default="")
    company = models.TextField(blank=True, default="")
    overall = models.IntegerField(default=0)
    content = models.IntegerField(default=0)
    delivery = models.IntegerField(null=True, blank=True)
    n = models.IntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    results = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user or 'guest'} · {self.job_title} · {self.overall}"
