import json
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import Organization, OrganizationMembership, Project, ProjectMembership, ProjectOriginVerification
from tenancy.services import create_origin_verification, revoke_origin_verification, update_project
from . import passive_header_source as source
from .crawling import FetchResponse
from .security import execute_origin_verification, queue_origin_verification
from . import test_security as fixtures


class PassiveHeaderSourceTests(TestCase):
    setUp = fixtures.OriginVerificationTests.setUp

    def verified(self, origin=None):
        origin = origin or self.project.canonical_origin
        row, self.challenge = create_origin_verification(project=self.project, user=self.owner, origin=origin)
        job = queue_origin_verification(verification=row, actor=self.owner, idempotency_key=f"header-source-{row.pk}")
        fetcher = Mock()
        fetcher.fetch.side_effect = lambda url, before_request: (before_request(url), FetchResponse(url, 200, {}, self.challenge.encode()))[1]
        self.assertTrue(execute_origin_verification(job.pk, fetcher_factory=lambda scope: fetcher))
        row.refresh_from_db(); self.assertEqual(row.state, "verified")
        return row

    def bind(self, **changes):
        return source.passive_header_source(**{**dict(project=self.project, actor=self.owner,
            data={"url": self.project.canonical_origin + "/", "observations": ["response_headers"], "collection_permission": True}), **changes})

    def test_genuine_http_file_current_exact_alias_read_only_minimized_binding_not_commercial_authority(self):
        verified = self.verified()
        with patch("socket.create_connection", side_effect=AssertionError("network")), CaptureQueriesContext(connection) as queries:
            result = self.bind()
        self.assertEqual((result["verification_id"], result["verified_at"]), (verified.pk, verified.verified_at.isoformat()))
        self.assertIn("not_network_job_commercial", result["interpretation"])
        for private in (self.challenge, verified.challenge_digest, self.owner.email, self.project.name, self.organization.name):
            self.assertNotIn(private, json.dumps(result))
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        trial = self.organization.trial
        trial.started_at = timezone.now() - timedelta(days=31); trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])
        self.assertEqual(self.bind(), result)
        origin = "https://www.security.example.com"
        alias = self.verified(origin)
        bound = self.bind(data={"url": origin + "/public", "observations": ["response_headers"], "collection_permission": True})
        self.assertEqual(bound["verification_id"], alias.pk)
        self.assertNotEqual(bound["source_digest"], result["source_digest"])

    def test_unverified_roles_foreign_source_wrong_scheme_and_exact_named_permission_fail(self):
        with self.assertRaises(PermissionDenied): self.bind()
        self.verified()
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.bind(actor=actor)
        data = {"url": self.project.canonical_origin + "/", "observations": ["response_headers"], "collection_permission": True}
        for changes in ({"collection_permission": 1}, {"collection_permission": False}, {"observations": ["tls"]},
                {"observations": ["response_headers", "response_headers"]}, {"observations": ("response_headers",)}, {"extra": "private"}):
            with self.assertRaises(ValidationError): self.bind(data={**data, **changes})
        for url in ("http://security.example.com/", "https://security.example.com:8443/", "https://security.example.com/?token=private",
                "https://user:private@security.example.com/", "https://security.example.com/#private", "https://security.example.com/?",
                "https://security.example.com/a b", "HTTPS://SECURITY.EXAMPLE.COM/", "https://security.example.com:443/"):
            with self.assertRaises(ValidationError): self.bind(data={**data, "url": url})
        for url in ("https://competitor.example.invalid/", "https://www.security.example.com/"):
            with self.assertRaises(PermissionDenied): self.bind(data={**data, "url": url})

    def test_revocation_rotation_scope_lifecycle_and_restricted_access_remain_current(self):
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

    def test_final_full_verification_scope_and_current_authority_drift_deny_without_writing(self):
        row = self.verified()
        reader = source._source
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
                with patch.object(source, "_source", changed), self.assertRaises((PermissionDenied, ValidationError)): self.bind()
                transaction.set_rollback(True)
        for changes in ({"verified_at": timezone.now() + timedelta(days=1)}, {"verified_at": row.created_at - timedelta(seconds=1)},
                {"updated_at": timezone.now() + timedelta(days=1)}):
            with transaction.atomic():
                ProjectOriginVerification.objects.filter(pk=row.pk).update(**changes)
                with self.assertRaises(ValidationError): self.bind()
                transaction.set_rollback(True)
