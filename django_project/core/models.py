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
