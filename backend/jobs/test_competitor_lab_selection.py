from datetime import timedelta
from hashlib import sha256
import json
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from providers.models import OrganizationPerformanceKey, PerformanceAPIKey
from providers.performance_key import performance_key_reference, set_organization_performance_key, revoke_organization_performance_key
from tenancy.models import OrganizationMembership, ProjectConfiguration
from . import competitor_lab_selection as selection, competitor_lab_source as source
from . import test_competitor_lab_source as fixtures
from .models import CrawlRun, JobRun, PerformanceObservationSnapshot, UsageReservation


KEY = Fernet.generate_key().decode()
SECRET = "fixture_org_key_with_32_characters"


@override_settings(PERFORMANCE_ENCRYPTION_KEYS=(KEY,), GOOGLE_PERFORMANCE_API_KEY="")
class CompetitorLabSelectionTests(TestCase):
    setUp = fixtures.CompetitorLabSourceTests.setUp
    data = fixtures.CompetitorLabSourceTests.data

    def read(self, *, actor=None, project=None, **changes):
        return selection.selection_snapshot(project=project or self.project, actor=actor or self.owner, data=self.data(**changes))

    def set_key(self):
        return set_organization_performance_key(actor=self.owner, organization=self.organization, value=SECRET)

    def platform(self, **changes):
        return PerformanceAPIKey.objects.create(encrypted_secret="v1:" + Fernet(KEY.encode()).encrypt(b"fixture_platform_key_with_32_chars").decode(),
            rotated_at=timezone.now(), **changes)

    def test_original_environment_unverified_source_digest_private_copy_no_secret_resolution_writes_or_io(self):
        with (patch("providers.performance_key.google_performance_key", side_effect=AssertionError("No resolution")),
            patch("providers.performance_key._cipher", side_effect=AssertionError("No decryption")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
            patch("jobs.performance_transport.google_performance_request", side_effect=AssertionError("No provider")), CaptureQueriesContext(connection) as queries):
            result = self.read()
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(set(result), {"method_version", "source", "performance_credential", "interpretation", "selection_sha256"})
        self.assertEqual(result["method_version"], selection.METHOD)
        self.assertEqual(result["source"], source.current_competitor_lab_source(project=self.project, actor=self.owner, data=self.data()))
        self.assertEqual(result["performance_credential"], {"source":"environment", "revision":"", "state":"unverified"})
        encoded = json.dumps({key:value for key,value in result.items() if key != "selection_sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        self.assertEqual(result["selection_sha256"], sha256(encoded).hexdigest()); self.assertLess(len(json.dumps(result).encode()), selection.MAX_RESULT_BYTES)
        for private in (SECRET, "encrypted_secret", "api_key", "Private customer prose", self.owner.email, "second.example.invalid", '"key_valid"', '"provider_ready"' ):
            self.assertNotIn(private, json.dumps(result))
        for model in (JobRun, CrawlRun, UsageReservation, PerformanceObservationSnapshot): self.assertFalse(model.objects.exists())
        result["source"]["strategy"]="changed"; result["performance_credential"]["state"]="changed"
        self.assertEqual(self.read()["source"]["strategy"], "mobile"); self.assertEqual(self.read()["performance_credential"]["state"], "unverified")
        with override_settings(GOOGLE_PERFORMANCE_API_KEY="private_environment_key_with_32_chars"):
            self.assertEqual(self.read()["performance_credential"], {"source":"environment", "revision":"", "state":"unverified"})

    def test_actual_platform_org_precedence_revoked_no_fallback_and_active_is_not_decryption_proof(self):
        platform=self.platform(); platform_result=self.read()
        self.assertEqual(platform_result["performance_credential"], performance_key_reference(organization=self.organization))
        self.assertEqual(platform_result["performance_credential"]["source"], "platform")
        record=self.set_key(); original=self.read()
        self.assertEqual(original["performance_credential"]["source"], "organization")
        self.assertNotEqual(original["selection_sha256"], platform_result["selection_sha256"])
        with patch("providers.performance_key._cipher", side_effect=AssertionError("Metadata only")):
            self.assertEqual(self.read(), original)
        OrganizationPerformanceKey.objects.filter(pk=record.pk).update(encrypted_secret="v1:invalid-ciphertext")
        self.assertEqual(self.read(), original)
        OrganizationPerformanceKey.objects.filter(pk=record.pk).update(rotated_at=timezone.now().replace(microsecond=0))
        self.assertEqual(self.read()["performance_credential"], performance_key_reference(organization=self.organization))
        self.assertNotEqual(self.read()["selection_sha256"],original["selection_sha256"])
        revoke_organization_performance_key(actor=self.owner, organization=self.organization)
        with override_settings(GOOGLE_PERFORMANCE_API_KEY="private_environment_key_with_32_chars"), self.assertRaises(ValidationError): self.read()
        record.delete(); PerformanceAPIKey.objects.filter(pk=platform.pk).update(state="revoked", encrypted_secret="")
        with self.assertRaises(ValidationError): self.read()

    def test_current_actor_device_uri_configuration_and_key_rotation_change_original_digest(self):
        original=self.read()
        for changes in ({"strategy":"desktop"}, {"url":self.data()["origin"]+"/other"}, {"actor":self.admin}):
            self.assertNotEqual(self.read(**changes)["selection_sha256"], original["selection_sha256"])
        self.set_key(); keyed=self.read(); self.set_key()
        self.assertNotEqual(self.read()["selection_sha256"], keyed["selection_sha256"])
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data()["origin"],"https://changed.example.invalid"])
        self.assertNotEqual(self.read()["selection_sha256"], original["selection_sha256"])
        with self.assertRaises(PermissionDenied): self.read(actor=self.foreign)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.read(actor=self.admin)

    def test_last_projection_rechecks_actual_key_revision_revocation_scope_and_complete_source(self):
        record=self.set_key(); original=selection.sha256
        for change in (
            lambda: OrganizationPerformanceKey.objects.filter(pk=record.pk).update(rotated_at=timezone.now()),
            lambda: OrganizationPerformanceKey.objects.filter(pk=record.pk).update(state="revoked",encrypted_secret=""),
            lambda: OrganizationPerformanceKey.objects.filter(pk=record.pk).delete(),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data()["origin"],"https://changed.example.invalid"]),
            lambda: OrganizationMembership.objects.filter(organization=self.organization,user=self.owner).update(role="admin")):
            with self.subTest(change=change), transaction.atomic():
                def changed(content):
                    result=original(content);change();return result
                with patch.object(selection,"sha256",side_effect=changed), self.assertRaises((PermissionDenied, ValidationError)): self.read()
                transaction.set_rollback(True)
        record.delete()
        for change in (self.platform, self.set_key):
            with self.subTest(change=change), transaction.atomic():
                def changed(content):
                    result=original(content);change();return result
                with patch.object(selection,"sha256",side_effect=changed), self.assertRaises(PermissionDenied): self.read()
                transaction.set_rollback(True)

    def test_strict_reference_dates_shape_state_and_invalid_input_before_key_read(self):
        now=timezone.now().isoformat(timespec="microseconds")
        malformed=[None,[],{}, {"source":"platform","revision":now,"state":"active","api_key":SECRET}]
        malformed += [{"source":value,"revision":now,"state":"active"} for value in (None,[],"foreign")]
        malformed += [{"source":"platform","revision":value,"state":"active"} for value in (None,[],"",now.replace("+00:00",""),(timezone.now()+timedelta(days=1)).isoformat())]
        malformed += [{"source":"platform","revision":now,"state":value} for value in (None,[],"revoked","unverified")]
        malformed += [{"source":"environment","revision":now,"state":"unverified"},{"source":"environment","revision":"","state":"active"}]
        for value in malformed:
            with self.subTest(value=value), patch.object(selection,"performance_key_reference",return_value=value), self.assertRaises(ValidationError): self.read()
        for data in (self.data(provider_processing_permission=False),self.data(api_key=SECRET),self.data(strategy="tablet")):
            with patch.object(selection,"performance_key_reference",side_effect=AssertionError("Invalid input before key")), self.assertRaises(ValidationError):
                selection.selection_snapshot(project=self.project,actor=self.owner,data=data)

    def test_caller_input_is_frozen_at_last_digest_without_changing_original_selection(self):
        data=self.data();expected=self.read();original=selection.sha256
        def changed(content):
            result=original(content);data.update(strategy="tablet",provider_processing_permission=False);return result
        with patch.object(selection,"sha256",side_effect=changed):
            self.assertEqual(selection.selection_snapshot(project=self.project,actor=self.owner,data=data),expected)
        with self.assertRaises(ValidationError): selection.selection_snapshot(project=self.project,actor=self.owner,data=data)
