import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import passive_header_source as verified_source
from . import passive_redirect_source as source
from . import passive_resource_source, passive_tls_source
from . import test_passive_header_source as fixtures


class PassiveRedirectSourceTests(TestCase):
    setUp = fixtures.PassiveHeaderSourceTests.setUp
    verified = fixtures.PassiveHeaderSourceTests.verified
    test_revocation_rotation_scope_lifecycle_and_restricted_access_remain_current = fixtures.PassiveHeaderSourceTests.test_revocation_rotation_scope_lifecycle_and_restricted_access_remain_current
    test_final_full_verification_scope_and_current_authority_drift_deny_without_writing = fixtures.PassiveHeaderSourceTests.test_final_full_verification_scope_and_current_authority_drift_deny_without_writing

    def bind(self, **changes):
        return source.passive_redirect_source(**{**dict(project=self.project, actor=self.owner,
            data={"url": self.project.canonical_origin + "/", "observations": ["response_location"],
                  "collection_permission": True}), **changes})

    def test_original_producer_minimized_independent_read_only_alias_and_expired_trial_not_capture(self):
        row = self.verified()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.bind()
        self.assertEqual((result["method_version"], result["observations"], result["verification_id"], result["verified_at"]),
            (source.METHOD, ["response_location"], row.pk, row.verified_at.isoformat()))
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        for private in (self.challenge, row.challenge_digest, self.owner.email, self.project.name, self.organization.name):
            self.assertNotIn(private, json.dumps(result))
        self.assertFalse({"location", "target", "target_url", "target_scheme", "same_origin"} & set(result))
        trial = self.organization.trial; trial.started_at = timezone.now() - timedelta(days=31); trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])
        self.assertEqual(self.bind(), result)
        alias = self.verified("https://www.security.example.com")
        selected = self.bind(data={"url": alias.origin + "/public", "observations": ["response_location"], "collection_permission": True})
        self.assertEqual(selected["verification_id"], alias.pk); self.assertNotEqual(selected["source_digest"], result["source_digest"])

    def test_other_families_union_targets_malformed_url_and_unverified_roles_never_authorize_location(self):
        with self.assertRaises(PermissionDenied): self.bind()
        self.verified()
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.bind(actor=actor)
        data = {"url": self.project.canonical_origin + "/", "observations": ["response_location"], "collection_permission": True}
        for changes in ({"collection_permission": 1}, {"collection_permission": False}, {"observations": ["response_headers"]},
            {"observations": ["certificate_dates", "negotiated_tls"]}, {"observations": ["static_resource_references"]},
            {"observations": ["response_location", "response_headers"]}, {"observations": ("response_location",)},
            {"location": "/public"}, {"same_origin": True}, {"origin": self.project.canonical_origin}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.bind(data={**data, **changes})
        for url in (None, True, "http://security.example.com/", "https://security.example.com:443/", "https://security.example.com:8443/",
            "https://user:private@security.example.com/", data["url"] + "?secret=private", data["url"] + "#private", data["url"] + "?",
            "https://security.example.com/a b", "HTTPS://SECURITY.EXAMPLE.COM/", "https://security.example.com/" + "x" * 1024):
            with self.subTest(url=url), self.assertRaises(ValidationError): self.bind(data={**data, "url": url})
        for url in ("https://competitor.example.invalid/", "https://www.security.example.com/"):
            with self.assertRaises(PermissionDenied): self.bind(data={**data, "url": url})
        for other in (verified_source, passive_tls_source, passive_resource_source):
            with self.assertRaises(ValidationError): other.validate_input(data)
