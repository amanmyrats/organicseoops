from copy import deepcopy
from datetime import date, timedelta
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership
from tenancy.services import create_organization, create_project

from . import crux_episode_source as episodes, test_crux_threshold_policy as fixtures
from .models import Artifact, PerformanceObservationSnapshot, ProjectAlertEpisodeClaim, ProjectAlertDelivery, ProjectAlertPreference


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
class CruxEpisodeSourceTests(TransactionTestCase):
    setUp = fixtures.MaterialCruxSourceTests.setUp
    date_part = staticmethod(fixtures.MaterialCruxSourceTests.date_part)
    history = fixtures.MaterialCruxSourceTests.history
    collect = fixtures.MaterialCruxSourceTests.collect
    all_metrics = fixtures.MaterialCruxSourceTests.all_metrics

    def inspect(self, row):
        return episodes.current_material_crux_episodes(project=self.project, actor=self.owner, observation_id=row.pk)

    def test_genuine_recollection_changed_raw_values_metadata_keep_episode_not_pin_and_never_write_or_send(self):
        row = self.collect(self.all_metrics())
        with CaptureQueriesContext(connection) as queries, patch("http.client.HTTPSConnection.request", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            result = self.inspect(row)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        self.assertEqual([item["metric"] for item in result["episodes"]], ["LCP", "INP", "CLS"])
        keys = [item["episode_key"] for item in result["episodes"]]
        self.assertEqual(len(set(keys)), 3)
        self.assertTrue(all(len(key) == 69 and key.startswith("crux:") for key in keys))
        self.assertEqual(result["source_fingerprint"], self.inspect(row)["source_fingerprint"])
        self.assertNotIn("assessed_at", result["policy"])
        for private in (self.target, self.owner.email, row.raw_artifact.key, "performance_credential", "observed_key"):
            self.assertNotIn(private, json.dumps(result))
        changed = self.all_metrics(lcp=(2500, 3500), inp=(200, 300), cls=("0.10", "0.20"))
        changed["raw_only"] = "fixture variation"
        recollected = self.collect(changed, key="recollected")
        next_result = self.inspect(recollected)
        self.assertEqual(next_result["episodes"], result["episodes"])
        self.assertNotEqual(next_result["source_fingerprint"], result["source_fingerprint"])
        older_history = self.history((1000, 2500, 3000), count=3)
        older_history["record"]["metrics"]["interaction_to_next_paint"]["percentilesTimeseries"]["p75s"] = [100, 200, 250]
        older_history["record"]["metrics"]["cumulative_layout_shift"]["percentilesTimeseries"]["p75s"] = ["0.01", "0.10", "0.15"]
        extended = self.inspect(self.collect(older_history, key="extended-history"))
        self.assertEqual(extended["episodes"], result["episodes"])
        Artifact.objects.filter(pk=row.raw_artifact_id).update(created_at=row.raw_artifact.created_at + timedelta(microseconds=1))
        changed_metadata = self.inspect(row)
        self.assertEqual(changed_metadata["episodes"], result["episodes"])
        self.assertNotEqual(changed_metadata["source_fingerprint"], result["source_fingerprint"])
        self.assertFalse(ProjectAlertPreference.objects.exists())
        self.assertFalse(ProjectAlertDelivery.objects.exists())
        self.assertFalse(ProjectAlertEpisodeClaim.objects.exists())

    def test_actual_origin_fallback_and_direct_origin_and_normalized_page_equivalence(self):
        payload = self.all_metrics()
        payload["record"]["key"] = {"origin": self.project.canonical_origin, "formFactor": "PHONE"}
        fallback = self.inspect(self.collect(payload, key="page-fallback"))
        direct = self.inspect(self.collect(payload, key="direct-origin", grain="origin"))
        self.assertEqual(fallback["episodes"], direct["episodes"])
        self.assertNotEqual(fallback["source_fingerprint"], direct["source_fingerprint"])
        payload = self.all_metrics()
        literal = self.inspect(self.collect(payload, key="literal-page"))
        observed = self.target
        self.target = self.project.canonical_origin + "/requested-variant"
        payload["urlNormalizationDetails"] = {"originalUrl": self.target, "normalizedUrl": observed}
        normalized = self.inspect(self.collect(payload, key="normalized-page"))
        self.assertTrue(normalized["policy"]["source"]["url_normalization"] == "provider_normalized")
        self.assertEqual(literal["episodes"], normalized["episodes"])
        self.assertNotEqual(literal["episodes"], direct["episodes"])

    def test_actual_device_target_period_and_project_distinctions(self):
        first = self.inspect(self.collect(self.all_metrics()))["episodes"]
        payload = self.all_metrics(); payload["record"]["key"]["formFactor"] = "DESKTOP"
        desktop = self.inspect(self.collect(payload, key="desktop", strategy="desktop"))["episodes"]
        self.assertTrue(set(item["episode_key"] for item in first).isdisjoint(item["episode_key"] for item in desktop))
        self.target = self.project.canonical_origin + "/different-page"
        different_target = self.inspect(self.collect(self.all_metrics(), key="target"))["episodes"]
        self.assertNotEqual(first, different_target)
        self.target = self.project.canonical_origin + "/page"
        payload = self.all_metrics()
        for period in payload["record"]["collectionPeriods"]:
            for key in ("firstDate", "lastDate"):
                value = period[key]
                period[key] = self.date_part(date(value["year"], value["month"], value["day"]) - timedelta(days=7))
        different_period = self.inspect(self.collect(payload, key="period"))["episodes"]
        self.assertNotEqual(first, different_period)
        # Two genuinely authorized organizations may configure the same website; neither identity crosses scope.
        other = get_user_model().objects.create_user("crux-episode-other@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        organization = create_organization(user=other, name="Other episode source")
        project = create_project(organization=organization, user=other, name="Same site independent scope", canonical_origin=self.project.canonical_origin)
        self.owner, self.organization, self.project = other, organization, project
        different_project = self.inspect(self.collect(self.all_metrics(), key="project"))["episodes"]
        self.assertNotEqual(first, different_project)

    def test_ineligible_unknown_and_legacy_never_generate_or_reconstruct_an_episode(self):
        cases = [self.all_metrics(lcp=(2500, 2999), inp=(200, 201), cls=("0.10", "0.11")),
                 self.all_metrics(lcp=(1000, 2000), inp=(100, 200), cls=("0.01", "0.10")),
                 self.all_metrics(lcp=(0, 3000), inp=(0, 250), cls=("0", "0.15")),
                 self.all_metrics(lcp=(None, 3000), inp=(200, None), cls=("1E-100000", "0.15"))]
        incomparable = self.all_metrics()
        period = incomparable["record"]["collectionPeriods"][1]["firstDate"]
        incomparable["record"]["collectionPeriods"][1]["firstDate"] = self.date_part(date(period["year"], period["month"], period["day"]) + timedelta(days=1))
        cases.append(incomparable)
        for index, payload in enumerate(cases):
            with self.subTest(index=index):
                result = self.inspect(self.collect(payload, key=f"ineligible-{index}"))
                self.assertEqual(result["episodes"], [])
        mixed = self.inspect(self.collect(self.all_metrics(inp=(200, None), cls=("0.1", "0.11")), key="mixed"))
        self.assertEqual([item["metric"] for item in mixed["episodes"]], ["LCP"])
        row = self.collect(self.all_metrics(), key="legacy")
        PerformanceObservationSnapshot.objects.filter(pk=row.pk).update(raw_sha256=None)
        with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("legacy read")):
            result = self.inspect(row)
        self.assertEqual(result["episodes"], [])
        self.assertEqual(result["policy"]["state"], "unknown_original_raw_integrity")

    def test_current_full_source_reader_and_foreign_boundaries_after_episode_projection(self):
        row = self.collect(self.all_metrics())
        for invalid in (True, 0, -1, "1", 2**53):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                episodes.current_material_crux_episodes(project=self.project, actor=self.owner, observation_id=invalid)
        foreign = deepcopy(self.project); foreign.organization_id += 10000
        with self.assertRaises(PermissionDenied):
            episodes.current_material_crux_episodes(project=foreign, actor=self.owner, observation_id=row.pk)
        original = episodes._episodes
        for mutate in [lambda: Artifact.objects.filter(pk=row.raw_artifact_id).update(created_at=row.raw_artifact.created_at + timedelta(microseconds=1)),
                       lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")]:
            with transaction.atomic():
                def changed(source, material):
                    result = original(source, material); mutate(); return result
                with patch("jobs.crux_episode_source._episodes", side_effect=changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect(row)
                transaction.set_rollback(True)
        with patch("jobs.crux_history_source.read_private_artifact", return_value=b"corrupted"), self.assertRaises(ValidationError):
            self.inspect(row)
