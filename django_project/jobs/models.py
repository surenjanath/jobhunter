from django.db import models

class Job(models.Model):
    job_id = models.TextField(primary_key=True)
    source = models.TextField()
    title = models.TextField()
    company = models.TextField()
    location = models.TextField(blank=True, default="")
    remote = models.BooleanField(default=False)
    salary = models.TextField(blank=True, default="")
    url = models.TextField()
    description = models.TextField(blank=True, default="")
    posted_at = models.TextField(blank=True, default="")
    fit_score = models.IntegerField(default=0)
    tier = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")
    flags = models.TextField(blank=True, default="")
    alt_urls = models.TextField(blank=True, default="")
    seen_on = models.TextField(blank=True, default="")
    first_seen = models.TextField(blank=True, default="")
    updated_at = models.TextField()
    expires_at = models.TextField(blank=True, default="")
    last_seen = models.TextField(blank=True, default="")
    region = models.TextField(blank=True, default="")
    category = models.TextField(blank=True, default="")
    likelihood = models.IntegerField(default=0)
    interview_chance = models.IntegerField(default=0)
    work_mode = models.TextField(blank=True, default="")
    remote_scope = models.TextField(blank=True, default="")
    match_json = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "jobs"
        ordering = ["-fit_score", "company"]
        app_label = "jobs"

    def __str__(self):
        return f"[{self.fit_score}] {self.title} @ {self.company}"


class ApplicationStatus(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, primary_key=True, db_column="job_id", to_field="job_id")
    status = models.TextField(default="New")
    applied_date = models.TextField(blank=True, default="")
    followup_date = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    updated_at = models.TextField()
    starred = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = "app_status"
        app_label = "jobs"


class Scan(models.Model):
    id = models.AutoField(primary_key=True)
    started_at = models.TextField()
    finished_at = models.TextField(blank=True, null=True)
    total_fetched = models.IntegerField(default=0)
    total_kept = models.IntegerField(default=0)
    status = models.TextField(default="running")
    error = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "scans"
        ordering = ["-id"]
        app_label = "jobs"


class CoverLetter(models.Model):
    id = models.AutoField(primary_key=True)
    job_id = models.TextField()
    company = models.TextField(blank=True, default="")
    title = models.TextField(blank=True, default="")
    backend = models.TextField(blank=True, default="")
    text = models.TextField()
    path = models.TextField(blank=True, default="")
    created_at = models.TextField()

    class Meta:
        managed = False
        db_table = "cover_letters"
        ordering = ["-id"]
        app_label = "jobs"


class SourceRun(models.Model):
    """One scan's outcome for one Trinidad board (written by jobhunt/src/db.py)."""
    id = models.AutoField(primary_key=True)
    name = models.TextField()
    label = models.TextField(blank=True, default="")
    ok = models.BooleanField(default=True)
    count = models.IntegerField(default=0)
    ms = models.IntegerField(default=0)
    error = models.TextField(blank=True, default="")
    ran_at = models.TextField()

    class Meta:
        managed = False
        db_table = "source_runs"
        ordering = ["-id"]
        app_label = "jobs"


class Snapshot(models.Model):
    """One row per day: the market as your resume sees it (written by jobhunt/src/snapshot.py)."""
    day = models.TextField(primary_key=True)
    total = models.IntegerField(default=0)
    good = models.IntegerField(default=0)
    decent = models.IntegerField(default=0)
    local = models.IntegerField(default=0)
    remote = models.IntegerField(default=0)
    avg_fit = models.FloatField(default=0)
    avg_odds = models.FloatField(default=0)
    coverage = models.FloatField(default=0)
    top_skills = models.TextField(blank=True, default="[]")
    created_at = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "snapshots"
        ordering = ["day"]
        app_label = "jobs"
