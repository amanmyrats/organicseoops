from copy import deepcopy
import json
from urllib.parse import parse_qs, urlsplit

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from jobs.local_assessment import review_local_business
from jobs.models import JobRun, LocalBusinessAssessment
from tenancy.models import MembershipRole, OrganizationMembership, Project, ProjectConfiguration, ProjectOriginVerification
from tenancy.services import create_organization, create_origin_verification, create_project, update_project
from .business_profile import (READ_MASK, require_account_location, require_business_authority,
    validate_accounts, validate_authorized_location, validate_location, validate_locations, validate_reviews)
from .business_profile_transport import (business_accounts_list, business_location_get,
                                        business_locations_list, business_reviews_list, read_authorized_business_profile)
from .search_console_transport import SearchConsoleTransportError
from .test_search_console_transport import FakeConnection, FakeResponse


def profile():
    return {"name": "locations/456", "title": "Synthetic business", "websiteUri": "https://local.example.invalid/office",
        "serviceArea": {"businessType": "CUSTOMER_LOCATION_ONLY"},
        "metadata": {"mapsUri": "https://maps.example.invalid/selected"}}


def reviews():
    return {"reviews": [{"name": "accounts/123/locations/456/reviews/review_1", "reviewId": "review_1",
        "starRating": "FIVE", "comment": "Untrusted <script>text</script>\nunchanged", "reviewer": {
            "displayName": "Synthetic reviewer", "profilePhotoUrl": "https://untrusted.example.invalid/photo"},
        "createTime": "2026-09-01T12:00:00.123456789Z", "updateTime": "2026-09-02T13:00:00Z",
        "reviewReply": {"comment": "Synthetic existing reply", "updateTime": "2026-09-02T14:00:00Z"}}],
        "averageRating": 4.5, "totalReviewCount": 200, "nextPageToken": "opaque-more-pages"}


class BusinessProfileTransportTests(SimpleTestCase):
    def fake(self, body, *, status=200, addresses=("8.8.8.8",)):
        response = FakeResponse(body if type(body) is bytes else json.dumps(body).encode(), status)
        transport = FakeConnection(response)
        seen = []
        def resolver(host, port, timeout):
            seen.append((host, port, timeout))
            return addresses
        def factory(scheme, address, host, port, deadline, clock):
            seen.append((scheme, address, host, port))
            return transport
        return {"access_token": "ACCESS_SECRET", "resolver": resolver, "connection_factory": factory}, transport, seen

    def test_fixed_read_hosts_required_mask_bounds_order_and_header_only_bearer(self):
        calls = (
            (business_accounts_list, {}, {"accounts": [{"name": "accounts/123", "accountName": "Synthetic account"}]},
             "mybusinessaccountmanagement.googleapis.com", "/v1/accounts", {"pageSize": ["20"]}),
            (business_locations_list, {"account_name": "accounts/123"}, {"locations": [profile()]},
             "mybusinessbusinessinformation.googleapis.com", "/v1/accounts/123/locations",
             {"pageSize": ["100"], "readMask": [READ_MASK]}),
            (business_location_get, {"location_name": "locations/456"}, profile(),
             "mybusinessbusinessinformation.googleapis.com", "/v1/locations/456", {"readMask": [READ_MASK]}),
            (business_reviews_list, {"account_name": "accounts/123", "location_name": "locations/456"}, reviews(),
             "mybusiness.googleapis.com", "/v4/accounts/123/locations/456/reviews", {"pageSize": ["50"]}),
        )
        for function, selection, payload, host, path, query in calls:
            with self.subTest(function=function.__name__):
                args, transport, seen = self.fake(payload)
                self.assertEqual(function(**selection, **args), payload)
                self.assertEqual(seen[1], ("https", "8.8.8.8", host, 443))
                self.assertEqual(len(transport.requests), 1)
                method, target, headers, body = transport.requests[0]
                self.assertEqual((method, urlsplit(target).path, body), ("GET", path, None))
                self.assertEqual(parse_qs(urlsplit(target).query), query)
                self.assertEqual(headers["Authorization"], "Bearer ACCESS_SECRET")
                self.assertNotIn("SECRET", target)
                self.assertTrue(transport.closed)
        payload = reviews()
        payload["reviews"].append({**payload["reviews"][0], "name": "accounts/123/locations/456/reviews/second",
                                   "reviewId": "second", "starRating": "ONE"})
        self.assertIs(validate_reviews(payload, account_name="accounts/123", location_name="locations/456"), payload)
        self.assertEqual([row["starRating"] for row in payload["reviews"]], ["FIVE", "ONE"])

    def test_path_injection_private_dns_remote_errors_invalid_json_and_size_fail_without_retry(self):
        for value in ("locations/456/../789", "https://evil.example/", "locations/456?key=x", "locations/456%2f789", True):
            args, transport, seen = self.fake(profile())
            with self.subTest(value=value), self.assertRaises(ValidationError):
                business_location_get(location_name=value, **args)
            self.assertEqual((seen, transport.requests), ([], []))
        for status, category in ((302, "redirect_denied"), (401, "authorization_unavailable"),
                                 (403, "authorization_unavailable"), (404, "property_unavailable"),
                                 (429, "quota_limited"), (503, "provider_unavailable")):
            args, transport, _ = self.fake(b'{"error":"ACCESS_SECRET private customer data"}', status=status)
            with self.subTest(status=status), self.assertRaises(SearchConsoleTransportError) as error:
                business_accounts_list(**args)
            self.assertEqual(error.exception.category, category)
            self.assertNotIn("SECRET", str(error.exception))
            self.assertEqual(len(transport.requests), 1)
            self.assertTrue(transport.closed)
        args, transport, _ = self.fake({}, addresses=("127.0.0.1",))
        with self.assertRaises(SearchConsoleTransportError) as error:
            business_accounts_list(**args)
        self.assertEqual(error.exception.category, "egress_denied")
        self.assertFalse(transport.requests)
        for body in (b'{"accounts":[],"accounts":[]}', b'{"count":NaN}', b'{"bad":"\xff"}', b' ' * (64 * 1024 + 1)):
            args, transport, _ = self.fake(body)
            with self.subTest(body_length=len(body)), self.assertRaises(SearchConsoleTransportError):
                business_accounts_list(**args)
            self.assertTrue(transport.closed)

    def test_schema_bounds_duplicate_foreign_review_identity_types_and_unchanged_attribution(self):
        payload = profile()
        payload["attribution"] = {"provider": "Google", "display": "Do not alter"}
        self.assertIs(validate_location(payload, location_name="locations/456"), payload)
        for payload in ({"accounts": [{"name": "accounts/123"}] * 2}, {"accounts": [{}]},
                        {"accounts": [{"name": f"accounts/{i}"} for i in range(21)]}):
            with self.assertRaises(ValidationError):
                validate_accounts(payload)
        for changes in ({"reviews": [reviews()["reviews"][0]] * 2}, {"averageRating": True},
                        {"totalReviewCount": 0}, {"totalReviewCount": 2**54}, {"reviews": [reviews()["reviews"][0]] * 51},
                        {"nextPageToken": "x" * 2049}, {"averageRating": float("nan")}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                validate_reviews({**reviews(), **changes}, account_name="accounts/123", location_name="locations/456")
        for changes in ({"name": "accounts/other/locations/456/reviews/review_1"}, {"starRating": []},
                        {"reviewId": "bad/path"}, {"createTime": "2026-09-01T12:00:00"},
                        {"comment": "\ud800"}, {"comment": "raw\x00text"}, {"reviewer": []},
                        {"comment": "x" * 8193}):
            payload = reviews()
            payload["reviews"][0].update(changes)
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                validate_reviews(payload, account_name="accounts/123", location_name="locations/456")
        self.assertEqual(validate_reviews({}, account_name="accounts/123", location_name="locations/456"), {})
        self.assertEqual(validate_reviews({"totalReviewCount": 0, "averageRating": 0},
                                         account_name="accounts/123", location_name="locations/456")["totalReviewCount"], 0)

    def test_first_page_membership_does_not_infer_missing_or_account_authority_from_location_get(self):
        accounts = {"accounts": [{"name": "accounts/123"}], "nextPageToken": "more"}
        locations = {"locations": [profile()], "nextPageToken": "more"}
        require_account_location(accounts=accounts, locations=locations, account_name="accounts/123", location_name="locations/456")
        for account, location in (("accounts/789", "locations/456"), ("accounts/123", "locations/789")):
            with self.assertRaises(PermissionDenied):
                require_account_location(accounts=accounts, locations=locations, account_name=account, location_name=location)
        with self.assertRaises(ValidationError):
            validate_locations({"locations": [profile(), profile()]})


class BusinessProfileAuthorityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("gbp-owner@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Synthetic local authority")
        self.project = create_project(organization=self.org, user=self.owner, name="Synthetic business",
                                      canonical_origin="https://local.example.invalid")
        self.config = ProjectConfiguration.objects.create(project=self.project, business_locations=["Synthetic office"],
            service_areas=["Synthetic area"], profile_urls=["https://maps.example.invalid/selected"],
            local_eligibility_notes="Owner attests eligibility; fixture is not provider evidence.")
        self.assessment = self.review()
        self.verification, _ = create_origin_verification(project=self.project, user=self.owner, origin=self.project.canonical_origin)
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="verified", verified_at=timezone.now())
        self.selection = {"account_name": "accounts/123", "location_name": "locations/456", "assessment_id": self.assessment.pk,
            "configuration_revision": self.config.revision, "origin": self.project.canonical_origin, "authorize_business": True}

    def review(self, **changes):
        data = dict(project=self.project, actor=self.owner, request_key="gbp-local-review-1", expected_config_revision=self.config.revision,
            location_label="Synthetic office", business_name="Synthetic business", address_display="Address deliberately undisclosed",
            phone="", hours="", services=["Synthetic service"], service_areas=["Synthetic area"],
            profile_url="https://maps.example.invalid/selected", eligibility="user_attested", review_theme="",
            evidence_note="Customer-only facts; not scraped or copied from API.", suggested_action="")
        return review_local_business(**{**data, **changes})

    def authorize(self, **changes):
        return require_business_authority(project=self.project, actor=self.owner, selection={**self.selection, **changes})

    def collect(self, *, responses=None, checkpoint=lambda: None, before_request=lambda _operation: None, clock=None):
        responses = responses or [{"accounts": [{"name": "accounts/123"}, {"name": "accounts/999", "accountName": "Sibling canary"}]},
            {"locations": [profile(), {**profile(), "name": "locations/999", "title": "Sibling canary"}], "nextPageToken": "more"}, reviews()]
        transports = []
        def factory(*_args):
            transport = FakeConnection(FakeResponse(json.dumps(responses[len(transports)]).encode()))
            transports.append(transport)
            return transport
        result = read_authorized_business_profile(project=self.project, actor=self.owner, selection=self.selection,
            access_token="ACCESS_SECRET", checkpoint=checkpoint, before_request=before_request,
            resolver=lambda *_args, **_kwargs: ("8.8.8.8",), connection_factory=factory,
            **({"clock": clock} if clock else {}))
        return result, transports

    def test_current_exact_customer_attested_source_read_is_metadata_free_without_any_write(self):
        payload = profile()
        before = deepcopy(payload)
        with CaptureQueriesContext(connection) as queries:
            source = validate_authorized_location(project=self.project, actor=self.owner, selection=self.selection, payload=payload)
        self.assertEqual(payload, before)
        self.assertEqual(set(source), {"assessment_id", "assessment_revision", "configuration_revision", "verification_id", "verified_at"})
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(JobRun.objects.count(), 0)
        self.assertEqual(LocalBusinessAssessment.objects.count(), 1)
        # Hidden customer-location-only address remains legitimate, not an inconsistency.
        self.assertNotIn("storefrontAddress", payload)

    def test_unknown_eligibility_foreign_viewer_false_authority_and_stale_revisions_fail(self):
        for changes in ({"authorize_business": False}, {"authorize_business": 1}, {"assessment_id": True},
                        {"account_name": "accounts/123/locations/456"}, {"extra": "raw content"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.authorize(**changes)
        viewer = get_user_model().objects.create_user("gbp-viewer@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=viewer, email=viewer.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.org, user=viewer, role=MembershipRole.VIEWER)
        with self.assertRaises(PermissionDenied):
            require_business_authority(project=self.project, actor=viewer, selection=self.selection)
        # Extra synthetic row isolates source checks; normal project creation retains its trial ceiling.
        foreign = Project.objects.create(organization=self.org, name="Synthetic foreign", canonical_origin="https://other.example.invalid")
        with self.assertRaises(PermissionDenied):
            require_business_authority(project=foreign, actor=self.owner, selection=self.selection)
        corrected = self.review(request_key="gbp-local-review-2", expected_revision=1, eligibility="unknown")
        with self.assertRaises(PermissionDenied):
            self.authorize()
        with self.assertRaises(PermissionDenied):
            self.authorize(assessment_id=corrected.pk)

    def test_revocation_reverification_config_scope_and_wrong_location_website_title_profile_fail(self):
        for changes in ({"name": "locations/789"}, {"title": "Another business"}, {"metadata": {"mapsUri": "https://maps.example.invalid/wrong"}},
                        {"websiteUri": "https://local.example.invalid.evil/"}, {"websiteUri": "http://local.example.invalid/"},
                        {"websiteUri": "https://user@local.example.invalid/"}, {"websiteUri": "https://local.example.invalid/?key=secret"},
                        {"websiteUri": "https://local.example.invalid:444/"}, {"websiteUri": None}):
            with self.subTest(changes=changes), self.assertRaises((ValidationError, PermissionDenied)):
                validate_authorized_location(project=self.project, actor=self.owner, selection=self.selection,
                                              payload={**profile(), **changes})
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.authorize()
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="verified", revoked_at=None, verified_at=timezone.now())
        self.authorize()
        self.config.revision += 1
        self.config.save(update_fields=["revision"])
        with self.assertRaises(PermissionDenied):
            self.authorize(configuration_revision=self.config.revision)
        self.config.revision -= 1
        self.config.save(update_fields=["revision"])
        update_project(project=self.project, user=self.owner, name=self.project.name, canonical_origin="https://changed.example.invalid")
        with self.assertRaises(PermissionDenied):
            self.authorize()  # stale caller Project is reloaded; removed origin is never silently retained.

    def test_ephemeral_collection_uses_exact_account_and_never_returns_or_stores_sibling_inventory(self):
        attempts = []
        with CaptureQueriesContext(connection) as queries:
            result, transports = self.collect(before_request=attempts.append)
        self.assertEqual(attempts, ["accounts_list", "locations_list", "reviews_list"])
        self.assertEqual(result["profile"], profile())
        self.assertEqual(result["reviews"], reviews())
        self.assertNotIn("Sibling canary", json.dumps(result))
        self.assertEqual([transport.requests[0][1].split("?")[0] for transport in transports],
            ["/v1/accounts", "/v1/accounts/123/locations", "/v4/accounts/123/locations/456/reviews"])
        self.assertEqual(result["coverage"], "first_page_only_not_complete_history")
        self.assertEqual((result["ranking"], result["device"], result["geolocation"], result["direct_writes"]),
                         ("unavailable", "unsupported", "unsupported", "unavailable"))
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(JobRun.objects.count(), 0)

    def test_source_or_actor_loss_between_calls_discards_evidence_and_stops_future_requests(self):
        attempts = []
        def revoke_before_review(operation):
            attempts.append(operation)
            if operation == "reviews_list":
                ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.collect(before_request=revoke_before_review)
        self.assertEqual(attempts, ["accounts_list", "locations_list", "reviews_list"])
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="verified", revoked_at=None)
        attempts.clear()
        def change_verification(operation):
            attempts.append(operation)
            if operation == "locations_list":
                ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(verified_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.collect(before_request=change_verification)
        self.assertEqual(attempts, ["accounts_list", "locations_list"])
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied):
            self.authorize()

    def test_caller_cancellation_deadline_and_missing_membership_never_retry_or_use_review_endpoint(self):
        attempts = []
        def cancel():
            if "locations_list" in attempts:
                raise PermissionDenied
        with self.assertRaises(PermissionDenied):
            self.collect(checkpoint=cancel, before_request=attempts.append)
        self.assertEqual(attempts, ["accounts_list", "locations_list"])
        attempts.clear()
        with self.assertRaises(PermissionDenied):
            self.collect(responses=[{"accounts": [], "nextPageToken": "unavailable-next-page"}], before_request=attempts.append)
        self.assertEqual(attempts, ["accounts_list"])
        attempts.clear()
        times = [0]
        def exceed_deadline(operation):
            attempts.append(operation)
            times[0] = 30
        with self.assertRaises(SearchConsoleTransportError) as error:
            self.collect(before_request=exceed_deadline, clock=lambda: times[0])
        self.assertEqual(error.exception.category, "timeout")
        self.assertEqual(attempts, ["accounts_list"])

    def test_selected_source_inputs_are_frozen_and_final_actor_revocation_withholds_collected_reviews(self):
        def mutate_caller_selection(operation):
            if operation == "locations_list":
                self.selection["account_name"] = "accounts/999"
        result, transports = self.collect(before_request=mutate_caller_selection)
        self.assertEqual(result["profile"]["name"], "locations/456")
        self.assertTrue(transports[-1].requests[0][1].startswith("/v4/accounts/123/locations/456/"))
        self.selection["account_name"] = "accounts/123"
        attempts, review_checks = [], []
        def revoke_after_reviews():
            if attempts and attempts[-1] == "reviews_list":
                review_checks.append(True)
                if len(review_checks) == 2:  # Second checkpoint occurs after the review response.
                    OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied):
            self.collect(checkpoint=revoke_after_reviews, before_request=attempts.append)
        self.assertEqual(attempts, ["accounts_list", "locations_list", "reviews_list"])
        self.assertEqual(JobRun.objects.count(), 0)
