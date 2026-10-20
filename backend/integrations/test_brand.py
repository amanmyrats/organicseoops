from unittest.mock import patch
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from jobs.services import execute_job
from tenancy.models import MembershipRole, OrganizationMembership
from tenancy.services import create_organization, create_project, update_project_configuration

from .brand import default_brand_label
from .models import QueryBrandReview, SearchMetricObservation
from .search_console import queue_search_console_csv_import
from .services import create_connection


@override_settings(
    SECURE_SSL_REDIRECT=False, STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}), ARTIFACT_MAX_BYTES=2 * 1024 * 1024,
)
class BrandQueryTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        users = get_user_model().objects
        self.owner = users.create_user("brand-owner@example.com", password="test-password")
        self.outsider = users.create_user("brand-outsider@example.com", password="test-password")
        self.viewer = users.create_user("brand-viewer@example.com", password="test-password")
        for user in (self.owner, self.outsider, self.viewer):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        organization = create_organization(user=self.owner, name="Brand org")
        OrganizationMembership.objects.create(organization=organization, user=self.viewer, role=MembershipRole.VIEWER)
        self.project = create_project(
            organization=organization, user=self.owner, name="Brand site", canonical_origin="https://brand.example",
        )
        connection = create_connection(
            project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://brand.example", capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance", source_semantics_version="csv-v1",
            timezone="America/Los_Angeles",
        )
        self.connection = connection
        end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=2)
        job = queue_search_console_csv_import(
            connection=connection, user=self.owner,
            content=b"Top queries,Clicks,Impressions,CTR,Position\nOrganic Ops prices,1,2,50%,2\norganically growing,1,2,50%,3\n",
            date_start=end - timedelta(days=1), date_end=end,
        )
        self.assertTrue(execute_job(job.pk))
        self.path = f"/api/organizations/{organization.pk}/projects/{self.project.pk}/sources/{connection.pk}/queries/"

    def test_default_brand_labels_are_scoped_and_recalculate_after_alias_change(self):
        self.assertEqual(default_brand_label("organically growing", ["organic"]), "non_branded")
        client = Client()
        self.assertEqual(client.get(self.path, secure=True).status_code, 401)
        client.force_login(self.outsider)
        self.assertEqual(client.get(self.path, secure=True).status_code, 404)
        client.force_login(self.owner)
        first = client.get(self.path, secure=True)
        self.assertEqual(first.status_code, 200)
        self.assertIn("no-store", first["Cache-Control"])
        self.assertEqual({row["default_label"] for row in first.json()["queries"]}, {"unclassified"})
        update_project_configuration(
            project=self.project, user=self.owner, expected_revision=0,
            changes={"brand_aliases": ["Organic Ops"]},
        )
        second = client.get(self.path, secure=True).json()
        self.assertEqual(second["alias_revision"], 1)
        labels = {row["query"]: row["label"] for row in second["queries"]}
        self.assertEqual(labels, {"Organic Ops prices": "branded", "organically growing": "non_branded"})
        self.assertEqual(second["source_completeness"], "provider_export_unknown")
        self.assertEqual(SearchMetricObservation.objects.count(), 2)

    def test_corrections_require_csrf_current_revision_and_leave_immutable_history(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        self.assertEqual(owner.get("/_allauth/browser/v1/auth/session", secure=True).status_code, 200)
        query = SearchMetricObservation.objects.get(query="organically growing")
        path = f"{self.path}{query.pk}/reviews/"

        def post(payload, *, csrf=True):
            headers = {"HTTP_REFERER": "https://testserver/"}
            if csrf:
                headers["HTTP_X_CSRFTOKEN"] = owner.cookies["csrftoken"].value
            return owner.post(path, data=json.dumps(payload), content_type="application/json", secure=True, **headers)

        payload = {"revision": 0, "label": "branded", "reason": "Reviewed query context"}
        self.assertEqual(post(payload, csrf=False).status_code, 403)
        self.assertEqual(post(payload).status_code, 201)
        self.assertEqual(post(payload).status_code, 409)
        self.assertEqual(post({"revision": 1, "label": "non_branded", "reason": "Human correction"}).status_code, 201)
        self.assertEqual(post({"revision": 2, "label": "invalid", "reason": "Bad"}).status_code, 400)
        self.assertEqual(
            list(QueryBrandReview.objects.filter(observation=query).values_list("revision", "label")),
            [(1, "branded"), (2, "non_branded")],
        )
        self.assertEqual(owner.get(path, secure=True).json()["reviews"][0]["revision"], 2)
        self.assertEqual(next(row for row in owner.get(self.path, secure=True).json()["queries"] if row["id"] == query.pk)["label"], "non_branded")
        self.assertEqual(SearchMetricObservation.objects.get(pk=query.pk).query, "organically growing")

        viewer = Client(enforce_csrf_checks=True)
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(path, secure=True).status_code, 200)
        viewer.get("/_allauth/browser/v1/auth/session", secure=True)
        self.assertEqual(viewer.post(
            path, data=json.dumps({"revision": 2, "label": "branded", "reason": "Viewer should not edit"}),
            content_type="application/json", secure=True,
            HTTP_REFERER="https://testserver/", HTTP_X_CSRFTOKEN=viewer.cookies["csrftoken"].value,
        ).status_code, 403)

        type(self.connection).objects.filter(pk=self.connection.pk).update(state="disconnected")
        self.assertEqual(post({"revision": 2, "label": "branded", "reason": "Disconnected"}).status_code, 400)
        self.assertEqual(QueryBrandReview.objects.filter(observation=query).count(), 2)

        outsider = Client(enforce_csrf_checks=True)
        outsider.force_login(self.outsider)
        self.assertEqual(outsider.get(path, secure=True).status_code, 404)
        outsider.get("/_allauth/browser/v1/auth/session", secure=True)
        self.assertEqual(outsider.post(
            path, data=json.dumps(payload), content_type="application/json", secure=True,
            HTTP_REFERER="https://testserver/", HTTP_X_CSRFTOKEN=outsider.cookies["csrftoken"].value,
        ).status_code, 404)
