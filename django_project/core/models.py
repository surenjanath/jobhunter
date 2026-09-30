from django.db import models


class StatusEvent(models.Model):
    """Local audit of pipeline edits. Lives on the Django database, not the scraper db."""

    job_id = models.TextField(db_index=True)
    title = models.CharField(max_length=300, blank=True)
    company = models.CharField(max_length=200, blank=True)
    from_status = models.CharField(max_length=40, blank=True)
    to_status = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company}: {self.from_status} → {self.to_status}"


class SiteConfig(models.Model):
    """Site-wide access switches, set from the Settings page (one row). A field left NULL falls back to the
    environment default (JOBHUNTER_PRIVATE / JOBHUNTER_ALLOW_SIGNUP), so a fresh hosted copy starts as configured."""
    allow_signup = models.BooleanField(null=True, blank=True)
    require_signin = models.BooleanField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=254, blank=True, default="")

    def __str__(self):
        return f"signup={self.allow_signup} signin={self.require_signin}"


class AlertSent(models.Model):
    """A job already announced in an alert, so the next alert only has new ones."""
    job_id = models.CharField(max_length=255, unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)
