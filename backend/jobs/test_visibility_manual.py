from django.test import TransactionTestCase
from datetime import datetime, timezone as utc

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .visibility_manual import METHOD, SOURCE, SURFACE, validate_manual_answer

NOW = datetime(2026, 10, 2, 12, tzinfo=utc.utc)


def observation():
    return {"method_version": METHOD, "source_kind": SOURCE, "surface": SURFACE,
        "origin": "https://manual.example.invalid", "configuration_revision": 1, "intent_review_id": 12,
        "prompt": "Which services address this synthetic customer intent?", "prompt_version": 1, "prompt_kind": "neutral",
        "requested_market": "Turkey", "requested_language": "en", "source_label": "Customer-authorized human report",
        "observation_reference": "human-answer-1", "observed_at": "2026-10-02T13:00:00+03:00", "reported_model": "",
        "reported_retrieval": "unknown", "applied_location": "", "applied_language": "", "applied_device": "unknown",
        "status": "complete", "answer": "Exact synthetic answer 😀 Straße. <script>not executed</script>",
        "evidence_note": "Human report; source/model/applied context not independently verified.",
        "storage_permission": True, "not_response_only_copy": True, "no_personal_payload": True}


class ManualAnswerIntakeTests(SimpleTestCase):
    def validate(self, data, **kwargs):
        return validate_manual_answer(data, **{**dict(as_of=NOW), **kwargs})

    def test_exact_prompt_answer_timezone_and_unknowns_preserved_without_database_or_network(self):
        data = observation()
        result = self.validate(data)
        self.assertEqual(result, data)
        self.assertIsNot(result, data)
        self.assertEqual(result["reported_model"], "")
        self.assertEqual(result["applied_device"], "unknown")
        result["answer"] = "Later edit"
        self.assertNotEqual(result["answer"], data["answer"])
        self.validate({**data, "applied_language": "tr", "applied_location": "Human-reported region",
            "reported_model": "Customer-reported model", "reported_retrieval": "reported"})

    def test_partial_unavailable_do_not_invent_negative_answers_or_citations(self):
        self.validate({**observation(), "status": "partial"})
        self.validate({**observation(), "status": "unavailable", "answer": ""})
        for changes in ({"status": "unavailable"}, {"status": "complete", "answer": ""},
            {"status": "partial", "answer": " "}, {"status": "not_mentioned"}, {"citation_count": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.validate({**observation(), **changes})

    def test_exact_scalar_schema_rights_method_context_and_personal_provider_fields_fail_closed(self):
        for changes in ({"storage_permission": 1}, {"not_response_only_copy": False}, {"no_personal_payload": False},
            {"method_version": "api-text-visibility-v1"}, {"surface": "verified_chatgpt"}, {"source_kind": "api"},
            {"prompt_version": True}, {"intent_review_id": 0}, {"configuration_revision": 0},
            {"answer": {"provider": "object"}}, {"account_email": "person@example.invalid"},
            {"observation_reference": "person@example.invalid"}, {"origin": "http://manual.example.invalid"},
            {"reported_retrieval": "verified_search"}, {"requested_language": "invented_language"},
            {"applied_language": "unknown"}, {"applied_device": "simulated"}):
            with self.subTest(keys=list(changes)), self.assertRaises(ValidationError):
                self.validate({**observation(), **changes})
        for data in (None, [], {}, {key: value for key, value in observation().items() if key != "storage_permission"}):
            with self.assertRaises(ValidationError):
                self.validate(data)

    def test_actual_serializer_size_controls_surrogates_and_aware_nonfuture_time(self):
        for changes in ({"observed_at": "2026-10-02T14:00:00+00:00"}, {"observed_at": "2026-10-02T10:00:00"},
            {"observed_at": "invalid"}, {"answer": "bad\x00"}, {"answer": "\ud800"}, {"prompt": "x" * 501},
            {"answer": "x" * 4001}, {"answer": "😀" * 4000}, {"evidence_note": ""}):
            with self.subTest(keys=list(changes)), self.assertRaises(ValidationError):
                self.validate({**observation(), **changes})
        self.validate({**observation(), "observed_at": NOW.isoformat()})
        for clock in (False, datetime(2026, 10, 2)):
            with self.assertRaises(ValidationError):
                self.validate(observation(), as_of=clock)


from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import json
from threading import Barrier
from unittest.mock import patch
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.test import Client
from django.core.cache import cache
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from tenancy.services import create_organization, create_project, update_project_configuration
from .intent_mapping import review_intent_cluster
from .models import AIVisibilityManualObservation, Artifact, JobRun, UsageReservation
from .visibility_entities import candidates
from .visibility_manual import entity_context, manual_rates, manual_source_current, record_manual_answer


class ManualFixture:
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("manual-owner@example.invalid", "test-password")
        self.other = users.create_user("manual-other@example.invalid", "test-password")
        for actor in (self.owner, self.other):
            EmailAddress.objects.create(user=actor, email=actor.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Synthetic manual org")
        self.project = create_project(organization=self.org, user=self.owner, name="Synthetic manual project",
            canonical_origin="https://manual.example.invalid")
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
            changes={"target_country": "Turkey", "target_languages": ["en"], "brand_aliases": ["Synthetic Brand"],
                     "seed_topics": ["service questions"], "competitor_origins": ["https://competitor.example.invalid"]})
        self.mapping_data = dict(project=self.project, actor=self.owner, request_key="manual-intent-1", label="Service questions",
            source_finding_ids=[], manual_topics=["service questions"], intent="commercial", page_kind="unmapped",
            preferred_page="", reason="Human seed; no demand measurement.", language="en")
        self.mapping = review_intent_cluster(**self.mapping_data)
        self.verification = ProjectOriginVerification.objects.create(organization=self.org, project=self.project,
            origin=self.project.canonical_origin, challenge_digest="a" * 64, state="verified", verified_at=timezone.now())
        self.intake = {**observation(), "intent_review_id": self.mapping.pk,
            "observed_at": (timezone.now() - timedelta(hours=1)).isoformat(),
            "answer": "😀 Synthetic Brand and Synthetic Brand; competitor.example.invalid. https://manual.example.invalid/own"}

    def record(self, **changes):
        return record_manual_answer(**{**dict(project=self.project, actor=self.owner,
            request_key="manual-report-1", intake=self.intake, reason="Original unchanged authorized human report."), **changes})

    def evaluate(self, row, **changes):
        matches = candidates(row.intake["answer"], entity_context(row.context))["matches"]
        matches = [{**match, "decision": "confirmed", "note": "Full-answer human meaning reviewed."} for match in matches]
        return self.record(**{**dict(request_key="manual-evaluation-1", observation_id=row.observation_id,
            expected_revision=row.revision, intake=row.intake, reason="Full answer evaluated with exact Unicode-codepoint spans.",
            evaluated=True, matches=matches), **changes})


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
class ManualAnswerHistoryTests(ManualFixture, TransactionTestCase):
    def test_foreign_real_intent_truncated_extraction_invalid_evaluations_and_unsafe_links(self):
        foreign_org = create_organization(user=self.other, name="Synthetic foreign manual org")
        foreign = create_project(organization=foreign_org, user=self.other, name="Synthetic foreign manual site", canonical_origin="https://foreign.example.invalid")
        update_project_configuration(project=foreign, user=self.other, expected_revision=0,
            changes={"target_country": "Turkey", "target_languages": ["en"], "brand_aliases": ["Synthetic Brand"], "seed_topics": ["service questions"]})
        mapping = review_intent_cluster(**{**self.mapping_data, "project": foreign, "actor": self.other})
        with self.assertRaises(PermissionDenied):
            self.record(intake={**self.intake, "intent_review_id": mapping.pk})
        for evaluated in (0, 1, "false", []):
            with self.assertRaises(ValidationError): self.record(evaluated=evaluated)
        row = self.record(intake={**self.intake, "answer": "Synthetic Brand " * 101})
        self.assertTrue(candidates(row.intake["answer"], entity_context(row.context))["has_more"])
        with self.assertRaises(ValidationError): self.evaluate(row, matches=[])
        second = self.record(request_key="manual-unsafe-links", intake={**self.intake, "observation_reference": "other-links",
            "answer": "😀 Straße https://manual.example.invalid.evil.invalid/ https://127.0.0.1/ javascript:alert(1)"})
        preview = candidates(second.intake["answer"], entity_context(second.context))
        self.assertFalse(any(match["kind"] == "project_domain" for match in preview["matches"]))
        self.assertFalse(next(link for link in preview["links"] if "127.0.0.1" in link["text"])["safe_syntax"])
        with self.assertRaises(ValidationError):
            self.evaluate(second, matches=[{"kind": "project_domain", "entity": "manual.example.invalid", "start": 0,
                "end": 1, "decision": "confirmed", "note": "Spoofed exact domain evidence."}])

    def test_immutable_exact_evidence_separate_evaluation_and_duplicate_reference_never_create_jobs(self):
        first = self.record()
        self.assertEqual(self.record().pk, first.pk)
        self.assertEqual(first.intake, self.intake)
        with self.assertRaises(ValidationError): first.save()
        with self.assertRaises(ValidationError): self.record(request_key="manual-duplicate-ref")
        evaluated = self.evaluate(first)
        self.assertEqual(self.evaluate(first).pk, evaluated.pk)
        with self.assertRaises(ValidationError): self.record()
        changed = {**evaluated.intake, "answer": "Changed synthetic evidence."}
        with self.assertRaises(ValidationError):
            self.evaluate(evaluated, request_key="manual-changed-eval", intake=changed, matches=[])
        correction = self.record(request_key="manual-correct-1", observation_id=first.observation_id,
            expected_revision=2, intake=changed)
        self.assertFalse(correction.evaluated)
        first.refresh_from_db()
        self.assertEqual(first.intake["answer"], self.intake["answer"])
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count(), Artifact.objects.count()), (0, 0, 0))

    def test_rates_latest_once_exact_source_context_prompt_mix_and_partial_unknown_exclusions(self):
        first = self.record()
        confirmed = self.evaluate(first)
        report = manual_rates(project=self.project, actor=self.owner)
        group = report["groups"][0]
        self.assertEqual(group["eligible_report_ids"], [confirmed.pk])
        self.assertEqual(group["mention_rate"], {"numerator": 1, "denominator": 1, "percent": "100.00", "state": "sampled_human_evaluated"})
        self.assertIsNone(group["citation_rate"]["percent"])
        self.assertIsNone(report["external_cost"])
        self.assertIsNone(report["referrals"])
        for index, changes in enumerate(({"status": "partial"}, {"status": "unavailable", "answer": ""},
            {"source_label": "Different reported tool"}, {"reported_model": "Different model"}, {"applied_language": "tr"},
            {"prompt": "What is Synthetic Brand?", "prompt_kind": "branded"})):
            row = self.record(request_key=f"manual-other-{index}", intake={**self.intake,
                "observation_reference": f"manual-other-{index}", **changes})
            if row.intake["status"] != "complete":
                with self.assertRaises(ValidationError): self.evaluate(row, request_key=f"manual-partial-eval-{index}")
        report = manual_rates(project=self.project, actor=self.owner)
        self.assertEqual(len(report["groups"]), 5)
        self.assertEqual(sum(len(group["eligible_report_ids"]) for group in report["groups"]), 1)
        uncertain = self.evaluate(confirmed, request_key="manual-uncertain-eval", matches=[{**confirmed.matches[0], "decision": "uncertain"}])
        group = next(group for group in manual_rates(project=self.project, actor=self.owner)["groups"] if uncertain.pk in group["report_ids"])
        self.assertEqual(group["exclusions"].get("uncertain_entity"), 1)
        self.assertEqual(group["mention_rate"]["denominator"], 0)
        self.assertIsNone(group["mention_rate"]["percent"])

    def test_current_foreign_role_email_intent_config_verification_and_retention_authority(self):
        with self.assertRaises(PermissionDenied): self.record(actor=self.other)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        with self.assertRaises(PermissionDenied): self.record(actor=self.other)
        membership.role = "admin"; membership.save()
        row = self.record(actor=self.other)
        membership.role = "member"; membership.save()
        self.assertFalse(manual_source_current(row))
        with self.assertRaises(PermissionDenied): self.evaluate(row)
        membership.role = "admin"; membership.save()
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(verified_at=timezone.now())
        self.assertFalse(manual_source_current(row))
        with self.assertRaises(PermissionDenied): self.evaluate(row)
        fresh = self.record(request_key="manual-fresh-attestation", intake={**self.intake, "observation_reference": "fresh-attestation"})
        forged = AIVisibilityManualObservation(project=self.project, actor=self.owner, intent_review=self.mapping,
            verification=self.verification, verified_at=fresh.verified_at, intake={**self.intake, "intent_review_id": self.mapping.pk + 999},
            context=fresh.context, revision=1, request_key="manual-forged-source", matches=[], reason="Forged source")
        with self.assertRaises(ValidationError): forged.save()
        review_intent_cluster(**{**self.mapping_data, "request_key": "manual-intent-2", "cluster_id": self.mapping.cluster_id, "expected_revision": 1})
        self.assertFalse(manual_source_current(fresh))
        with self.assertRaises(ValidationError): self.record(request_key="manual-stale-intent")
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied): self.record(request_key="manual-stale-email")
        EmailAddress.objects.filter(user=self.owner).update(verified=True)
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1, changes={"seed_topics": []})
        with self.assertRaises(ValidationError): self.record(request_key="manual-stale-config")
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.record(request_key="manual-retention-cutoff")

    def test_real_bounded_stored_sequential_private_exports_and_child_before_source_closed_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        first = self.record()
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.org, actor=self.owner))) as archive:
            exported = json.loads(archive.read("records/jobs/AIVisibilityManualObservation.json"))[0]
            self.assertEqual(exported["intake"], first.intake)
            self.assertTrue(exported["source_current_at_capture"])
            self.assertNotIn("request_key", exported)
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            stored = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="e" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
            original, _digest = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=stored.pk, position=0)
            ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
            self.assertEqual(private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=stored.pk, position=0)[0], original)
            parts = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="f" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                parts.refresh_from_db()
                if parts.state != parts.State.PREPARING: break
                self.assertTrue(capture_source_stage(parts.pk, parts.progress.get("step", 0)))
            parts.refresh_from_db()
            self.assertEqual(parts.state, parts.State.READY)
            part = parts.parts.filter(source__model="jobs.AIVisibilityManualObservation").first()
            data, _digest = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=parts.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive:
                exported = json.loads(archive.read("data"))[0]
                self.assertEqual(exported["intake"], first.intake)
                self.assertFalse(exported["source_current_at_capture"])
                self.assertEqual(exported["scope"], "historical_human_report_not_consumer_verification_or_current_use_permission")
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.other, snapshot_id=stored.pk, position=0)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=stored.pk, position=0)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=now)
        with self.assertRaises(PermissionDenied): self.record(request_key="manual-closed")
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(AIVisibilityManualObservation.objects.exists())


class ManualAnswerConcurrencyTests(ManualFixture, TransactionTestCase):
    def test_real_two_connection_corrections_cannot_overwrite_or_double_evaluate(self):
        first = self.record()
        barrier = Barrier(2)
        def write(key):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return self.evaluate(first, request_key=key).revision
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["manual-concurrent-1", "manual-concurrent-2"]))
        self.assertCountEqual(results, [2, "conflict"])
        self.assertEqual(AIVisibilityManualObservation.objects.filter(observation_id=first.observation_id).count(), 2)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "manual-answer-api"}})
class ManualAnswerApiTests(ManualFixture, TestCase):
    def test_actual_csrf_private_source_report_evaluation_history_rates_and_uncertain_key(self):
        cache.clear()
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/visibility-manual/"
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.owner)
        payload = {"request_key": "manual-api-first", "intake": self.intake, "reason": "Original exact report", "evaluated": False, "matches": []}
        self.assertEqual(client.post(url, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        def post(path, data):
            return client.post(path, json.dumps(data), content_type="application/json", **headers)
        response = post(url, payload)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        row = response.json()["observation"]
        self.assertEqual(row["intake"], self.intake)
        self.assertEqual(row["basis"], "human_report_not_consumer_or_provider_verified")
        self.assertEqual(post(url, payload).json()["observation"]["id"], row["id"])
        current = client.get(url).json()
        self.assertEqual(current["intent_reviews"][0]["review_id"], self.mapping.pk)
        self.assertEqual(current["verified_origins"], [self.project.canonical_origin])
        matches = [{**match, "decision": "confirmed"} for match in row["preview"]["matches"]]
        history = url + row["observation_id"] + "/"
        evaluated = {**payload, "request_key": "manual-api-evaluation", "expected_revision": 1, "evaluated": True, "matches": matches}
        result = post(history, evaluated)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual([item["revision"] for item in client.get(history).json()["observations"]], [2, 1])
        rates = client.get(url + "rates/").json()
        self.assertEqual(rates["groups"][0]["mention_rate"]["denominator"], 1)
        self.assertIsNone(rates["referrals"])
        lookup = client.get(url, {"request_key": "manual-api-evaluation"}).json()
        self.assertEqual(lookup["lookup"], "found")
        self.assertTrue(lookup["observations"][0]["is_latest"])
        self.assertEqual(client.get(url, {"request_key": "manual-api-absent"}).json()["lookup"], "not_found")
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        self.assertFalse(client.get(history).json()["observations"][0]["source_current"])
        self.assertEqual(post(history, {**evaluated, "request_key": "manual-api-source-loss", "expected_revision": 2}).status_code, 403)

    def test_foreign_viewer_malformed_duplicate_nonfinite_and_stale_source_denials_do_not_record(self):
        cache.clear()
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/visibility-manual/"
        client = Client(); client.force_login(self.other)
        self.assertEqual(client.get(url).status_code, 404)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertFalse(client.get(url).json()["can_review"])
        self.assertEqual(client.post(url, "{}", content_type="application/json").status_code, 403)
        membership.role = "admin"; membership.save()
        payload = {"request_key": "manual-api-invalid", "intake": self.intake, "reason": "Own report", "evaluated": False, "matches": []}
        for body in (json.dumps(payload)[:-1] + ',"reason":"duplicate"}', "x" * (60 * 1024 + 1),
            json.dumps({**payload, "evaluated": float("nan")}), json.dumps({**payload, "intake": {**self.intake, "storage_permission": False}})):
            self.assertEqual(client.post(url, body, content_type="application/json").status_code, 409)
        self.assertEqual(client.get(url + "?request_key=a&request_key=b").status_code, 400)
        self.assertEqual(client.get(url, {"extra": "value"}).status_code, 400)
        self.assertEqual(client.post(url + "rates/", "{}", content_type="application/json").status_code, 400)
        self.assertEqual(client.get(url + "00000000-0000-4000-8000-000000000099/").status_code, 404)
        self.assertEqual(AIVisibilityManualObservation.objects.count(), 0)
