from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from tenancy.services import create_organization, create_project, update_project

from .ga4_properties import eligible_ga4_property


class GA4PropertySelectionTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("ga4-owner@example.test", password="test-password")
        self.foreign = users.create_user("ga4-foreign@example.test", password="test-password")
        for user in (self.owner, self.foreign):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="GA4 fixture organization")
        self.project = create_project(organization=organization, user=self.owner, name="GA4 fixture",
                                      canonical_origin="https://site.example")
        self.property = {"name": "properties/12345", "propertyType": "PROPERTY_TYPE_ORDINARY",
                         "timeZone": "Europe/Istanbul", "currencyCode": "USD"}
        self.streams = {"dataStreams": [
            {"name": "properties/12345/dataStreams/456", "type": "WEB_DATA_STREAM",
             "webStreamData": {"defaultUri": "https://site.example/", "measurementId": "G-IGNORED"}},
            {"name": "properties/12345/dataStreams/789", "type": "WEB_DATA_STREAM",
             "webStreamData": {"defaultUri": "https://foreign.example/"}},
        ]}

    def select(self, **kwargs):
        return eligible_ga4_property(project=kwargs.pop("project", self.project),
            user=kwargs.pop("user", self.owner), property_id=kwargs.pop("property_id", "12345"),
            property_response=kwargs.pop("property_response", self.property),
            streams_response=kwargs.pop("streams_response", self.streams))

    def test_exact_project_stream_is_only_a_scoped_candidate(self):
        result = self.select()
        self.assertEqual(result["matched_origins"], ["https://site.example"])
        self.assertEqual((result["matching_stream_count"], result["other_stream_count"]), (1, 1))
        self.assertTrue(result["host_filter_required"])
        self.assertEqual(result["url_scheme_from_ga4_hostname"], "unknown")
        self.assertNotIn("foreign.example", str(result))
        self.assertNotIn("G-IGNORED", str(result))
        with self.assertRaises(PermissionDenied):
            self.select(user=self.foreign)
        update_project(project=self.project, user=self.owner, canonical_origin="https://new.example")
        with self.assertRaises(ValidationError):
            self.select()

    def test_alias_removal_and_foreign_or_incomplete_provider_inventory_fail_closed(self):
        update_project(project=self.project, user=self.owner, aliases=["https://alias.example"])
        response = {"dataStreams": [{"name": "properties/12345/dataStreams/456", "type": "WEB_DATA_STREAM",
                                      "webStreamData": {"defaultUri": "https://alias.example"}}]}
        self.assertEqual(self.select(streams_response=response)["matched_origins"], ["https://alias.example"])
        update_project(project=self.project, user=self.owner, aliases=[])
        with self.assertRaises(ValidationError):
            self.select(streams_response=response)
        for bad in (
            {**self.streams, "nextPageToken": "more"},
            {"dataStreams": [{"name": "properties/98765/dataStreams/456", "type": "WEB_DATA_STREAM",
                              "webStreamData": {"defaultUri": "https://site.example"}}]},
            {"dataStreams": [{"name": "properties/12345/dataStreams/456", "type": "WEB_DATA_STREAM",
                              "webStreamData": {"defaultUri": "https://site.example/path"}}]},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.select(streams_response=bad)
        with self.assertRaises(ValidationError):
            self.select(property_response={**self.property, "name": "properties/54321"})
