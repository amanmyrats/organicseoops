import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import Organization, OrganizationMembership, Project, ProjectMembership, ProjectOriginVerification
from tenancy.services import create_origin_verification, revoke_origin_verification, update_project
from . import passive_header_source as verified_source
from . import passive_tls_source as source
from . import test_passive_header_source as fixtures


class PassiveTLSSourceTests(TestCase):
    setUp = fixtures.PassiveHeaderSourceTests.setUp
    verified = fixtures.PassiveHeaderSourceTests.verified

    def bind(self, **changes):
        return source.passive_tls_source(**{**dict(project=self.project, actor=self.owner,
            data={"origin": self.project.canonical_origin, "observations": ["certificate_dates", "negotiated_tls"],
                  "collection_permission": True}), **changes})

    def test_genuine_current_origin_alias_minimized_read_only_and_not_commercial_authority(self):
        verified = self.verified()
        with patch("socket.create_connection", side_effect=AssertionError("network")), CaptureQueriesContext(connection) as queries:
            result = self.bind()
        self.assertEqual((result["verification_id"], result["verified_at"]), (verified.pk, verified.verified_at.isoformat()))
        self.assertEqual(result["observations"], ["certificate_dates", "negotiated_tls"])
        self.assertEqual(result["method_version"], source.METHOD)
        self.assertNotIn("url", result)
        for private in (self.challenge, verified.challenge_digest, self.owner.email, self.project.name, self.organization.name):
            self.assertNotIn(private, json.dumps(result))
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        trial = self.organization.trial
        trial.started_at = timezone.now() - timedelta(days=31); trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])
        self.assertEqual(self.bind(), result)
        origin = "https://www.security.example.com"
        alias = self.verified(origin)
        data = {"origin": origin, "observations": ["certificate_dates", "negotiated_tls"], "collection_permission": True}
        bound = self.bind(data=data)
        self.assertEqual(bound["verification_id"], alias.pk)
        self.assertNotEqual(bound["source_digest"], result["source_digest"])

    def test_independent_exact_permission_and_current_verified_scope_are_required(self):
        with self.assertRaises(PermissionDenied): self.bind()
        self.verified()
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.bind(actor=actor)
        data = {"origin": self.project.canonical_origin, "observations": ["certificate_dates", "negotiated_tls"], "collection_permission": True}
        for changes in ({"collection_permission": 1}, {"collection_permission": False}, {"observations": ["response_headers"]},
            {"observations": ["negotiated_tls", "certificate_dates"]}, {"observations": ["certificate_dates"]},
            {"observations": ("certificate_dates", "negotiated_tls")}, {"extra": "private"}):
            with self.assertRaises(ValidationError): self.bind(data={**data, **changes})
        header_input = {"url": data["origin"] + "/", "observations": ["response_headers"], "collection_permission": True}
        with self.assertRaises(ValidationError): self.bind(data=header_input)
        with self.assertRaises(ValidationError): verified_source.validate_input(data)
        for origin in ("http://security.example.com", "https://security.example.com/", "https://security.example.com/public",
            "https://security.example.com:443", "https://security.example.com:8443", "https://user:private@security.example.com",
            "https://security.example.com?", "https://security.example.com#private", "HTTPS://SECURITY.EXAMPLE.COM", None, True):
            with self.subTest(origin=origin), self.assertRaises(ValidationError): self.bind(data={**data, "origin": origin})
        for origin in ("https://competitor.example.invalid", "https://www.security.example.com"):
            with self.assertRaises(PermissionDenied): self.bind(data={**data, "origin": origin})

    def test_revocation_rotation_scope_lifecycle_and_restricted_admin_remain_current(self):
        row = self.verified()
        for mutate in (lambda: revoke_origin_verification(verification=row, user=self.owner),
            lambda: create_origin_verification(project=self.project, user=self.owner, origin=row.origin),
            lambda: update_project(project=self.project, user=self.owner, canonical_origin="https://other.example.invalid"),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")):
            with transaction.atomic():
                mutate()
                with self.assertRaises((PermissionDenied, ValidationError)): self.bind()
                transaction.set_rollback(True)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        membership.role = "admin"; membership.save(update_fields=["role"])
        self.assertEqual(self.bind(actor=self.member)["actor_id"], self.member.pk)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.bind(actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.bind(actor=self.member)["actor_id"], self.member.pk)

    def test_final_full_original_verification_scope_and_actor_drift_deny(self):
        row = self.verified()
        reader = verified_source._source
        for mutate in (lambda: ProjectOriginVerification.objects.filter(pk=row.pk).update(challenge_digest="a" * 64),
            lambda: ProjectOriginVerification.objects.filter(pk=row.pk).update(updated_at=row.updated_at + timedelta(microseconds=1)),
            lambda: Project.objects.filter(pk=self.project.pk).update(access_restricted=True),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")):
            with transaction.atomic():
                calls = 0
                def changed(*args):
                    nonlocal calls
                    result = reader(*args); calls += 1
                    if calls == 1: mutate()
                    return result
                with patch.object(verified_source, "_source", changed), self.assertRaises((PermissionDenied, ValidationError)): self.bind()
                transaction.set_rollback(True)
