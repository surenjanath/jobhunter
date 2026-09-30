"""Answer the platform health check before anything that could reject it.

Hosting platforms probe /health/ from inside their network, sometimes with an internal Host header and over plain
HTTP. Django's ALLOWED_HOSTS check (DisallowedHost -> 400) or the HTTPS redirect (-> 301) would then fail the probe
and the deploy, even though the app is fine. This sits first in MIDDLEWARE and answers only that exact path; the
answer reveals nothing but "up" and a job count. Every other request goes through the normal checks."""
from django.http import JsonResponse

HEALTH_PATHS = ("/health/", "/health")


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info in HEALTH_PATHS and request.method in ("GET", "HEAD"):
            from .views import health_payload
            return JsonResponse(health_payload())
        return self.get_response(request)
