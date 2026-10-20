from copy import deepcopy
import json

from django.test import SimpleTestCase

from .public_analytics_policy import parse_public_analytics_policy
from .public_analytics_source import CONSENT_VERSION, ERROR, METHOD, public_observation_source
from .test_public_analytics_policy import policy


def candidate():
    return {"dictionary_version": "acquisition-v1", "event_id": "public_page_view", "route_id": "HOME",
            "locale": "en", "consent_version": CONSENT_VERSION, "consent_state": "granted"}


class PublicAnalyticsSourceTests(SimpleTestCase):
    def setUp(self):
        self.content = json.dumps(policy()).encode()
        self.digest = parse_public_analytics_policy(self.content)[1]

    def source(self, value, **kwargs):
        return public_observation_source(value, policy_content=self.content,
                                         expected_policy_digest=self.digest, **kwargs)

    def test_actual_pinned_policy_page_and_route_specific_cta_are_minimized_fresh_sources_only(self):
        original = candidate()
        frozen = deepcopy(original)
        source = self.source(original, current_choice=True)
        self.assertEqual(source, {"method": METHOD, "dictionary_version": "acquisition-v1", "event_id": "public_page_view",
            "route_id": "HOME", "locale": "en", "consent_version": CONSENT_VERSION,
            "html_sha256": "a" * 64, "policy_digest": self.digest})
        self.assertEqual(original, frozen)
        original["route_id"] = "PRIVATE"
        self.assertEqual(source["route_id"], "HOME")
        cta = {**candidate(), "event_id": "public_cta_selected", "cta_id": "public_trial_cta", "locale": "tr"}
        source = self.source(cta, current_choice=True)
        self.assertEqual((source["cta_id"], source["html_sha256"]), ("public_trial_cta", "b" * 64))
        self.assertNotRegex(json.dumps(source), "origin|path|reviewer|history|occurred_at|actor|organization|customer|visitor")

    def test_client_flag_without_trusted_current_choice_and_missing_stale_malformed_policy_pin_deny(self):
        for choice in [False, None, 0, 1, "true", {}, {"allowed": True}]:
            with self.subTest(choice=choice), self.assertRaisesMessage(ValueError, ERROR):
                self.source(candidate(), current_choice=choice)
        with self.assertRaisesMessage(ValueError, ERROR):
            self.source(candidate())
        for pin in [None, "", "old", True, "f" * 64, self.digest.upper(), self.digest + "extra"]:
            with self.subTest(pin=pin), self.assertRaisesMessage(ValueError, ERROR):
                public_observation_source(candidate(), policy_content=self.content, expected_policy_digest=pin, current_choice=True)
        changed = policy(); changed["routes"][0]["html_sha256"] = "c" * 64
        for content in [None, b"", b"{}", b"\xff", json.dumps(changed).encode()]:
            with self.subTest(content=content), self.assertRaisesMessage(ValueError, ERROR):
                public_observation_source(candidate(), policy_content=content, expected_policy_digest=self.digest, current_choice=True)

    def test_exact_version_event_route_locale_cta_and_extra_secret_customer_properties_never_echo(self):
        bad = [None, [], {}, {**candidate(), "event_id": []}, {**candidate(), "event_id": "paid_activation_confirmed"},
               {**candidate(), "route_id": "UNKNOWN"}, {**candidate(), "route_id": "/account/reset#secret"},
               {**candidate(), "locale": "de"}, {**candidate(), "locale": []}, {**candidate(), "consent_state": "denied"},
               {**candidate(), "consent_version": "old"}, {**candidate(), "dictionary_version": "old"},
               {**candidate(), "cta_id": "public_trial_cta"}, {**candidate(), "event_id": "public_cta_selected"},
               {**candidate(), "event_id": "public_cta_selected", "cta_id": "other_route_cta"}]
        for key in ["occurred_at", "url", "path", "origin", "referrer", "campaign", "actor_id", "visitor_id", "email",
                    "project_id", "organization_id", "property_id", "customer_export", "password", "receipt_proof"]:
            bad.append({**candidate(), key: "private-secret-customer-value"})
        for value in bad:
            with self.subTest(value=value), self.assertRaisesMessage(ValueError, ERROR) as error:
                self.source(value, current_choice=True)
            self.assertEqual(str(error.exception), ERROR)
