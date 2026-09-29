"""
Interview preparation data (see jobhunt/src/coach.py for the logic). Lives in Django's 'default' database, like the
rest of per-account data. user is NULL for the shared no-account instance — the same guest convention as
accounts.InterviewSession — so everything works without signing up and stays private once you do.
"""
from django.conf import settings
from django.db import models

_USER = dict(to=settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)


class VoiceBaseline(models.Model):
    """Your calm reading voice, recorded once: composure is then judged against it rather than generic thresholds."""
    user = models.ForeignKey(related_name="voice_baselines", **_USER)
    metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Story(models.Model):
    """A reusable STAR story, usually saved from a mock-interview answer, tagged with the skills it proves."""
    user = models.ForeignKey(related_name="stories", **_USER)
    title = models.CharField(max_length=200)
    question = models.TextField(blank=True, default="")
    text = models.TextField()
    skills = models.JSONField(default=list, blank=True)
    star = models.JSONField(default=dict, blank=True)
    score = models.IntegerField(null=True, blank=True)
    job_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class Drill(models.Model):
    """A question to practise again, on a spaced-repetition schedule (coach.schedule)."""
    user = models.ForeignKey(related_name="drills", **_USER)
    question = models.TextField()
    kind = models.CharField(max_length=20, default="behavioural")
    job_id = models.CharField(max_length=255, blank=True, default="")
    job_title = models.TextField(blank=True, default="")
    source = models.CharField(max_length=20, default="mock")   # mock | real (asked in a real interview) | manual
    interval_days = models.FloatField(default=1)
    next_due = models.DateField()
    reps = models.IntegerField(default=0)
    last_score = models.IntegerField(null=True, blank=True)
    last_reviewed = models.DateTimeField(null=True, blank=True)
    mastered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_due", "id"]


class RealInterview(models.Model):
    """A real interview on the calendar: drives the prep plan before, and the log afterwards."""
    STAGES = [("screen", "Recruiter screen"), ("technical", "Technical"), ("onsite", "Panel / on-site"), ("final", "Final")]
    user = models.ForeignKey(related_name="real_interviews", **_USER)
    job_id = models.CharField(max_length=255)
    job_title = models.TextField(blank=True, default="")
    company = models.TextField(blank=True, default="")
    scheduled_on = models.DateField()
    stage = models.CharField(max_length=20, choices=STAGES, default="screen")
    done_tasks = models.JSONField(default=list, blank=True)     # prep-plan task keys ticked off
    # the log, filled in afterwards
    logged = models.BooleanField(default=False)
    questions = models.JSONField(default=list, blank=True)
    felt = models.IntegerField(null=True, blank=True)            # 1 (rough) .. 5 (great)
    outcome = models.CharField(max_length=20, blank=True, default="")   # waiting | advanced | rejected | offer
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_on", "id"]


class InboxSuggestion(models.Model):
    """A recruiter email that looks like an invite / rejection / offer, matched to a tracked job. Never applied
    automatically: you confirm each one. Created by `manage.py check_inbox` (IMAP) or by pasting an email."""
    user = models.ForeignKey(related_name="inbox_suggestions", **_USER)
    message_id = models.CharField(max_length=500, blank=True, default="")
    subject = models.TextField(blank=True, default="")
    sender = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(null=True, blank=True)
    kind = models.CharField(max_length=20)
    suggested_status = models.CharField(max_length=40, blank=True, default="")
    job_id = models.CharField(max_length=255, blank=True, default="")
    job_title = models.TextField(blank=True, default="")
    company = models.TextField(blank=True, default="")
    snippet = models.TextField(blank=True, default="")
    mentions_date = models.CharField(max_length=80, blank=True, default="")
    state = models.CharField(max_length=12, default="new")        # new | applied | dismissed
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
