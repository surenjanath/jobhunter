from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(["GET"])
def list_letters(request):
    try:
        from jobs.models import CoverLetter
        qs = CoverLetter.objects.using("jobhunt").all()[:20]
        data = [{"id": c.id, "job_id": c.job_id, "company": c.company, "title": c.title, "backend": c.backend, "path": c.path, "created_at": c.created_at} for c in qs]
        return Response(data)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
