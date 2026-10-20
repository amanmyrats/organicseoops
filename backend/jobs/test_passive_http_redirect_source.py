import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import DomainAlias, OrganizationMembership, Project, ProjectOriginVerification
from tenancy.services import update_project, create_project, create_organization
from . import passive_header_source as verified_source
from . import passive_http_redirect_source as source
from . import passive_redirect_source, passive_resource_source, passive_tls_source
from . import test_passive_header_source as fixtures


class PassiveHTTPRedirectSourceTests(TestCase):
    verified = fixtures.PassiveHeaderSourceTests.verified
    test_revocation_rotation_scope_lifecycle_and_restricted_access_remain_current = fixtures.PassiveHeaderSourceTests.test_revocation_rotation_scope_lifecycle_and_restricted_access_remain_current
    test_final_full_verification_scope_and_current_authority_drift_deny_without_writing = fixtures.PassiveHeaderSourceTests.test_final_full_verification_scope_and_current_authority_drift_deny_without_writing

    def setUp(self):
        fixtures.PassiveHeaderSourceTests.setUp(self)
        self.https_origin = self.project.canonical_origin
        self.project = update_project(project=self.project, user=self.owner, canonical_origin="http://security.example.com",
            aliases=[self.https_origin, "http://www.security.example.com"])

    def input_data(self, url=None):
        return {"url": url or self.project.canonical_origin + "/", "observations": ["http_response_location"], "collection_permission": True}

    def bind(self, **changes):
        return source.passive_http_redirect_source(**{**dict(project=self.project, actor=self.owner, data=self.input_data()), **changes})

    def test_genuine_configured_http_verifier_independent_source_read_only_privacy_alias_and_expiry(self):
        row = self.verified()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), CaptureQueriesContext(connection) as queries:
            result = self.bind()
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "actor_id", "origin", "url", "observations",
            "collection_permission", "verification_id", "verified_at", "source_digest", "interpretation"})
        self.assertEqual((result["method_version"], result["observations"], result["verification_id"], result["verified_at"]),
            (source.METHOD, ["http_response_location"], row.pk, row.verified_at.isoformat()))
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        for private in (self.challenge, row.challenge_digest, self.owner.email, self.project.name, self.organization.name):
            self.assertNotIn(private, json.dumps(result))
        self.assertIn("not_network_job_commercial", result["interpretation"])
        trial = self.organization.trial
        trial.started_at = timezone.now() - timedelta(days=31); trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])
        self.assertEqual(self.bind(), result)
        alias = self.verified("http://www.security.example.com")
        selected = self.bind(data=self.input_data(alias.origin + "/public"))
        self.assertEqual(selected["verification_id"], alias.pk)
        self.assertNotEqual(selected["source_digest"], result["source_digest"])
        selected["observations"].append("response_location")
        self.assertEqual(self.bind(data=self.input_data(alias.origin + "/public"))["observations"], ["http_response_location"])

    def test_https_verification_never_authorizes_http_and_http_never_authorizes_https_family(self):
        https = self.verified(self.https_origin)
        with self.assertRaises(PermissionDenied): self.bind()
        http = self.verified()
        self.assertNotEqual(http.pk, https.pk)
        self.assertEqual(self.bind()["verification_id"], http.pk)
        with self.assertRaises(ValidationError): self.bind(data=self.input_data(self.https_origin + "/"))
        for other in (verified_source, passive_redirect_source, passive_resource_source, passive_tls_source):
            with self.assertRaises(ValidationError): other.validate_input(self.input_data())
        # A valid HTTPS-family input still cannot inherit the independently verified HTTP row.
        ProjectOriginVerification.objects.filter(pk=https.pk).update(state="revoked", revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            passive_redirect_source.passive_redirect_source(project=self.project, actor=self.owner,
                data={"url": self.https_origin + "/", "observations": ["response_location"], "collection_permission": True})

    def test_strict_separate_permission_url_roles_and_foreign_project_org_deny(self):
        with self.assertRaises(PermissionDenied): self.bind()
        self.verified()
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.bind(actor=actor)
        for changes in ({"collection_permission": 1}, {"collection_permission": False}, {"observations": ["response_location"]},
            {"observations": ["response_headers"]}, {"observations": ["certificate_dates", "negotiated_tls"]},
            {"observations": ["static_resource_references"]}, {"observations": ["http_response_location", "response_location"]},
            {"observations": ("http_response_location",)}, {"observations": ["http_response_location"] * 2},
            {"origin": self.project.canonical_origin}, {"same_hostname_default_https": True}, {"target_url": self.https_origin}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.bind(data={**self.input_data(), **changes})
        for url in (None, True, 12, "http://security.example.com", "http://security.example.com:80/", "http://security.example.com:8080/",
            "HTTP://security.example.com/", "http://SECURITY.EXAMPLE.COM/", "http://user:secret@security.example.com/",
            "http://security.example.com/?", "http://security.example.com/#", "http://security.example.com/?secret=value",
            "http://security.example.com/a b", "http://security.example.com/" + "x" * 1024):
            with self.subTest(url=url), self.assertRaises(ValidationError): self.bind(data={**self.input_data(), "url": url})
        for url in ("http://foreign.example.invalid/", "http://www.security.example.com/"):
            with self.assertRaises(PermissionDenied): self.bind(data=self.input_data(url))
        other_project = Project.objects.create(organization=self.organization, name="Other project", canonical_origin="http://other.example.invalid")
        with self.assertRaises(PermissionDenied): self.bind(project=other_project)
        other_org = create_organization(user=self.outsider, name="Other org")
        foreign = create_project(organization=other_org, user=self.outsider, name="Foreign project", canonical_origin=self.project.canonical_origin)
        with self.assertRaises(PermissionDenied): self.bind(project=foreign)

    def test_selected_http_alias_identity_and_full_hidden_microseconds_are_bound_at_final_read(self):
        row = self.verified("http://www.security.example.com")
        data = self.input_data(row.origin + "/public")
        original = self.bind(data=data)
        reader = verified_source._source
        for mutate in (lambda: DomainAlias.objects.filter(project=self.project, origin=row.origin).update(origin="http://other.example.invalid"),
            lambda: ProjectOriginVerification.objects.filter(pk=row.pk).update(updated_at=row.updated_at + timedelta(microseconds=1)),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")):
            with transaction.atomic():
                calls = 0
                def changed(*args):
                    nonlocal calls
                    result = reader(*args); calls += 1
                    if calls == 1: mutate()
                    return result
                with patch.object(verified_source, "_source", changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.bind(data=data)
                transaction.set_rollback(True)
        ProjectOriginVerification.objects.filter(pk=row.pk).update(updated_at=row.updated_at + timedelta(microseconds=1))
        self.assertNotEqual(self.bind(data=data)["source_digest"], original["source_digest"])
