import json
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings

from tenancy.models import MembershipRole, OrganizationMembership, ProjectConfiguration
from tenancy.services import create_organization, create_project

from .local_assessment import review_local_business
from .models import Finding, LocalBusinessAssessment


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                     "LOCATION": "local-business-fixtures"}})
class LocalBusinessAssessmentTests(TestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("local-owner@example.invalid", "Test passphrase 99!")
        self.outsider = users.create_user("local-other@example.invalid", "Test passphrase 99!")
        for actor in (self.owner, self.outsider):
            EmailAddress.objects.create(user=actor, email=actor.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Synthetic local business")
        self.project = create_project(organization=organization, user=self.owner,
                                      name="Synthetic office", canonical_origin="https://local.example.invalid")
        self.config = ProjectConfiguration.objects.create(project=self.project,
            business_locations=["Antalya example office"], service_areas=["Antalya region"],
            profile_urls=["https://profiles.example.invalid/ant"], business_hours="09:00–17:00")

    def review(self, **changes):
        values = dict(project=self.project, actor=self.owner, request_key="local-review-001",
                      expected_config_revision=self.config.revision, location_label="Antalya example office",
                      business_name="Synthetic airport transfer", address_display="Unverified customer-entered address",
                      phone="+90 555 000 0000", hours="09:00–17:00", services=["Airport transfers"],
                      service_areas=["Antalya region"], profile_url="https://profiles.example.invalid/ant",
                      eligibility="unknown", review_theme="", evidence_note="Owner entered these facts; no listing was fetched.",
                      suggested_action="Review an existing useful service page first.")
        values.update(changes)
        return review_local_business(**values)

    def test_current_manual_facts_are_immutable_not_verified_local_findings(self):
        first = self.review()
        self.assertEqual(first.revision, 1)
        self.assertEqual(first.eligibility, "unknown")
        self.assertEqual(self.review().pk, first.pk)
        self.assertEqual(Finding.objects.count(), 0)
        corrected = self.review(request_key="local-review-002", expected_revision=1,
                                evidence_note="Corrected customer-entered phone; listing remains unchecked.")
        self.assertEqual(corrected.revision, 2)
        self.assertEqual(LocalBusinessAssessment.objects.filter(project=self.project).count(), 2)
        with self.assertRaises(ValidationError):
            self.review(request_key="local-review-003", expected_revision=1)
        with self.assertRaises(ValidationError):
            first.save()

    def test_foreign_actor_unlisted_profile_and_missing_eligibility_notes_fail(self):
        with self.assertRaises(PermissionDenied):
            self.review(actor=self.outsider)
        with self.assertRaises(ValidationError):
            self.review(location_label="Invented second office")
        with self.assertRaises(ValidationError):
            self.review(service_areas=["Invented area"])
        with self.assertRaises(ValidationError):
            self.review(profile_url="https://unknown.example.invalid/listing")
        with self.assertRaises(ValidationError):
            self.review(eligibility="user_attested")
        self.config.local_eligibility_notes = "Owner has checked their own business eligibility requirements."
        self.config.save(update_fields=["local_eligibility_notes"])
        attested = self.review(request_key="local-review-004", eligibility="user_attested")
        self.assertEqual(attested.eligibility, "user_attested")
        self.config.revision += 1
        self.config.save(update_fields=["revision"])
        with self.assertRaises(ValidationError):
            self.review(request_key="local-review-005")

    def test_project_api_requires_csrf_role_and_current_config_for_history(self):
        prefix = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                  "/local-assessments/")
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        data = dict(request_key="local-api-001", expected_config_revision=self.config.revision,
            location_label="Antalya example office", business_name="Synthetic local business",
            address_display="Unverified owner statement", phone="", hours="09:00–17:00",
            services=["Airport transfers"], service_areas=["Antalya region"],
            profile_url="https://profiles.example.invalid/ant", eligibility="unknown", review_theme="",
            evidence_note="Entered by an authorized owner; profile not checked.", suggested_action="")
        self.assertEqual(owner.post(prefix, data=json.dumps(data), content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        def post(url, payload):
            return owner.post(url, data=json.dumps(payload), content_type="application/json",
                              HTTP_X_CSRFTOKEN=owner.cookies["csrftoken"].value)
        result = post(prefix, data)
        self.assertEqual(result.status_code, 201, result.content)
        row = result.json()["assessment"]
        self.assertTrue(row["source_current"])
        self.assertEqual(row["verification_state"], "manual_user_supplied_not_listing_or_provider_verified")
        self.assertEqual(post(prefix, data).json()["assessment"]["id"], row["id"])
        history_path = prefix + row["location_digest"] + "/"
        correction = {**data, "request_key": "local-api-002", "expected_revision": 1,
                      "evidence_note": "Revised user note; no listing or provider verification."}
        self.assertEqual(post(history_path, correction).json()["assessment"]["revision"], 2)
        self.assertEqual([review["revision"] for review in owner.get(history_path).json()["history"]], [2, 1])
        self.assertEqual(post(history_path, {**correction, "request_key": "local-api-003"}).status_code, 409)
        viewer = get_user_model().objects.create_user("local-viewer@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=viewer, email=viewer.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.project.organization, user=viewer,
                                              role=MembershipRole.VIEWER)
        readonly = Client()
        readonly.force_login(viewer)
        self.assertEqual(readonly.get(history_path).status_code, 200)
        self.assertEqual(readonly.post(history_path, data=json.dumps(correction), content_type="application/json").status_code, 403)
        foreign = Client()
        foreign.force_login(self.outsider)
        self.assertEqual(foreign.get(history_path).status_code, 404)
        self.config.revision += 1
        self.config.save(update_fields=["revision"])
        self.assertFalse(owner.get(history_path).json()["history"][0]["source_current"])
