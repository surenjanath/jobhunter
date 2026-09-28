from rest_framework import serializers
from .models import Job, Scan, CoverLetter

class JobSerializer(serializers.ModelSerializer):
    app_status = serializers.CharField(source="applicationstatus.status", default="New", read_only=True)
    class Meta:
        model = Job
        fields = ["job_id","source","title","company","location","remote","salary","url","description","posted_at","fit_score","tier","why","flags","alt_urls","seen_on","first_seen","updated_at","app_status"]

class ScanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scan
        fields = "__all__"

class CoverLetterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoverLetter
        fields = "__all__"
