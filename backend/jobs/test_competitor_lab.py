from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from . import competitor_lab as evidence
from .performance import LAB_AUDITS


URL = "https://competitor.example.invalid/selected/article"
REPORTED = "2026-01-01T00:00:00Z"


class CompetitorLabTests(SimpleTestCase):
    def payload(self, *, url=URL, strategy="mobile"):
        return {"id": url, "loadingExperience": {"overall_category": "FAST", "metrics": {"private_field": 1}},
            "originLoadingExperience": {"id": "https://foreign.example.invalid"},
            "lighthouseResult": {"requestedUrl": url, "finalUrl": url, "fetchTime": REPORTED, "lighthouseVersion": "12.5.0",
                "configSettings": {"formFactor": strategy}, "categories": {"performance": {"score": 0.75}, "accessibility": {"score": 0}},
                "audits": {"largest-contentful-paint": {"numericValue": 3000, "description": "private prose", "details": {"url": "https://private.example.invalid/?token=secret"}},
                    "cumulative-layout-shift": {"numericValue": 0.15}, "screenshot-thumbnails": {"data": "private image"}},
                "userAgent": "private-agent", "runWarnings": ["private-warning"], "i18n": {"private": "private@example.invalid"}}}

    def observe(self, payload=None, **changes):
        payload = self.payload() if payload is None else payload
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return evidence.observe_pagespeed_lab(**({"body": body, "body_complete": True, "url": URL,
            "strategy": "mobile", "received_at": timezone.now().isoformat(timespec="microseconds")} | changes))

    def test_original_exact_uri_device_dates_bytes_nullable_values_privacy_fresh_readback_and_no_io(self):
        payload = self.payload(); body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("builtins.open", side_effect=AssertionError("No files")), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No fetch")):
            result = self.observe(payload)
        self.assertEqual((result["method_version"], result["url"], result["strategy"], result["provider_reported_at"]),
            (evidence.METHOD, URL, "mobile", REPORTED))
        self.assertEqual((result["response_sha256"], result["response_size_bytes"]), (sha256(body).hexdigest(), len(body)))
        lab = result["lab"]
        self.assertEqual(lab["observed_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(lab["scores"], {"performance": 0.75, "accessibility": 0, "best-practices": None, "seo": None})
        self.assertEqual(lab["audits"]["largest-contentful-paint"], {"value": 3000, "unit": "ms", "state": "observed"})
        self.assertEqual(lab["audits"]["total-blocking-time"], {"value": None, "unit": "ms", "state": "unavailable"})
        self.assertEqual(lab["field_data"], "not_used")
        for private in ("private", "secret", "loadingExperience", "rankings_score", "source_current", "collection_permission", "artifact_id"):
            self.assertNotIn(private, json.dumps(result))
        encoded = evidence.encode_lab(result); stored = evidence.parse_lab(encoded); stored["lab"]["scores"]["performance"] = 0
        self.assertEqual(evidence.parse_lab(encoded), result)

    def test_mobile_desktop_zero_missing_runtime_whole_null_and_bounded_versions_remain_honest(self):
        for strategy in ("mobile", "desktop"):
            payload = self.payload(strategy=strategy); payload["lighthouseResult"]["categories"] = {}
            payload["lighthouseResult"]["audits"] = {key: {"numericValue": 0} for key in LAB_AUDITS}
            result = self.observe(payload, strategy=strategy)
            self.assertEqual(result["state"], "observed"); self.assertTrue(all(value is None for value in result["lab"]["scores"].values()))
            self.assertTrue(all(value["value"] == 0 and value["state"] == "observed" for value in result["lab"]["audits"].values()))
        payload = self.payload(); payload["lighthouseResult"]["runtimeError"] = {"code": "PRIVATE_SECRET", "message": "private provider response"}
        result = self.observe(payload)
        self.assertEqual((result["state"], result["reason"], result["lab"]), ("unavailable", "runtime_failed", None))
        self.assertEqual(result["provider_reported_at"], REPORTED); self.assertNotIn("PRIVATE_SECRET", json.dumps(result))
        for version in (None, "private secret", "9"*33 + ".0"):
            payload = self.payload(); payload["lighthouseResult"]["lighthouseVersion"] = version
            self.assertEqual(self.observe(payload)["lab"]["lighthouse_version"], "unknown")

    def test_exact_nonroot_original_uri_strategy_and_provider_dates_deny_without_scope_substitution(self):
        for key in ("id", "requestedUrl", "finalUrl"):
            for changed in (None, URL + "/", URL.replace("https:", "http:"), "https://competitor.example.invalid/", "https://own.example.invalid/page", URL + "?token=private"):
                payload = self.payload()
                target = payload if key == "id" else payload["lighthouseResult"]
                target[key] = changed
                with self.subTest(key=key, changed=changed), self.assertRaises(ValidationError): self.observe(payload)
        for url in ("https://competitor.example.invalid/", URL + "#", URL + "?", URL + "/%0a", "https://user:secret@competitor.example.invalid/a", "https://competitor.example.invalid:443/a"):
            with self.assertRaises(ValidationError): self.observe(self.payload(url=url), url=url)
        for strategy in (None, [], True, "tablet", "MOBILE"):
            with self.assertRaises(ValidationError): self.observe(strategy=strategy)
        for changed in (None, [], {}, {"formFactor": "desktop"}):
            payload = self.payload(); payload["lighthouseResult"]["configSettings"] = changed
            with self.assertRaises(ValidationError): self.observe(payload)
        for stamp in (None, "not a date", "2026-01-01T00:00:00", (timezone.now()+timedelta(days=1)).isoformat()):
            payload = self.payload(); payload["lighthouseResult"]["fetchTime"] = stamp
            with self.assertRaises(ValidationError): self.observe(payload)
        payload = self.payload(); payload["lighthouseResult"]["fetchTime"] = "2026-01-01T03:00:00+03:00"
        result = self.observe(payload); self.assertEqual(result["provider_reported_at"], "2026-01-01T03:00:00+03:00")
        self.assertEqual(result["lab"]["observed_at"], result["provider_reported_at"])
        with self.assertRaises(ValidationError): self.observe(received_at="2026-01-01T00:00:00Z")

    def test_complete_strict_utf8_duplicate_nonfinite_shape_and_body_limits_fail_closed(self):
        body = json.dumps(self.payload()).encode()
        for value in (b"", b"\xff", b"{} trailing", b"[]", b'{"id":"a","id":"b"}', b'{"ignored":NaN}', b'{"ignored":1e10000}', b"{"*10000,
            body + b" "*(evidence.MAX_BODY_BYTES-len(body)+1)):
            with self.subTest(size=len(value)), self.assertRaises(ValidationError): self.observe(body=value)
        for complete in (False, 1, None):
            with self.assertRaises(ValidationError): self.observe(body_complete=complete)
        for value in (None, bytearray(body), body.decode()):
            with self.assertRaises(ValidationError): self.observe(body=value)
        self.assertEqual(self.observe(body=body+b" "*(evidence.MAX_BODY_BYTES-len(body)))["response_size_bytes"], evidence.MAX_BODY_BYTES)
        for key in ("categories", "audits"):
            payload = self.payload(); payload["lighthouseResult"][key] = []
            with self.assertRaises(ValidationError): self.observe(payload)
        for value in (True, "0.5", -1, 1.1, float("inf")):
            payload = self.payload(); payload["lighthouseResult"]["categories"]["performance"]["score"] = value
            with self.assertRaises(ValidationError): self.observe(payload)
        for value in (True, "0", -1, 10_000_001, float("nan")):
            payload = self.payload(); payload["lighthouseResult"]["audits"]["largest-contentful-paint"]["numericValue"] = value
            with self.assertRaises(ValidationError): self.observe(payload)

    def test_closed_derived_dto_units_state_dates_scope_caps_and_old_source_method_exclusions(self):
        original = self.observe()
        mutations = [lambda r: r.update(method_version="competitor-static-dates-v1"), lambda r: r.update(source_current=True),
            lambda r: r.update(response_sha256="bad"), lambda r: r.update(response_size_bytes=True), lambda r: r.update(provider_reported_at="2026-01-01"),
            lambda r: r.update(state="observed", reason="valid"), lambda r: r.update(coverage="whole_site"), lambda r: r.update(interpretation="field_p75"),
            lambda r: r["lab"].update(final_url=URL + "/other"), lambda r: r["lab"].update(observed_at=r["received_at"]),
            lambda r: r["lab"].update(field_data="used"), lambda r: r["lab"].update(lighthouse_version="9"*40+".0"),
            lambda r: r["lab"]["scores"].update(performance=True), lambda r: r["lab"]["audits"]["largest-contentful-paint"].update(unit="seconds"),
            lambda r: r["lab"]["audits"]["total-blocking-time"].update(state="observed"), lambda r: r["lab"].update(raw_body="private"),
            lambda r: r.update(state="unavailable", reason="runtime_failed"), lambda r: r.update(state="unavailable", reason=[])]
        for change in mutations:
            result = deepcopy(original); change(result)
            with self.assertRaises(ValidationError): evidence.encode_lab(result)
        encoded = evidence.encode_lab(original)
        for value in (b"[]", b'{"method_version":"x","method_version":"y"}', encoded+b" "*evidence.MAX_RESULT_BYTES, b'{"value":NaN}'):
            with self.assertRaises(ValidationError): evidence.parse_lab(value)
        from .competitor_dates import validate_dates
        from .competitor_headings import validate_headings
        from .competitor_destinations import validate_destinations
        from .competitor_metadata import validate_metadata
        for old in (validate_dates, validate_headings, validate_destinations, validate_metadata):
            with self.assertRaises(ValidationError): old(original)

    def test_maximum_canonical_uri_stays_bounded_and_noncanonical_unicode_is_not_rewritten(self):
        prefix = "https://competitor.example.invalid/"
        url = prefix + "a"*(1024-len(prefix))
        result = self.observe(self.payload(url=url), url=url)
        self.assertEqual((result["state"], result["url"]), ("observed", url))
        self.assertLessEqual(len(evidence.encode_lab(result)), evidence.MAX_RESULT_BYTES)
        for invalid in (url+"a", prefix+"🙂"*900):
            with self.assertRaises(ValidationError): self.observe(self.payload(url=invalid), url=invalid)
