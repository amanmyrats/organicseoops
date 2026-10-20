import json

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType
from tenancy.services import create_organization, create_project, update_project

from .ga4_oauth import SCOPE, encrypt_ga4_refresh_token
from .ga4_quality import record_ga4_measurement_review
from .models import GA4MeasurementReview, GA4OAuthGrant, IntegrationConnection


@override_settings(GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class GA4MeasurementReviewTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("ga4-quality@example.test", password="test-password")
        self.foreign = users.create_user("ga4-quality-foreign@example.test", password="test-password")
        for user in (self.owner, self.foreign):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="GA4 quality fixture")
        self.project = create_project(organization=organization, user=self.owner, name="Quality project",
            canonical_origin="https://quality.example")
        grant = GA4OAuthGrant.objects.create(organization=organization, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_ga4_refresh_token("REFRESH_SECRET"), scope=SCOPE,
            property_id="12345", selected_origins=[self.project.canonical_origin],
            state=GA4OAuthGrant.State.ACTIVE, verified_at=timezone.now())
        self.connection = IntegrationConnection.objects.create(project=self.project, provider="google_analytics_4",
            external_property_id="12345", credential_reference=grant.credential_reference,
            capabilities=["api_sync", "landing_metrics"], available_dimensions=["hostname", "landing_page"],
            source_semantics="ga4_landing_pages", source_semantics_version="ga4-data-v1",
            timezone="Europe/Istanbul", currency="USD")

    def review(self, revision=0, **changes):
        fields = {"project": self.project, "user": self.owner, "connection": self.connection,
                  "expected_revision": revision,
                  "definitions": [{"goal": "Qualified booking", "event_name": "purchase",
                                   "value_definition": "Manual booking value rule, unverified"}],
                  "instrumentation_state": "manual_reviewed", "instrumentation_notes": "Check an authorized test event",
                  "event_quality_state": "not_checked",
                  "attribution_notes": "GA4 configured attribution unverified",
                  "consent_notes": "Consent gaps not yet checked", "tracking_change_notes": "No known tracking change"}
        fields.update(changes)
        return record_ga4_measurement_review(**fields)

    def test_append_only_human_definitions_do_not_verify_aggregate_key_events(self):
        first = self.review()
        self.assertEqual(self.review().pk, first.pk)
        self.assertEqual(AuditEvent.objects.filter(project=self.project,
            event_type=AuditEventType.GA4_MEASUREMENT_REVIEWED).count(), 1)
        self.assertEqual((first.currency, first.timezone, first.property_id), ("USD", "Europe/Istanbul", "12345"))
        self.assertEqual(first.instrumentation_state, "manual_reviewed")
        self.assertNotIn("REFRESH_SECRET", str(first.__dict__))
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            self.review(instrumentation_notes="Different state with old revision")
        revised = self.review(revision=1, instrumentation_notes="Business test event not yet verified")
        self.assertEqual((first.revision, revised.revision), (1, 2))
        self.assertEqual(GA4MeasurementReview.objects.filter(project=self.project).count(), 2)
        suspected = self.review(revision=2, event_quality_state="suspected_duplicate",
            instrumentation_notes="Manual review found a possible double count; verify the event stream.")
        self.assertEqual(suspected.event_quality_state, "suspected_duplicate")

    def test_wrong_actor_bad_mapping_and_source_revocation_fail_closed(self):
        with self.assertRaises(PermissionDenied):
            self.review(user=self.foreign)
        for definitions in (
            [{"goal": "Booking", "event_name": "purchase", "value_definition": ""},
             {"goal": "Booking", "event_name": "signup", "value_definition": ""}],
            [{"goal": "Booking", "event_name": "invalid space", "value_definition": ""}],
            [{"goal": "Booking", "event_name": "purchase", "value_definition": "", "secret": "untrusted"}],
        ):
            with self.subTest(definitions=definitions), self.assertRaises(ValidationError):
                self.review(definitions=definitions)
        with self.assertRaises(ValidationError):
            self.review(event_quality_state="suspected_missing", instrumentation_state="unverified",
                        instrumentation_notes="")
        self.assertFalse(GA4MeasurementReview.objects.exists())
        first = self.review()
        update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
        with self.assertRaises(ValidationError):
            self.review(revision=1)
        self.assertEqual(GA4MeasurementReview.objects.filter(pk=first.pk).count(), 1)

    def test_project_api_scopes_csrf_and_retains_historical_reviews_after_disconnect(self):
        path = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                f"/analytics/sources/{self.connection.pk}/quality/")
        def browser(actor):
            client = Client(enforce_csrf_checks=True)
            client.force_login(actor)
            client.get("/_allauth/browser/v1/auth/session")
            return client
        owner, foreign = browser(self.owner), browser(self.foreign)
        payload = {"expected_revision": 0, "definitions": [{"goal": "Qualified booking",
            "event_name": "purchase", "value_definition": "Unverified booking value"}],
            "instrumentation_state": "unverified", "instrumentation_notes": "",
            "event_quality_state": "not_checked",
            "attribution_notes": "Not established", "consent_notes": "Consent coverage unknown",
            "tracking_change_notes": "No known changes"}
        def post(client, csrf=True):
            return client.post(path + "reviews/", data=json.dumps(payload), content_type="application/json",
                **({"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}))
        self.assertEqual(post(owner, csrf=False).status_code, 403)
        self.assertEqual(post(foreign).status_code, 404)
        response = post(owner)
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["provider_instrumentation_verified"])
        self.assertEqual(post(owner).json()["review"]["id"], response.json()["review"]["id"])
        visible = owner.get(path)
        self.assertEqual(visible.status_code, 200)
        self.assertTrue(visible.json()["source_current"])
        self.assertIn("no-store", visible["Cache-Control"])
        self.assertEqual(visible.json()["reviews"][0]["property_id"], "12345")
        self.assertNotIn("REFRESH_SECRET", visible.content.decode())
        update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
        historical = owner.get(path)
        self.assertFalse(historical.json()["source_current"])
        self.assertEqual(len(historical.json()["reviews"]), 1)
        payload["expected_revision"] = 1
        self.assertEqual(post(owner).status_code, 409)
