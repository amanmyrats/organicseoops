"""Real fixture worker→diagnostics→finding→human review/action, never a first-value conversion."""
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import OrganizationMembership, Project, ProjectConfiguration
from .action_review import record_action
from .diagnostics import build_technical_diagnostics
from .findings import record_technical_findings, review_finding
from .first_audit_value import first_audit_action_source
from .models import ActionReview, CrawlPageSnapshot, Finding, Opportunity, TechnicalDiagnosticsSnapshot
from . import test_first_audit_evidence as audit_fixtures


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-action-source"}})
class FirstAuditActionSourceTests(TransactionTestCase):
    setUp = audit_fixtures.FirstAuditEvidenceTests.setUp
    crawl = audit_fixtures.FirstAuditEvidenceTests.crawl

    def accepted_source(self, key="actual-audit-action", *, marked=True):
        job = self.crawl(key, marked=marked)
        snapshot = build_technical_diagnostics(job.crawl_run.pk)
        findings, _truncated = record_technical_findings(project=self.project, actor=self.owner, diagnostics_id=snapshot.pk)
        finding = next(row for row in findings if row.detector == "raw_meta_description_missing_candidate")
        review = review_finding(project=self.project, actor=self.owner, finding_id=finding.pk, expected_revision=0,
            priority="medium", estimated_effort="small", business_relevance="unknown", reason="Human metadata review only.")
        values = {"project": self.project, "actor": self.owner, "source_type": "opportunity", "source_id": review.pk,
            "action_kind": "refresh", "assignee_id": self.owner.pk,
            "acceptance_criteria": "A business expert should review this observed description.", "reason": "Human proposal."}
        proposal = record_action(**values, request_key=f"{key}-proposal", state="proposed")
        accepted = record_action(**{**values, "reason": "Human accepts manual review, not first value."},
            request_key=f"{key}-accept", state="accepted", action_id=proposal.action_id, expected_revision=1)
        return job, finding, review, proposal, accepted

    def source(self, job, accepted, **changes):
        return first_audit_action_source(**{"project": self.project, "actor": self.viewer,
            "job_id": job.pk, "action_review_id": accepted.pk, **changes})

    def test_actual_current_private_worker_finding_human_acceptance_is_minimized_read_only_and_not_first_value(self):
        job, finding, review, _proposal, accepted = self.accepted_source()
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("socket.getaddrinfo", side_effect=AssertionError("network")), \
            patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            source = self.source(job, accepted)
            self.assertEqual(source, self.source(job, accepted))
        self.assertEqual(source["finding_id"], finding.pk)
        self.assertEqual(source["opportunity_id"], review.pk)
        self.assertEqual(source["action_review_id"], accepted.pk)
        self.assertEqual(source["action_accepted_at"], accepted.created_at.isoformat())
        self.assertEqual(source["audit_completed_at"], job.crawl_run.completed_at.isoformat())
        self.assertEqual(source["first_value"], "not_established")
        self.assertEqual(source["first_ever_occurrence"], "not_established")
        serialized = json.dumps(source)
        for hidden in ("https://", "Synthetic audit body", accepted.acceptance_criteria, accepted.reason, "organizations/"):
            self.assertNotIn(hidden, serialized)
        from tenancy.acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"], {"count": 0, "grain": "organization", "state": "derivable"})

    def test_invalid_foreign_unmarked_proposed_and_different_crawl_are_not_current_accepted_sources(self):
        job, _finding, _review, proposal, accepted = self.accepted_source()
        other = Project.objects.create(organization=self.org, name="Other source scope",
            canonical_origin="https://different-value.example.invalid")
        for field in ("job_id", "action_review_id"):
            for value in (True, 0, "1", 2**53):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.source(job, accepted, **{field: value})
        for changes in ({"actor": self.foreign}, {"project": other}, {"action_review_id": proposal.pk},
                        {"action_review_id": accepted.pk + 9999}):
            with self.subTest(changes=changes), self.assertRaises((PermissionDenied, ValidationError)):
                self.source(job, accepted, **changes)
        other_job = self.crawl("later-unrelated-audit")
        with self.assertRaises(ValidationError):
            self.source(other_job, accepted)
        ordinary, _finding, _review, _proposal, ordinary_action = self.accepted_source("ordinary-action-source", marked=False)
        with self.assertRaises(ValidationError):
            self.source(ordinary, ordinary_action)

    def test_later_marked_audit_can_supply_action_evidence_without_rewriting_first_operational_history(self):
        from .models import FirstBoundedAuditCompletion
        earlier = self.crawl("earlier-operational-completion")
        job, _finding, _review, _proposal, accepted = self.accepted_source("later-human-reviewed-audit")
        source = self.source(job, accepted)
        self.assertEqual(source["job_id"], job.pk)
        self.assertEqual(FirstBoundedAuditCompletion.objects.get().job_id, earlier.pk)
        self.assertEqual(source["first_ever_occurrence"], "not_established")

    def test_tampered_metadata_decision_dates_and_nonlatest_reviews_are_unavailable(self):
        job, finding, review, proposal, accepted = self.accepted_source()
        page = job.crawl_run.pages.get()
        source = finding.source_diagnostics
        from django.utils import timezone
        from datetime import timedelta
        mutations = [
            (CrawlPageSnapshot, page.pk, {"meta_description": "Different database metadata"}),
            (Finding, finding.pk, {"evidence": {**finding.evidence, "details": {**finding.evidence["details"], "character_count": 99}}}),
            (Finding, finding.pk, {"detector": "raw_title_missing_candidate"}),
            (Finding, finding.pk, {"detected_at": timezone.now() + timedelta(days=1)}),
            (TechnicalDiagnosticsSnapshot, source.pk, {"input_hash": "a" * 64}),
            (ActionReview, accepted.pk, {"acceptance_criteria": "Changed acceptance criteria."}),
            (ActionReview, accepted.pk, {"affected_urls": []}),
        ]
        for model, pk, fields in mutations:
            rows = model.objects.filter(pk=pk); original = rows.values(*fields).get()
            rows.update(**fields)
            with self.subTest(model=model.__name__, fields=fields), self.assertRaises((PermissionDenied, ValidationError)):
                self.source(job, accepted)
            rows.update(**original)
        # Metadata can be tampered consistently in SQL; retained original bytes still reject it.
        details = {**finding.evidence["details"], "character_count": 1}
        CrawlPageSnapshot.objects.filter(pk=page.pk).update(meta_description="x")
        changed_detector = "raw_meta_description_short_candidate"
        import hashlib
        fingerprint = hashlib.sha256(json.dumps(["technical-candidate-v1", "source_diagnostics", source.pk,
            changed_detector, finding.subject, f"page:{page.pk}"], separators=(",", ":")).encode()).hexdigest()
        Finding.objects.filter(pk=finding.pk).update(detector=changed_detector, fingerprint=fingerprint,
            evidence={**finding.evidence, "details": details})
        with self.assertRaises(ValidationError):
            self.source(job, accepted)
        CrawlPageSnapshot.objects.filter(pk=page.pk).update(meta_description=page.meta_description)
        Finding.objects.filter(pk=finding.pk).update(detector=finding.detector, fingerprint=finding.fingerprint, evidence=finding.evidence)
        review_finding(project=self.project, actor=self.owner, finding_id=finding.pk, expected_revision=1,
            priority="high", estimated_effort="small", business_relevance="unknown", reason="Later human reprioritization.")
        with self.assertRaises(ValidationError):
            self.source(job, accepted)

    def test_latest_action_and_current_authority_rechecked_after_private_read(self):
        job, _finding, review, proposal, accepted = self.accepted_source()
        configuration = ProjectConfiguration.objects.create(project=self.project, source_choice="skip")
        reader = OrganizationMembership.objects.get(organization=self.org, user=self.viewer)
        for rows, fields in ((OrganizationMembership.objects.filter(organization=self.org, user=self.owner), {"role": "viewer"}),
                             (OrganizationMembership.objects.filter(pk=reader.pk), {"user_id": self.foreign.pk}),
                             (ProjectConfiguration.objects.filter(pk=configuration.pk), {"source_choice": "synthetic_demo"}),
                             (Opportunity.objects.filter(pk=review.pk), {"review_reason": "Changed while reading."})):
            original = rows.values(*fields).get()
            def change_after_read(**kwargs):
                body = read_project_artifact(**kwargs); rows.update(**fields); return body
            with self.subTest(fields=fields), patch("jobs.first_audit_value.read_project_artifact", side_effect=change_after_read):
                with self.assertRaises((PermissionDenied, ValidationError)):
                    self.source(job, accepted)
            rows.update(**original)
        def reopen_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            record_action(project=self.project, actor=self.owner, source_type="opportunity", source_id=review.pk,
                action_kind="refresh", assignee_id=self.owner.pk, acceptance_criteria=proposal.acceptance_criteria,
                reason="Human reopens during source read.", request_key="audit-action-reopened", state="proposed",
                action_id=accepted.action_id, expected_revision=2)
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=reopen_after_read), self.assertRaises(ValidationError):
            self.source(job, accepted)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-action-api"}})
class FirstAuditActionSourceApiTests(TransactionTestCase):
    setUp = audit_fixtures.FirstAuditEvidenceTests.setUp
    crawl = audit_fixtures.FirstAuditEvidenceTests.crawl
    accepted_source = FirstAuditActionSourceTests.accepted_source
    source = FirstAuditActionSourceTests.source

    def path_for(self, row):
        return f"{self.path}actions/{row.action_id}/{row.revision}/"

    def test_exact_private_selected_revision_derives_actual_audit_and_writes_or_fetches_nothing(self):
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        self.client.force_login(self.viewer)
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            result = self.client.get(self.path_for(accepted))
            self.assertEqual(result.status_code, 200, result.content)
            self.assertEqual(result.json()["source"], self.source(job, accepted))
        self.assertEqual(result.json()["action_id"], str(accepted.action_id))
        self.assertEqual(result.json()["revision"], accepted.revision)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("https://", result.content.decode())
        self.assertNotIn(accepted.reason, result.content.decode())
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(self.path_for(accepted)).status_code, 404)
        self.client.logout()
        denied = self.client.get(self.path_for(accepted))
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied["Cache-Control"], "private, no-store")

    def test_strict_methods_bounds_inputs_stale_proposed_and_real_get_throttle(self):
        _job, _finding, _review, proposal, accepted = self.accepted_source()
        path = self.path_for(accepted)
        for method in ("post", "head", "put", "patch", "delete", "options"):
            result = getattr(self.client, method)(path)
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result["Allow"], "GET")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        for suffix in ("?job_id=1", "?revision=2&revision=3"):
            self.assertEqual(self.client.get(path + suffix).status_code, 400)
        self.assertEqual(self.client.generic("GET", path, data=b"{}", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(path.replace(f"/{accepted.revision}/", "/65535/")).status_code, 400)
        self.assertEqual(self.client.get(self.path_for(proposal)).status_code, 409)
        from django.core.cache import cache
        cache.clear()
        missing = path.replace(str(accepted.action_id), "00000000-0000-4000-8000-000000000000")
        for _ in range(30):
            self.assertEqual(self.client.get(missing).status_code, 404)
        self.assertEqual(self.client.get(missing).status_code, 429)

    def test_final_demo_reader_and_latest_acceptance_loss_return_only_generic_errors(self):
        _job, _finding, review, proposal, accepted = self.accepted_source()
        path = self.path_for(accepted)
        configuration = ProjectConfiguration.objects.create(project=self.project, source_choice="skip")
        def demo_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="synthetic_demo")
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=demo_after_read):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json(), {"message": "Current accepted audit source unavailable or needs review."})
        ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="skip")
        self.client.force_login(self.viewer)
        def revoke_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).delete()
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=revoke_after_read):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.owner)
        record_action(project=self.project, actor=self.owner, source_type="opportunity", source_id=review.pk,
            action_kind="refresh", assignee_id=self.owner.pk, acceptance_criteria=proposal.acceptance_criteria,
            reason="Reopened source is no longer an accepted current action.", request_key="source-api-reopened",
            state="proposed", action_id=accepted.action_id, expected_revision=2)
        self.assertEqual(self.client.get(path).status_code, 409)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-value-proof"}})
class FirstValueAcknowledgmentProofTests(TransactionTestCase):
    setUp = audit_fixtures.FirstAuditEvidenceTests.setUp
    crawl = audit_fixtures.FirstAuditEvidenceTests.crawl
    accepted_source = FirstAuditActionSourceTests.accepted_source

    def validate(self, job, action, proof, **changes):
        from .first_audit_value import validate_first_value_acknowledgment_proof
        return validate_first_value_acknowledgment_proof(**{"project": self.project, "actor": self.owner,
            "job_id": job.pk, "action_review_id": action.pk, "proof": proof,
            "acknowledge_useful_next_action": True, **changes})

    def test_actual_current_source_challenge_and_repeated_validation_record_no_acknowledgment_or_first_value(self):
        from .first_audit_value import first_value_acknowledgment_challenge, completion_source_digest
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            challenge = first_value_acknowledgment_challenge(project=self.project, actor=self.owner,
                job_id=job.pk, action_review_id=accepted.pk)
            source = self.validate(job, accepted, challenge["receipt_proof"])
            self.assertEqual(self.validate(job, accepted, challenge["receipt_proof"]), source)
        self.assertFalse(challenge["acknowledgment_recorded"])
        self.assertEqual(source, challenge["source"])
        self.assertEqual(challenge["source_digest"], completion_source_digest(source))
        self.assertEqual(source["acknowledging_actor_id"], self.owner.pk)
        self.assertEqual(source["evidence"]["first_value"], "not_established")
        self.assertLessEqual(len(challenge["receipt_proof"]), 4096)
        self.assertNotIn("https://", json.dumps(source))
        from tenancy.acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"], {"count": 0, "grain": "organization", "state": "derivable"})

    def test_signature_purpose_expiry_explicit_flag_exact_actor_and_current_source_authority_fail_closed(self):
        from django.core import signing
        from django.utils import timezone
        from .first_audit_value import (ACK_METHOD, ACK_SALT, first_value_acknowledgment_challenge)
        from allauth.account.models import EmailAddress
        import time
        job, _finding, review, _proposal, accepted = self.accepted_source()
        challenge = first_value_acknowledgment_challenge(project=self.project, actor=self.owner,
            job_id=job.pk, action_review_id=accepted.pk)
        proof = challenge["receipt_proof"]
        for flag in (False, None, 0, 1, "true"):
            with self.subTest(flag=flag), self.assertRaises(ValidationError):
                self.validate(job, accepted, proof, acknowledge_useful_next_action=flag)
        with self.assertRaises(ValidationError):
            self.validate(job, accepted, proof + "x")
        payload = {"method": ACK_METHOD, "source": challenge["source"], "issued_at": timezone.now().isoformat()}
        with self.assertRaises(ValidationError):
            self.validate(job, accepted, signing.dumps(payload, salt="wrong-purpose"))
        for issued in ("2026-10-03T01:00:00", "2099-01-01T00:00:00Z", "not-a-date"):
            with self.subTest(issued=issued), self.assertRaises(ValidationError):
                self.validate(job, accepted, signing.dumps({**payload, "issued_at": issued}, salt=ACK_SALT))
        original_time = time.time()
        with patch("django.core.signing.time.time", return_value=original_time - 301):
            expired = signing.dumps(payload, salt=ACK_SALT)
        with self.assertRaises(ValidationError):
            self.validate(job, accepted, expired)
        OrganizationMembership.objects.create(organization=self.org, user=self.foreign, role="owner")
        with self.assertRaises(ValidationError):
            self.validate(job, accepted, proof, actor=self.foreign)
        with self.assertRaises(PermissionDenied):
            self.validate(job, accepted, proof, actor=self.viewer)
        Opportunity.objects.filter(pk=review.pk).update(review_reason="Changed exact current human judgment.")
        with self.assertRaises(ValidationError):
            self.validate(job, accepted, proof)
        Opportunity.objects.filter(pk=review.pk).update(review_reason=review.review_reason)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied):
            self.validate(job, accepted, proof)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-value-capture"}})
class FirstValueAcknowledgmentCaptureTests(TransactionTestCase):
    setUp = audit_fixtures.FirstAuditEvidenceTests.setUp
    crawl = audit_fixtures.FirstAuditEvidenceTests.crawl
    accepted_source = FirstAuditActionSourceTests.accepted_source

    def challenge(self, job, accepted):
        from .first_audit_value import first_value_acknowledgment_challenge
        return first_value_acknowledgment_challenge(project=self.project, actor=self.owner,
            job_id=job.pk, action_review_id=accepted.pk)

    def capture(self, job, accepted, proof, **changes):
        from .first_audit_value import acknowledge_first_audit_value
        return acknowledge_first_audit_value(**{"project": self.project, "actor": self.owner,
            "job_id": job.pk, "action_review_id": accepted.pk, "proof": proof,
            "acknowledge_useful_next_action": True, **changes})

    def test_explicit_original_current_proof_immutable_server_date_set_once_not_approval_or_challenge(self):
        from .first_audit_value import ACK_METHOD, completion_source_digest
        from .models import FirstAuditValueAcknowledgment
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        challenge = self.challenge(job, accepted)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            saved = self.capture(job, accepted, challenge["receipt_proof"])
            repeated = self.capture(job, accepted, challenge["receipt_proof"])
            reissued = self.capture(job, accepted, self.challenge(job, accepted)["receipt_proof"])
        self.assertEqual(saved.pk, repeated.pk)
        self.assertEqual(saved.pk, reissued.pk)
        self.assertEqual(saved.acknowledged_at, repeated.acknowledged_at)
        self.assertEqual(saved.source["declaration"], challenge["source"])
        self.assertEqual(saved.source["tracking_started_at"], self.org.created_at.isoformat())
        self.assertEqual(self.org.first_value_tracking, ACK_METHOD)
        self.assertEqual(saved.actor_id, self.owner.pk)
        self.assertGreater(saved.acknowledged_at, accepted.created_at)
        self.assertEqual(saved.source_digest, completion_source_digest(saved.source))
        self.assertFalse(hasattr(saved, "_first_value_capture"))
        for hidden in (challenge["receipt_proof"], "https://", accepted.reason, accepted.acceptance_criteria):
            self.assertNotIn(hidden, json.dumps(saved.source))
        with self.assertRaises(ValidationError):
            saved.save()
        later, _finding, _review, _proposal, later_action = self.accepted_source("later-value-source")
        with self.assertRaises(ValidationError):
            self.capture(later, later_action, self.challenge(later, later_action)["receipt_proof"])
        self.assertEqual(FirstAuditValueAcknowledgment.objects.get().source, saved.source)
        from tenancy.acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"], {"count": 1, "grain": "organization", "state": "derivable"})

    def test_old_null_manager_birth_and_direct_historical_reconstruction_cannot_capture(self):
        from tenancy.models import Organization
        from .models import FirstAuditValueAcknowledgment
        from .first_audit_value import ACK_METHOD, completion_source_digest
        from django.utils import timezone
        legacy = Organization.objects.create(name="Synthetic untracked first value")
        self.assertIsNone(legacy.first_value_tracking)
        legacy.first_value_tracking = ACK_METHOD
        with self.assertRaises(ValidationError):
            legacy.save()
        reconstructed = Organization(pk=legacy.pk, name=legacy.name, first_value_tracking=ACK_METHOD)
        with self.assertRaises(ValidationError):
            reconstructed.save()
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        challenge = self.challenge(job, accepted)
        now = timezone.now()
        source = {"method": ACK_METHOD, "tracking_started_at": self.org.created_at.isoformat(),
                  "acknowledged_at": now.isoformat(), "declaration": challenge["source"]}
        with self.assertRaises(ValidationError):
            FirstAuditValueAcknowledgment.objects.create(organization=self.org, project=self.project, job=job,
                action_review=accepted, actor=self.owner, acknowledged_at=now, source=source,
                source_digest=completion_source_digest(source))
        Organization.objects.filter(pk=self.org.pk).update(first_value_tracking=None)
        with self.assertRaises(ValidationError):
            self.capture(job, accepted, challenge["receipt_proof"])
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())

    def test_invalid_false_expired_foreign_viewer_changed_source_capture_does_not_write(self):
        from .models import FirstAuditValueAcknowledgment
        import time
        job, _finding, review, _proposal, accepted = self.accepted_source()
        proof = self.challenge(job, accepted)["receipt_proof"]
        for changes in ({"acknowledge_useful_next_action": "true"}, {"acknowledge_useful_next_action": False},
                        {"proof": proof + "x"}, {"actor": self.foreign}, {"actor": self.viewer}):
            values = {"proof": proof, **changes}
            with self.subTest(changes=changes), self.assertRaises((PermissionDenied, ValidationError)):
                self.capture(job, accepted, **values)
        with patch("django.core.signing.time.time", return_value=time.time() + 301), self.assertRaises(ValidationError):
            self.capture(job, accepted, proof)
        Opportunity.objects.filter(pk=review.pk).update(review_reason="Changed current usefulness source.")
        with self.assertRaises(ValidationError):
            self.capture(job, accepted, proof)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())

    def test_private_read_current_authority_loss_rolls_back_capture_then_fresh_proof_can_retry(self):
        from .models import FirstAuditValueAcknowledgment
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        proof = self.challenge(job, accepted)["receipt_proof"]
        def revoke_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=revoke_after_read), self.assertRaises(PermissionDenied):
            self.capture(job, accepted, proof)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org, user=self.owner).role, "owner")
        self.capture(job, accepted, self.challenge(job, accepted)["receipt_proof"])
        self.assertEqual(FirstAuditValueAcknowledgment.objects.count(), 1)

    def test_insert_crash_rolls_back_acknowledgment_and_original_proof_retry_records_once(self):
        from .models import FirstAuditValueAcknowledgment
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        proof = self.challenge(job, accepted)["receipt_proof"]
        original_save = FirstAuditValueAcknowledgment.save
        def crash_after_insert(row, *args, **kwargs):
            original_save(row, *args, **kwargs)
            self.assertEqual(FirstAuditValueAcknowledgment.objects.count(), 1)
            raise RuntimeError("synthetic crash before acknowledgment commit")
        with patch.object(FirstAuditValueAcknowledgment, "save", crash_after_insert), self.assertRaises(RuntimeError):
            self.capture(job, accepted, proof)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        self.assertEqual(ActionReview.objects.get(pk=accepted.pk).state, "accepted")
        self.capture(job, accepted, proof)
        self.assertEqual(FirstAuditValueAcknowledgment.objects.count(), 1)

    def test_actual_customer_export_closure_and_erasure_remove_acknowledgment_before_sources(self):
        from tenancy.acquisition import acquisition_milestones
        from django.test import RequestFactory
        from tenancy.customer_inventory import CUSTOMER, RESTRICTED, require_complete_ownership_map
        from tenancy.customer_export import project_customer_rows
        from tenancy.closure import close_organization_locally
        from tenancy.deletion import (_customer_deletion_order, prepare_customer_data_deletion,
                                     sweep_customer_artifact_versions, delete_customer_database_records)
        from .models import FirstAuditValueAcknowledgment
        from tenancy.models import Organization
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        saved = self.capture(job, accepted, self.challenge(job, accepted)["receipt_proof"])
        label = "jobs.FirstAuditValueAcknowledgment"
        self.assertEqual(CUSTOMER[label], "organization_id")
        self.assertNotIn(label, RESTRICTED)
        require_complete_ownership_map()
        order = [model._meta.label for model, _lookup in _customer_deletion_order()]
        for parent in ("jobs.JobRun", "jobs.ActionReview", "tenancy.Project"):
            self.assertLess(order.index(label), order.index(parent))
        exported = project_customer_rows(organization=self.org, actor=self.owner, model_label=label,
            after_id=0, through_id=saved.pk)
        self.assertEqual(exported["rows"][0]["source"], saved.source)
        self.assertEqual(exported["rows"][0]["action_review_id"], accepted.pk)
        with self.assertRaises(PermissionDenied):
            project_customer_rows(organization=self.org, actor=self.foreign, model_label=label, after_id=0, through_id=saved.pk)
        request = RequestFactory().post("/synthetic-close/"); request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_organization_locally(organization=self.org, actor=self.owner, request=request)
        self.assertEqual(FirstAuditValueAcknowledgment.objects.count(), 1)
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"]["count"], 1)
        with self.assertRaises(PermissionDenied):
            self.capture(job, accepted, self.challenge(job, accepted)["receipt_proof"])
        run = prepare_customer_data_deletion(organization=self.org)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"]["count"], 0)
        self.assertTrue(Organization.objects.filter(pk=self.org.pk).exists())

    def test_retained_staff_projection_counts_actual_unique_org_declarations_not_completion_approval_or_current_roles(self):
        from django.contrib.auth import get_user_model
        from django.test.utils import CaptureQueriesContext
        from tenancy.acquisition import acquisition_milestones
        from tenancy.services import create_organization, create_project
        job, _finding, review, proposal, accepted = self.accepted_source()
        count = lambda: acquisition_milestones()["milestones"]["first_audit_succeeded"]
        self.assertEqual(count(), {"count": 0, "grain": "organization", "state": "derivable"})
        proof = self.challenge(job, accepted)["receipt_proof"]
        self.assertEqual(count()["count"], 0)
        saved = self.capture(job, accepted, proof)
        self.capture(job, accepted, proof)
        self.assertEqual(count()["count"], 1)
        record_action(project=self.project, actor=self.owner, source_type="opportunity", source_id=review.pk,
            action_kind="refresh", assignee_id=self.owner.pk, acceptance_criteria=proposal.acceptance_criteria,
            reason="Later reopening is not another usefulness declaration.", request_key="milestone-value-reopen",
            state="proposed", action_id=accepted.action_id, expected_revision=2)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        self.assertEqual(count()["count"], 1)
        self.owner = self.foreign
        self.org = create_organization(user=self.owner, name="Synthetic second usefulness organization")
        self.project = create_project(organization=self.org, user=self.owner, name="Synthetic second useful audit",
            canonical_origin="https://second-usefulness.example.invalid")
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/first-audit/"
        self.client.force_login(self.owner)
        second, _finding, _review, _proposal, second_action = self.accepted_source("second-org-useful-audit")
        self.capture(second, second_action, self.challenge(second, second_action)["receipt_proof"])
        self.assertEqual(count()["count"], 2)
        staff = get_user_model().objects.create_superuser("value-count-staff@example.invalid", "Test passphrase 99!")
        self.client.force_login(staff)
        with override_settings(STAFF_MFA_REQUIRED=False), CaptureQueriesContext(connection) as queries, \
            patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("no fetch")):
            result = self.client.get("/api/platform/acquisition/milestones/")
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result.json()["milestones"]["first_audit_succeeded"], count())
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        for hidden in ("organization_id", "project_id", "source_digest", "acknowledged_at", str(saved.acknowledged_at),
                       "action_id", accepted.reason, self.owner.email):
            self.assertNotIn(hidden, result.content.decode())
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(self.client.get("/api/platform/acquisition/milestones/").status_code, 403)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-value-history"}})
class FirstValueAcknowledgmentHistoryTests(TransactionTestCase):
    setUp = audit_fixtures.FirstAuditEvidenceTests.setUp
    crawl = audit_fixtures.FirstAuditEvidenceTests.crawl
    accepted_source = FirstAuditActionSourceTests.accepted_source
    challenge = FirstValueAcknowledgmentCaptureTests.challenge
    capture = FirstValueAcknowledgmentCaptureTests.capture

    def test_original_server_timing_is_read_only_exact_rounded_down_scoped_unknown_and_not_current_action_authority(self):
        from datetime import timedelta
        from .first_audit_value import inspect_first_audit_value_timing
        from tenancy.models import Organization
        from .models import FirstAuditValueAcknowledgment
        unknown = inspect_first_audit_value_timing(project=self.project, actor=self.viewer)
        self.assertEqual(unknown["state"], "not_observed_for_project")
        self.assertNotIn("elapsed_milliseconds", unknown)
        Organization.objects.filter(pk=self.org.pk).update(first_value_tracking=None)
        self.assertEqual(inspect_first_audit_value_timing(project=self.project, actor=self.viewer)["state"], "unknown")
        from .first_audit_value import ACK_METHOD
        Organization.objects.filter(pk=self.org.pk).update(first_value_tracking=ACK_METHOD)  # Fixture restoration only.
        job, _finding, review, proposal, accepted = self.accepted_source("actual-usefulness-timing")
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        proof = self.challenge(job, accepted)
        self.assertNotIn("elapsed_milliseconds", inspect_first_audit_value_timing(project=self.project, actor=self.viewer))
        saved = self.capture(job, accepted, proof["receipt_proof"])
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("no network")):
            timing = inspect_first_audit_value_timing(project=self.project, actor=self.viewer)
        self.assertEqual(timing["elapsed_milliseconds"], (saved.acknowledged_at - self.org.created_at) // timedelta(milliseconds=1))
        self.assertEqual(timing["acknowledged_at"], saved.acknowledged_at.isoformat())
        self.assertEqual(timing["tracking_started_at"], self.org.created_at.isoformat())
        self.assertEqual(timing["source_digest"], saved.source_digest)
        self.assertEqual(timing["precision"], "whole_milliseconds_rounded_down")
        self.assertEqual(timing["interpretation"], "organization_age_at_first_server_subjective_ack_not_business_value_time")
        for hidden in ("action_id", "job_id", "acknowledging_actor_id", "source", "receipt_proof"):
            self.assertNotIn(hidden, timing)
        record_action(project=self.project, actor=self.owner, source_type="opportunity", source_id=review.pk,
            action_kind="refresh", assignee_id=self.owner.pk, acceptance_criteria=proposal.acceptance_criteria,
            reason="Later action state does not change original timing.", request_key="timing-source-reopen",
            state="proposed", action_id=accepted.action_id, expected_revision=2)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        self.assertEqual(inspect_first_audit_value_timing(project=self.project, actor=self.viewer), timing)
        other = Project.objects.create(organization=self.org, name="Other timing scope",
            canonical_origin="https://other-timing.example.invalid")
        self.assertEqual(inspect_first_audit_value_timing(project=other, actor=self.viewer), {**unknown, "project_id": other.pk})
        with self.assertRaises(PermissionDenied):
            inspect_first_audit_value_timing(project=self.project, actor=self.foreign)
        with patch("jobs.first_audit_value.read_project_artifact", return_value=b"tampered"), self.assertRaises(ValidationError):
            inspect_first_audit_value_timing(project=self.project, actor=self.viewer)

    def test_history_is_read_only_minimized_original_and_not_current_role_or_latest_source_authority(self):
        from .first_audit_value import inspect_first_audit_value
        job, _finding, review, proposal, accepted = self.accepted_source()
        challenge = self.challenge(job, accepted)
        saved = self.capture(job, accepted, challenge["receipt_proof"])
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            history = inspect_first_audit_value(project=self.project, actor=self.viewer)
            self.assertEqual(inspect_first_audit_value(project=self.project, actor=self.viewer), history)
        self.assertEqual(history["state"], "recorded")
        self.assertEqual(history["declaration_digest"], challenge["source_digest"])
        self.assertEqual(history["acknowledged_at"], saved.acknowledged_at.isoformat())
        self.assertEqual(history["source"]["action_accepted_at"], accepted.created_at.isoformat())
        for hidden in ("https://", "organizations/", "Synthetic audit body", accepted.reason, accepted.acceptance_criteria):
            self.assertNotIn(hidden, json.dumps(history))
        record_action(project=self.project, actor=self.owner, source_type="opportunity", source_id=review.pk,
            action_kind="refresh", assignee_id=self.owner.pk, acceptance_criteria=proposal.acceptance_criteria,
            reason="Human reopened after historical usefulness acknowledgment.", request_key="after-first-value-reopened",
            state="proposed", action_id=accepted.action_id, expected_revision=2)
        review_finding(project=self.project, actor=self.owner, finding_id=review.finding_id, expected_revision=1,
            priority="high", estimated_effort="small", business_relevance="unknown", reason="Later human review.")
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        self.assertEqual(inspect_first_audit_value(project=self.project, actor=self.viewer), history)
        with self.assertRaises((ValidationError, PermissionDenied)):
            first_audit_action_source(project=self.project, actor=self.viewer, job_id=job.pk, action_review_id=accepted.pk)
        other = Project.objects.create(organization=self.org, name="Other history scope",
                                       canonical_origin="https://other-value-history.example.invalid")
        other_history = inspect_first_audit_value(project=other, actor=self.viewer)
        self.assertEqual(other_history["state"], "not_observed_for_project")
        self.assertNotIn("source", other_history)
        self.assertNotIn("acknowledged_at", other_history)
        with self.assertRaises(PermissionDenied):
            inspect_first_audit_value(project=self.project, actor=self.foreign)

    def test_unknown_does_not_write_and_original_source_private_integrity_and_final_reader_mode_loss_deny(self):
        from .first_audit_value import inspect_first_audit_value, completion_source_digest
        from .models import FirstAuditValueAcknowledgment
        from tenancy.models import Organization
        self.assertEqual(inspect_first_audit_value(project=self.project, actor=self.viewer)["state"], "not_observed_for_project")
        Organization.objects.filter(pk=self.org.pk).update(first_value_tracking=None)
        self.assertEqual(inspect_first_audit_value(project=self.project, actor=self.viewer)["state"], "unknown")
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        from .first_audit_value import ACK_METHOD
        Organization.objects.filter(pk=self.org.pk).update(first_value_tracking=ACK_METHOD)  # Fixture restoration only.
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        saved = self.capture(job, accepted, self.challenge(job, accepted)["receipt_proof"])
        with patch("jobs.first_audit_value.read_project_artifact", return_value=b"changed historical body"), self.assertRaises(ValidationError):
            inspect_first_audit_value(project=self.project, actor=self.viewer)
        changed = {**saved.source, "acknowledged_at": accepted.created_at.isoformat()}
        rows = FirstAuditValueAcknowledgment.objects.filter(pk=saved.pk)
        rows.update(source=changed, source_digest=completion_source_digest(changed))
        with self.assertRaises(ValidationError):
            inspect_first_audit_value(project=self.project, actor=self.viewer)
        rows.update(source=saved.source, source_digest=saved.source_digest)
        configuration = ProjectConfiguration.objects.create(project=self.project, source_choice="skip")
        def demo_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="synthetic_demo")
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=demo_after_read), self.assertRaises(ValidationError):
            inspect_first_audit_value(project=self.project, actor=self.viewer)
        ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="skip")
        def revoke_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).delete()
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=revoke_after_read), self.assertRaises(PermissionDenied):
            inspect_first_audit_value(project=self.project, actor=self.viewer)

    def test_proof_expiry_rechecked_after_slow_source_inspection(self):
        from django.utils import timezone
        from datetime import timedelta
        from .first_audit_value import validate_first_value_acknowledgment_proof
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        challenge = self.challenge(job, accepted)
        now = timezone.now()
        future = now + timedelta(seconds=301)
        with patch("jobs.first_audit_value.first_value_acknowledgment_source", return_value=challenge["source"]), \
            patch("jobs.first_audit_value.timezone.now", side_effect=[now, future, future]), self.assertRaises(ValidationError):
            validate_first_value_acknowledgment_proof(project=self.project, actor=self.owner, job_id=job.pk,
                action_review_id=accepted.pk, proof=challenge["receipt_proof"], acknowledge_useful_next_action=True)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-value-race"}})
class FirstValueAcknowledgmentRaceTests(TransactionTestCase):
    setUp = audit_fixtures.FirstAuditEvidenceTests.setUp
    crawl = audit_fixtures.FirstAuditEvidenceTests.crawl
    accepted_source = FirstAuditActionSourceTests.accepted_source
    challenge = FirstValueAcknowledgmentCaptureTests.challenge
    capture = FirstValueAcknowledgmentCaptureTests.capture

    def test_two_postgresql_sessions_acknowledge_same_original_proof_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from .models import FirstAuditValueAcknowledgment
        self.assertEqual(connection.vendor, "postgresql")
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        proof = self.challenge(job, accepted)["receipt_proof"]
        barrier = Barrier(2)
        def worker(_index):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                saved = self.capture(job, accepted, proof)
                return saved.pk, saved.acknowledged_at
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, (1, 2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(FirstAuditValueAcknowledgment.objects.count(), 1)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html", "text/plain"}),
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "audit-value-api"}})
class FirstValueAcknowledgmentApiTests(TransactionTestCase):
    setUp = audit_fixtures.FirstAuditEvidenceTests.setUp
    crawl = audit_fixtures.FirstAuditEvidenceTests.crawl
    accepted_source = FirstAuditActionSourceTests.accepted_source

    def test_private_original_timing_get_unknown_then_actual_ack_read_only_minimized_and_no_capture(self):
        from .first_audit_value import inspect_first_audit_value_timing
        from .models import FirstAuditValueAcknowledgment
        path = f"{self.path}usefulness/timing/"
        unknown = self.client.get(path)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.json()["state"], "not_observed_for_project")
        self.assertNotIn("elapsed_milliseconds", unknown.json())
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        job, _finding, _review, _proposal, accepted = self.accepted_source("timing-api-source")
        proof = self.client.get(self.path_for(accepted)).json()["challenge"]["receipt_proof"]
        captured = self.client.post(self.path_for(accepted), json.dumps({"receipt_proof": proof,
            "acknowledge_useful_next_action": True}), content_type="application/json")
        self.assertEqual(captured.status_code, 200, captured.content)
        self.client.force_login(self.viewer)
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("no fetch")):
            result = self.client.get(path)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json(), inspect_first_audit_value_timing(project=self.project, actor=self.viewer))
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        for hidden in ("https://", "organizations/", "source\"", "action_id", "actor_id", accepted.reason, proof):
            self.assertNotIn(hidden, result.content.decode())
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(path).status_code, 401)

    def test_timing_get_strict_intake_shared_throttle_and_final_current_mode_reader_loss(self):
        from django.core.cache import cache
        from .first_audit_value import first_value_acknowledgment_challenge, acknowledge_first_audit_value
        path = f"{self.path}usefulness/timing/"
        for method in ("post", "head", "put", "patch", "delete", "options"):
            result = getattr(self.client, method)(path)
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result["Allow"], "GET")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get(path + "?timing=true").status_code, 400)
        self.assertEqual(self.client.generic("GET", path, b"{}", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(path.replace(f"projects/{self.project.pk}", "projects/0")).status_code, 400)
        job, _finding, _review, _proposal, accepted = self.accepted_source("timing-final-source")
        proof = first_value_acknowledgment_challenge(project=self.project, actor=self.owner, job_id=job.pk, action_review_id=accepted.pk)
        acknowledge_first_audit_value(project=self.project, actor=self.owner, job_id=job.pk,
            action_review_id=accepted.pk, proof=proof["receipt_proof"], acknowledge_useful_next_action=True)
        config = ProjectConfiguration.objects.create(project=self.project, source_choice="skip")
        def demo_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            ProjectConfiguration.objects.filter(pk=config.pk).update(source_choice="synthetic_demo")
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=demo_after_read):
            self.assertEqual(self.client.get(path).status_code, 409)
        ProjectConfiguration.objects.filter(pk=config.pk).update(source_choice="skip")
        self.client.force_login(self.viewer)
        def revoke_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.viewer).delete()
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=revoke_after_read):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.owner)
        cache.clear()
        # This uses the actual shared private-history 30/m user limit, not a separate bypass.
        for _ in range(30):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get(f"{self.path}usefulness/").status_code, 429)

    def path_for(self, row):
        return f"{self.path}actions/{row.action_id}/{row.revision}/usefulness/"

    def test_private_read_only_challenge_explicit_csrf_ack_and_original_history_repeat(self):
        from django.test import Client
        from .models import FirstAuditValueAcknowledgment
        from config.observability import redact
        job, _finding, _review, _proposal, accepted = self.accepted_source()
        path = self.path_for(accepted)
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        def read_only(execute, sql, params, many, context):
            self.assertEqual(sql.lstrip().split()[0].upper(), "SELECT", sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(read_only), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.content)
            challenge = response.json()["challenge"]
            self.assertFalse(challenge["acknowledgment_recorded"])
            self.assertEqual(client.get(f"{self.path}usefulness/").json()["state"], "not_observed_for_project")
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        body = json.dumps({"receipt_proof": challenge["receipt_proof"], "acknowledge_useful_next_action": True})
        self.assertNotIn(challenge["receipt_proof"], redact(body))
        self.assertEqual(client.post(path, body, content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("site fetch")):
            captured = client.post(path, body, content_type="application/json", **headers)
            repeated = client.post(path, body, content_type="application/json", **headers)
        self.assertEqual(captured.status_code, 200, captured.content)
        self.assertEqual(captured.json(), repeated.json())
        self.assertEqual(captured.json()["state"], "recorded")
        self.assertEqual(captured.json()["declaration_digest"], challenge["source_digest"])
        self.assertEqual(captured.json()["source"]["job_id"], job.pk)
        self.assertEqual(FirstAuditValueAcknowledgment.objects.count(), 1)
        self.assertNotIn(challenge["receipt_proof"], captured.content.decode())
        self.assertNotIn("https://", captured.content.decode())
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        client.force_login(self.viewer)
        self.assertEqual(client.get(f"{self.path}usefulness/").json(), captured.json())
        self.assertEqual(client.get(path).status_code, 403)
        client.force_login(self.foreign)
        self.assertEqual(client.get(f"{self.path}usefulness/").status_code, 404)
        client.logout()
        denied = client.get(f"{self.path}usefulness/")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied["Cache-Control"], "private, no-store")

    def test_strict_methods_input_duplicate_json_expiry_proof_scope_and_actual_mutation_throttle(self):
        from django.core.cache import cache
        from .models import FirstAuditValueAcknowledgment
        from tenancy.models import Organization
        import time
        _job, _finding, _review, _proposal, accepted = self.accepted_source()
        path = self.path_for(accepted)
        proof = self.client.get(path).json()["challenge"]["receipt_proof"]
        valid = json.dumps({"receipt_proof": proof, "acknowledge_useful_next_action": True})
        for method in ("head", "put", "patch", "delete", "options"):
            result = getattr(self.client, method)(path)
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result["Allow"], "GET, POST")
            self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.post(f"{self.path}usefulness/", valid, content_type="application/json").status_code, 405)
        for target in (path + "?job_id=1", path.replace(f"/{accepted.revision}/", "/65535/")):
            self.assertEqual(self.client.get(target).status_code, 400)
        self.assertEqual(self.client.generic("GET", path, data=b"{}", content_type="application/json").status_code, 400)
        for bad in ("{}", "[]", '{"receipt_proof":"x","receipt_proof":"y","acknowledge_useful_next_action":true}',
                    '{"receipt_proof":"x","acknowledge_useful_next_action":NaN}',
                    json.dumps({"receipt_proof": proof, "acknowledge_useful_next_action": 1}),
                    json.dumps({"receipt_proof": proof, "acknowledge_useful_next_action": False}),
                    json.dumps({"receipt_proof": True, "acknowledge_useful_next_action": True}),
                    json.dumps({"receipt_proof": proof, "acknowledge_useful_next_action": True, "job_id": 1}),
                    "x" * 6145):
            result = self.client.post(path, bad, content_type="application/json")
            self.assertEqual(result.status_code, 409, result.content)
            self.assertNotIn(proof, result.content.decode())
        self.assertEqual(self.client.post(path, valid, content_type="text/plain").status_code, 409)
        with patch("django.core.signing.time.time", return_value=time.time() + 301):
            self.assertEqual(self.client.post(path, valid, content_type="application/json").status_code, 409)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(path, valid, content_type="application/json").status_code, 403)
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.post(path, valid, content_type="application/json").status_code, 404)
        self.client.force_login(self.owner)
        Organization.objects.filter(pk=self.org.pk).update(first_value_tracking=None)
        self.assertEqual(self.client.post(path, valid, content_type="application/json").status_code, 409)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        cache.clear()
        missing = path.replace(str(accepted.action_id), "00000000-0000-4000-8000-000000000000")
        for _ in range(20):
            self.assertEqual(self.client.post(missing, valid, content_type="application/json").status_code, 404)
        self.assertEqual(self.client.post(missing, valid, content_type="application/json").status_code, 429)

    def test_uncertain_response_after_commit_uses_independent_read_lookup_then_deliberate_same_proof_retry(self):
        from .models import FirstAuditValueAcknowledgment
        _job, _finding, _review, _proposal, accepted = self.accepted_source()
        path = self.path_for(accepted)
        proof = self.client.get(path).json()["challenge"]["receipt_proof"]
        body = json.dumps({"receipt_proof": proof, "acknowledge_useful_next_action": True})
        with patch("jobs.first_audit_api.inspect_first_audit_value", side_effect=ValidationError("synthetic postcommit response loss")):
            uncertain = self.client.post(path, body, content_type="application/json")
            self.assertEqual(uncertain.status_code, 409)
        saved = FirstAuditValueAcknowledgment.objects.get()
        looked_up = self.client.get(f"{self.path}usefulness/")
        self.assertEqual(looked_up.status_code, 200)
        self.assertEqual(looked_up.json()["acknowledged_at"], saved.acknowledged_at.isoformat())
        repeated = self.client.post(path, body, content_type="application/json")
        self.assertEqual(repeated.json(), looked_up.json())
        self.assertEqual(FirstAuditValueAcknowledgment.objects.count(), 1)

    def test_current_loss_during_private_challenge_and_history_and_shared_get_throttle(self):
        from django.core.cache import cache
        from .models import FirstAuditValueAcknowledgment
        _job, _finding, _review, _proposal, accepted = self.accepted_source()
        path = self.path_for(accepted)
        configuration = ProjectConfiguration.objects.create(project=self.project, source_choice="skip")
        def demo_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="synthetic_demo")
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=demo_after_read):
            self.assertEqual(self.client.get(path).status_code, 409)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="skip")
        proof = self.client.get(path).json()["challenge"]["receipt_proof"]
        def revoke_after_read(**kwargs):
            body = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
            return body
        with patch("jobs.first_audit_value.read_project_artifact", side_effect=revoke_after_read):
            result = self.client.post(path, json.dumps({"receipt_proof": proof, "acknowledge_useful_next_action": True}),
                                      content_type="application/json")
            self.assertEqual(result.status_code, 403)
        self.assertFalse(FirstAuditValueAcknowledgment.objects.exists())
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org, user=self.owner).role, "owner")
        history_path = f"{self.path}usefulness/"
        cache.clear()
        for _ in range(30):
            self.assertEqual(self.client.get(history_path).status_code, 200)
        self.assertEqual(self.client.get(history_path).status_code, 429)
