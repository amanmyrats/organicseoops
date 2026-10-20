"""Reject non-opaque/oversized log requests before CSRF can parse multipart files."""
import re

from django.http import JsonResponse


class BotLogBodyGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and re.match(r"^/api/organizations/[0-9]+/projects/[0-9]+/bot-logs(?:/|$)", request.path_info):
            intake = request.path_info.rstrip("/").endswith("/bot-logs")
            limit = 1048576 if intake else 2
            length = request.META.get("CONTENT_LENGTH", "")
            if (request.content_type != ("application/x-ndjson" if intake else "application/json")
                or request.headers.get("Content-Encoding") or not re.fullmatch(r"[0-9]{1,7}", length)
                or not 1 <= int(length) <= limit):
                response = JsonResponse({"errors": [{"message": "Use bounded opaque JSONL or an empty JSON cancellation."}]}, status=413)
                response["Cache-Control"] = "private, no-store"
                return response
        return self.get_response(request)
