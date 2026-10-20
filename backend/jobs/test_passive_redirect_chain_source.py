import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import DomainAlias, Organization, OrganizationMembership, Project, ProjectMembership, ProjectOriginVerification
from tenancy.services import create_origin_verification, revoke_origin_verification, create_organization, create_project, update_project
from . import passive_header_source as verified_source
from . import passive_redirect_chain_source as source
from . import passive_http_redirect_source, passive_redirect_source
from . import test_passive_header_source as fixtures


class PassiveRedirectChainSourceTests(TestCase):
    verified = fixtures.PassiveHeaderSourceTests.verified

    def setUp(self):
        fixtures.PassiveHeaderSourceTests.setUp(self)
        self.https = self.project.canonical_origin
        self.http = "http://security.example.com"
        self.project = update_project(project=self.project, user=self.owner,
            aliases=[self.http, "https://www.security.example.com"])

    def input_data(self, **changes):
        return {"url": self.http + "/public", "target_urls": [self.https + "/public"],
            "observations": ["redirect_chain"], "collection_permission": True, **changes}

    def bind(self, **changes):
        return source.passive_redirect_chain_source(**{**dict(project=self.project, actor=self.owner,
            data=self.input_data()), **changes})

    def test_genuine_independent_origins_exact_selection_read_only_privacy_fresh_objects_and_expired_trial(self):
        http, https = self.verified(self.http), self.verified(self.https)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), CaptureQueriesContext(connection) as queries:
            result = self.bind()
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "actor_id", "url", "target_urls",
            "observations", "collection_permission", "origins", "source_digest", "interpretation"})
        self.assertEqual(result["method_version"], source.METHOD)
        self.assertEqual(result["origins"], [{"origin": row.origin, "verification_id": row.pk,
            "verified_at": row.verified_at.isoformat()} for row in (http, https)])
        for private in (self.challenge, http.challenge_digest, https.challenge_digest, self.owner.email, self.project.name, self.organization.name):
            self.assertNotIn(private, json.dumps(result))
        self.assertIn("not_observed_chain", result["interpretation"])
        changed_path = self.bind(data=self.input_data(target_urls=[self.https + "/other"]))
        self.assertNotEqual(result["source_digest"], changed_path["source_digest"])
        data = self.input_data(); mutable = self.bind(data=data)
        mutable["target_urls"].append(self.http + "/other"); mutable["origins"][0]["verification_id"] = 1
        mutable["observations"].append("response_location")
        self.assertEqual(data, self.input_data()); self.assertEqual(self.bind(), result)
        trial = self.organization.trial
        trial.started_at = timezone.now() - timedelta(days=31); trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])
        self.assertEqual(self.bind(), result)
        alias = self.verified("https://www.security.example.com")
        selected = self.bind(data=self.input_data(target_urls=[self.https + "/public", alias.origin + "/public"]))
        self.assertEqual(selected["origins"][-1]["verification_id"], alias.pk)
        targets = [self.http + f"/page-{index}" for index in range(source.MAX_TARGETS)]
        self.assertEqual(len(self.bind(data=self.input_data(target_urls=targets))["origins"]), 1)
        self.assertEqual(self.bind(data=self.input_data(target_urls=[]))["target_urls"], [])

    def test_every_origin_is_independently_configured_verified_and_same_project_with_current_manager(self):
        self.verified(self.https)
        with self.assertRaises(PermissionDenied): self.bind()
        self.verified(self.http)
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.bind(actor=actor)
        for target in ("https://foreign.example.invalid/public", "https://www.security.example.com/public"):
            with self.assertRaises(PermissionDenied): self.bind(data=self.input_data(target_urls=[target]))
        other_project = Project.objects.create(organization=self.organization, name="Other project", canonical_origin="https://other.example.invalid")
        other_org = create_organization(user=self.outsider, name="Other org")
        foreign = create_project(organization=other_org, user=self.outsider, name="Foreign", canonical_origin=self.https)
        for project in (other_project, foreign):
            with self.assertRaises(PermissionDenied): self.bind(project=project)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        membership.role = "admin"; membership.save(update_fields=["role"])
        self.assertEqual(self.bind(actor=self.member)["actor_id"], self.member.pk)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.bind(actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.bind(actor=self.member)["actor_id"], self.member.pk)

    def test_strict_named_permission_exact_bounded_urls_and_no_first_response_family_inheritance(self):
        malformed = ({"collection_permission": 1}, {"collection_permission": False}, {"observations": ["response_location"]},
            {"observations": ["http_response_location"]}, {"observations": ["redirect_chain", "response_location"]},
            {"observations": ("redirect_chain",)}, {"observations": ["redirect_chain"] * 2}, {"location": "/public"},
            {"target_urls": None}, {"target_urls": ()}, {"target_urls": [self.https + "/p"] * 6},
            {"target_urls": [self.http + "/public"]}, {"target_urls": [self.https + "/p"] * 2})
        with patch.object(verified_source, "_source", side_effect=AssertionError("Validate before source reads")):
            for changes in malformed:
                with self.subTest(changes=changes), self.assertRaises(ValidationError): self.bind(data=self.input_data(**changes))
            for url in (None, True, 3, {}, "http://security.example.com", "http://security.example.com:80/public",
                "https://security.example.com:443/public", "https://security.example.com:8443/public", "ftp://security.example.com/public",
                "HTTP://SECURITY.EXAMPLE.COM/public", "https://user:secret@security.example.com/public",
                self.https + "/?", self.https + "/#", self.https + "/?private=value", self.http + "/a b",
                self.https + "/" + "x" * 1024):
                for key in ("url", "target_urls"):
                    with self.subTest(url=url, key=key), self.assertRaises(ValidationError):
                        self.bind(data=self.input_data(**{key: [url] if key == "target_urls" else url}))
        for other in (verified_source, passive_http_redirect_source, passive_redirect_source):
            with self.assertRaises(ValidationError): other.validate_input(self.input_data())

    def test_every_selected_source_revocation_rotation_alias_lifecycle_and_hidden_metadata_drift_deny(self):
        rows = [self.verified(self.http), self.verified(self.https)]
        reader = verified_source._source
        mutations = [lambda row=row: revoke_origin_verification(verification=row, user=self.owner) for row in rows]
        mutations += [lambda row=row: create_origin_verification(project=self.project, user=self.owner, origin=row.origin) for row in rows]
        mutations += [lambda row=row: ProjectOriginVerification.objects.filter(pk=row.pk).update(updated_at=row.updated_at + timedelta(microseconds=1)) for row in rows]
        mutations += [lambda: DomainAlias.objects.filter(project=self.project, origin=self.http).delete(),
            lambda: Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://other.example.invalid"),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")]
        for mutate in mutations:
            with transaction.atomic():
                calls = 0
                def changed(*args):
                    nonlocal calls
                    result = reader(*args); calls += 1
                    # Change either original while the last target's slow first read completes.
                    if calls == len(rows): mutate()
                    return result
                with patch.object(verified_source, "_source", changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.bind()
                transaction.set_rollback(True)
        # A final slow metadata read must not conceal a newly removed manager.
        with transaction.atomic():
            calls = 0
            def removed(*args):
                nonlocal calls
                result = reader(*args); calls += 1
                if calls == 2 * len(rows):
                    OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")
                return result
            with patch.object(verified_source, "_source", removed), self.assertRaises(PermissionDenied): self.bind()
            transaction.set_rollback(True)
