from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase, override_settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory


@override_settings(SECURE_SSL_REDIRECT=False)
class HealthTests(TestCase):
    def test_health_is_read_only_public_uncached_and_generic(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(self.client.post("/api/health/").status_code, 405)
        with patch("config.views.connection.cursor", side_effect=OperationalError("private database details")):
            response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_other_api_views_require_authentication_by_default(self):
        @api_view(["GET"])
        def protected(request):
            return Response({"private": True})

        response = protected(APIRequestFactory().get("/"))
        self.assertEqual(response.status_code, 403)
