from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collector
from . import test_passive_redirect_chain_candidates as fixtures
from .models import Finding, JobRun, Opportunity, Recommendation, UsageReservation
from .passive_redirect_chain_findings import CONFIDENCE, FIELDS, METHOD, redirect_chain_finding_values


class RedirectChainFindingRecipeTests(SimpleTestCase):
    def setUp(self):
        self.original = fixtures.RedirectChainCandidateTests()
        self.original.setUp()
        self.addCleanup(self.original.doCleanups)

    def recipes(self, observation, *, job_id=7, binding=None):
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No private I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")), patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")):
            return redirect_chain_finding_values(job_id=job_id, binding=binding or self.original.binding, observation=observation)

    def test_exact_compact_original_identity_all_capture_dates_status_and_full_binding_collection_hashes(self):
        urls = ["https://example.com/public", "http://example.com/public", "https://example.com/other", "http://example.com/other"]
        observation = self.original.result(urls)
        original = deepcopy((observation, self.original.binding))
        rows = self.recipes(observation)
        self.assertEqual(len(rows), 1)
        row = rows[0]; evidence = row["evidence"]
        self.assertEqual(set(row), set(FIELDS))
        self.assertEqual((row["source_passive_redirect_chain_id"], row["subject"], row["method_version"], row["confidence"]), (7, urls[0], METHOD, CONFIDENCE))
        self.assertEqual(set(evidence), {"source", "job_id", "binding", "binding_sha256", "collection_sha256", "observed_at", "last_observed_at",
            "captures", "availability", "fact", "coverage", "interpretation"})
        self.assertEqual(set(evidence["binding"]), {"method_version", "organization_id", "project_id", "actor_id", "source_digest", "observations", "collection_permission"})
        self.assertEqual(evidence["source"], "passive_exact_selected_redirect_chain")
        self.assertEqual(evidence["binding_sha256"], sha256(lifecycle._encode(self.original.binding)).hexdigest())
        self.assertEqual(evidence["collection_sha256"], sha256(lifecycle._encode(observation)).hexdigest())
        self.assertEqual(evidence["captures"], [{"hop": i, "scheme": "https" if i % 2 == 0 else "http", "status": 200 if i == 3 else 302,
            "observed_at": observation["evidence"]["hops"][i]["observed_at"]} for i in range(4)])
        self.assertEqual((evidence["observed_at"], evidence["last_observed_at"]), (observation["observed_at"], observation["last_observed_at"]))
        self.assertEqual(evidence["fact"], {"transitions": [{"from_hop": 0, "to_hop": 1}, {"from_hop": 2, "to_hop": 3}]})
        self.assertEqual(row["fingerprint"], sha256(lifecycle._encode([METHOD, row["detector"], evidence])).hexdigest())
        for private in ("target_urls", "raw_location", "raw_body", "source_current", '"priority":', '"severity":', '"score":'):
            self.assertNotIn(private, json.dumps(rows))
        evidence["binding"]["observations"].append("raw")
        evidence["captures"][0]["status"] = 599
        evidence["fact"]["transitions"].clear()
        self.assertEqual((observation, self.original.binding), original)
        self.assertEqual(self.recipes(observation)[0]["fingerprint"], row["fingerprint"])

    def test_actual_loop_budget_unknown_null_terminal_outside_and_unvisited_facts_never_infer_false_transitions_or_clean(self):
        for fields, status, detector in ((b"Location: /public\r\n", 302, "redirect_chain_loop_stop_candidate"),
            (b"", 302, None), (b"Location: \t\r\n", 302, None), (b"Location: /one\r\nLocation: /two\r\n", 302, None),
            (b"Location: javascript:private\r\n", 302, None), (b"Location: https://example.com/public?\r\n", 302, None),
            (b"Location: http://foreign.invalid/private\r\n", 302, None), (b"Location: http://foreign.invalid/private\r\n", 200, None)):
            observation = self.original.result(["https://example.com/public"], fields=fields, status=status)
            rows = self.recipes(observation)
            self.assertEqual([row["detector"] for row in rows], [detector] if detector else [])
            self.assertNotIn("foreign.invalid", json.dumps(rows))
            if rows: self.assertEqual(rows[0]["evidence"]["fact"], {"state": "redirect_loop", "observed_hops": 1, "last_hop": 0})
        observation = self.original.result(["https://example.com/public", "http://example.com/public"], max_redirects=0)
        rows = self.recipes(observation)
        self.assertEqual([row["detector"] for row in rows], ["redirect_chain_budget_stop_candidate"])
        self.assertEqual(rows[0]["evidence"]["fact"], {"state": "redirect_limit", "observed_hops": 1, "last_hop": 0})
        self.assertEqual(rows[0]["evidence"]["availability"], {"selected_urls": 2, "observed_hops": 1, "last_target_metadata": "observed"})

    def test_maximum_six_1024_character_selected_paths_two_compact_facts_keep_4k_limit_and_every_original_identity(self):
        urls = [("https" if index % 2 == 0 else "http") + "://example.com/" for index in range(6)]
        urls = [prefix + str(index) * (1024 - len(prefix)) for index, prefix in enumerate(urls)]
        observation = self.original.result(urls, fields=f"Location: {urls[0]}\r\n".encode(), status=302)
        self.assertGreater(len(lifecycle._encode(observation)), 8192)
        binding = deepcopy(self.original.binding)
        for key in ("organization_id", "project_id", "actor_id"): binding[key] = 2**53 - 1
        rows = self.recipes(observation, job_id=2**53 - 1, binding=binding)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row["subject"]), 1024)
            self.assertLessEqual(len(lifecycle._encode(row["evidence"])), 4096)
            self.assertEqual(len(row["evidence"]["captures"]), 6)
            self.assertEqual(row["evidence"]["binding_sha256"], sha256(lifecycle._encode(binding)).hexdigest())
        self.assertEqual(rows[1]["evidence"]["fact"], {"state": "redirect_loop", "observed_hops": 6, "last_hop": 5})
        for changes in ({"actor_id": 7}, {"source_digest": "c" * 64}, {"target_urls": list(reversed(binding["target_urls"]))}):
            changed = self.recipes(observation, job_id=2**53 - 1, binding={**binding, **changes})
            self.assertNotEqual(rows[0]["fingerprint"], changed[0]["fingerprint"])
        self.assertNotEqual(rows[0]["fingerprint"], self.recipes(observation, binding=binding)[0]["fingerprint"])
        changed = deepcopy(observation); changed["status"] = changed["evidence"]["hops"][-1]["status"] = 301
        changed["evidence"]["hops"][-1]["response_location"]["response_status"] = 301
        self.assertNotEqual(rows[0]["fingerprint"], self.recipes(changed, job_id=2**53 - 1, binding=binding)[0]["fingerprint"])

    def test_strict_original_family_shape_id_declaration_dates_status_and_complete_private_provenance_before_recipe(self):
        observation = self.original.result(["https://example.com/public", "http://example.com/public"])
        for job_id in (True, "7", 0, -1, 2**53):
            with self.assertRaises(ValidationError): self.recipes(observation, job_id=job_id)
        for changes in ({"collection_permission": 1}, {"actor_id": True}, {"source_digest": "bad"}, {"observations": ["response_location"]},
            {"origins": self.original.binding["origins"][:1]}, {"raw": "private"}):
            with self.assertRaises(ValidationError): self.recipes(observation, binding={**self.original.binding, **changes})
        for mutate in (lambda r: r.update(method="passive-redirect-evidence-v1"), lambda r: r.update(status=True), lambda r: r.update(raw_location="private"),
            lambda r: r.update(last_observed_at=r["observed_at"]), lambda r: r["evidence"].update(state="redirect_loop"),
            lambda r: r["evidence"]["hops"][0]["response_location"].update(target_scheme="https"),
            lambda r: r["evidence"]["hops"][1].update(observed_at="2026-02-30T00:00:00.000001+00:00")):
            bad = deepcopy(observation); mutate(bad)
            with self.assertRaises(ValidationError): self.recipes(bad)
        for value in (None, [], {}, "private"):
            with self.assertRaises(ValidationError): self.recipes(value)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class OriginalRedirectChainFindingRecipeTests(TransactionTestCase):
    setUp = fixtures.OriginalRedirectChainCandidateTests.setUp
    verified = fixtures.OriginalRedirectChainCandidateTests.verified
    queue = fixtures.OriginalRedirectChainCandidateTests.queue
    transport = fixtures.OriginalRedirectChainCandidateTests.transport
    read = fixtures.OriginalRedirectChainCandidateTests.read

    def test_genuine_independent_verifiers_native_private_byte_readback_to_pure_recipe_no_new_work(self):
        self.data = {**self.data, "url": self.https + "/public", "target_urls": [self.http + "/public"]}
        job = self.queue(); fetcher, connections, responses, *_ = self.transport()
        with patch("socket.create_connection", side_effect=AssertionError("No actual network")):
            self.assertTrue(collector.execute_passive_redirect_chain_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); source = self.read(job)["collection"]; original = deepcopy((source, job.config_snapshot))
        counts = (JobRun.objects.count(), UsageReservation.objects.count())
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No private I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            rows = redirect_chain_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_passive_redirect_chain_id"], job.pk)
        self.assertEqual(rows[0]["evidence"]["collection_sha256"], job.output["derived_sha256"])
        self.assertEqual(rows[0]["evidence"]["binding_sha256"], sha256(lifecycle._encode(job.config_snapshot["binding"])).hexdigest())
        self.assertEqual(rows[0]["evidence"]["fact"], {"transitions": [{"from_hop": 0, "to_hop": 1}]})
        self.assertEqual((source, job.config_snapshot), original)
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
        for private in (self.challenge, self.http_verification.challenge_digest, self.owner.email, "private", "secret"):
            self.assertNotIn(private, json.dumps(rows))
        for conn, response in zip(connections, responses): conn.request.assert_called_once(); response.read.assert_not_called()
