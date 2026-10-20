"""Keep unsupported bodies out of multipart handlers before CSRF processing."""
import re

from django.http import JsonResponse


class YandexBodyGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        management = re.fullmatch(r"/api/organizations/[0-9]+/projects/[0-9]+/yandex/(?:oauth/start|sync(?:/[0-9]+)?|grants/[0-9]+/(?:revoke|refresh-report-revoked)|exchanges/[0-9]+/report-revoked)/?", request.path_info)
        match = re.fullmatch(r"/api/organizations/[0-9]+/projects/[0-9]+/yandex/imports(?:/([0-9]+))?/?", request.path_info)
        if request.method == "POST" and (match or management):
            intake = bool(match and match.group(1) is None)
            length = request.META.get("CONTENT_LENGTH", "")
            if (request.content_type != ("text/csv" if intake else "application/json")
                or request.headers.get("Content-Encoding") or not re.fullmatch(r"[0-9]{1,7}", length)
                or not 1 <= int(length) <= (1048576 if intake else 2048 if management else 2)):
                response = JsonResponse({"error": "Use bounded CSV or an empty JSON cancellation."}, status=413)
                response["Cache-Control"] = "private, no-store"
                response["X-Robots-Tag"] = "noindex, nofollow"
                return response
        return self.get_response(request)
