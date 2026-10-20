from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from tenancy.models import ProjectOriginVerification
from tenancy.services import create_organization, create_project, update_project

from .search_console_api import exact_scope_search_console_sites


class SearchConsolePropertySelectionTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("gsc-list-owner@example.com", password="test-password")
        self.outsider = users.create_user("gsc-list-other@example.com", password="test-password")
        for user in (self.owner, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="GSC property scope")
        self.project = create_project(
            organization=organization, user=self.owner, name="Scope",
            canonical_origin="https://gsc.example", aliases=["https://www.gsc.example"],
        )

    def select(self, entries, *, user=None):
        return exact_scope_search_console_sites(project=self.project, user=user or self.owner,
                                                 response={"siteEntry": entries})

    def test_only_exact_current_origins_with_eligible_google_permissions_are_selectable(self):
        result = self.select([
            {"siteUrl": "sc-domain:gsc.example", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://gsc.example/path/", "permissionLevel": "siteOwner"},
            {"siteUrl": " https://gsc.example/", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://gsc.example/", "permissionLevel": "siteUnverifiedUser"},
            {"siteUrl": "https://www.gsc.example/", "permissionLevel": "siteRestrictedUser"},
            {"siteUrl": "https://gsc.example/", "permissionLevel": "siteFullUser"},
            {"siteUrl": "HTTPS://GSC.EXAMPLE:443/", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://unrelated.example/", "permissionLevel": "siteOwner"},
        ])
        self.assertEqual(result["result_state"], "exact_scopes_listed")
        self.assertEqual(len(result["sites"]), 2)
        self.assertEqual(result["sites"][0], {
            "external_property_id": "https://gsc.example",
            "google_site_url": "HTTPS://GSC.EXAMPLE:443/", "permission_level": "siteOwner",
            "scope": "exact_origin_url_prefix", "access_evidence": "sites_list_only_not_verified_sync",
        })
        self.assertEqual(result["sites"][1]["external_property_id"], "https://www.gsc.example")
        self.assertEqual(result["skipped"], {"domain_wide": 1, "path_prefix_or_invalid": 2,
                                             "foreign_scope": 1, "unverified_or_unknown_permission": 1,
                                             "duplicate_property": 1})
        self.assertEqual(result["api_sync_status"], "not_verified")

    def test_foreign_actor_and_removed_alias_cannot_select_property(self):
        property_response = [{"siteUrl": "https://www.gsc.example/", "permissionLevel": "siteFullUser"}]
        with self.assertRaises(PermissionDenied):
            self.select(property_response, user=self.outsider)
        update_project(project=self.project, user=self.owner, aliases=[])
        result = self.select(property_response)
        self.assertEqual(result["sites"], [])
        self.assertEqual(result["result_state"], "no_accessible_exact_scope_property")
        self.assertEqual(result["skipped"]["foreign_scope"], 1)

    def test_bounded_response_and_malformed_entries_fail_closed(self):
        for payload in ({"siteEntry": "invalid"}, {"siteEntry": [{}]}, {"siteEntry": [{"siteUrl": 4, "permissionLevel": "siteOwner"}]},
                        {"siteEntry": [1]}, {"siteEntry": [{"siteUrl": "x" * (256 * 1024), "permissionLevel": "siteOwner"}]},
                        {"siteEntry": [{}] * 501}):
            with self.subTest(shape=str(type(payload["siteEntry"]))), self.assertRaises(ValidationError):
                exact_scope_search_console_sites(project=self.project, user=self.owner, response=payload)
        self.assertEqual(self.select([])["api_sync_status"], "not_verified")

    def test_domain_property_lists_only_current_verified_exact_origins_and_no_aggregates(self):
        property_response = [{"siteUrl": "sc-domain:gsc.example", "permissionLevel": "siteOwner"}]
        self.assertEqual(self.select(property_response)["sites"], [])
        for origin in (self.project.canonical_origin, "https://www.gsc.example"):
            ProjectOriginVerification.objects.create(
                organization=self.project.organization, project=self.project, origin=origin,
                challenge_digest="a" * 64, state=ProjectOriginVerification.State.VERIFIED,
                verified_at=timezone.now(),
            )
        result = self.select(property_response)
        self.assertEqual(result["result_state"], "scoped_properties_listed")
        self.assertEqual(result["sites"], [{
            "external_property_id": "sc-domain:gsc.example", "google_site_url": "sc-domain:gsc.example",
            "permission_level": "siteOwner", "scope": "verified_domain_page_only",
            "approved_origins": ["https://gsc.example", "https://www.gsc.example"],
            "available_dimensions": ["page"],
            "access_evidence": "sites_list_and_verified_exact_origins_not_verified_sync",
        }])
        with self.assertRaises(PermissionDenied):
            self.select(property_response, user=self.outsider)
        ProjectOriginVerification.objects.filter(project=self.project, origin="https://www.gsc.example").update(
            state=ProjectOriginVerification.State.REVOKED, revoked_at=timezone.now())
        self.assertEqual(self.select(property_response)["sites"][0]["approved_origins"], ["https://gsc.example"])
        update_project(project=self.project, user=self.owner, aliases=[])
        self.assertEqual(self.select(property_response)["sites"][0]["approved_origins"], ["https://gsc.example"])

    def test_domain_suffix_and_malformed_property_cannot_broaden_scope(self):
        ProjectOriginVerification.objects.create(
            organization=self.project.organization, project=self.project,
            origin=self.project.canonical_origin, challenge_digest="b" * 64,
            state=ProjectOriginVerification.State.VERIFIED, verified_at=timezone.now(),
        )
        result = self.select([
            {"siteUrl": "sc-domain:example", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:evilgsc.example", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:gsc.example.evil", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:gsc.example/path", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:gsc.example", "permissionLevel": "siteUnverifiedUser"},
            {"siteUrl": "sc-domain:gsc.example", "permissionLevel": "siteFullUser"},
        ])
        self.assertEqual(result["sites"][0]["approved_origins"], ["https://gsc.example"])
        self.assertEqual(result["sites"][0]["permission_level"], "siteFullUser")
        self.assertEqual(result["skipped"]["path_prefix_or_invalid"], 2)
        self.assertEqual(result["skipped"]["domain_wide"], 3)
