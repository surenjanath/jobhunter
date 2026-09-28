from django.contrib import admin
from .models import Job, Scan, CoverLetter, ApplicationStatus

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("job_id", "title", "company", "source", "fit_score", "tier", "posted_at")
    list_filter = ("source", "tier", "remote")
    search_fields = ("title", "company", "description")
    ordering = ("-fit_score",)
    list_per_page = 25
    readonly_fields = ("job_id", "description")

@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ("id", "started_at", "finished_at", "total_fetched", "total_kept", "status")
    ordering = ("-id",)

@admin.register(CoverLetter)
class CoverLetterAdmin(admin.ModelAdmin):
    list_display = ("id", "job_id", "company", "title", "backend", "created_at")
    search_fields = ("company", "title", "job_id")

@admin.register(ApplicationStatus)
class AppStatusAdmin(admin.ModelAdmin):
    list_display = ("job", "status", "updated_at")
    list_filter = ("status",)
