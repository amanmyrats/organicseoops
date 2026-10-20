import hashlib
import json
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from tenancy.models import (
    AuditEvent,
    AuditEventType,
    DomainAlias,
    MembershipRole,
    OrganizationMembership,
    Organization,
    ProjectOriginVerification,
)
from tenancy.services import (
    create_organization,
    create_origin_verification,
    create_project,
    require_passive_security_scope,
    revoke_origin_verification,
    update_project,
)

from .crawling import FetchResponse
from .models import JobCancellation, JobRun, JobStatus, UsageReservation
from .recovery import reconcile_stuck_origin_verifications
from .security import execute_origin_verification, queue_origin_verification
from .services import cancel_job, dispatch_pending
from .usage import UsageLimitError


@override_settings(SECURE_SSL_REDIRECT=False)
class OriginVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.owner = user_model.objects.create_user("security-owner@example.com", password="test-password")
        self.member = user_model.objects.create_user("security-member@example.com", password="test-password")
        self.outsider = user_model.objects.create_user("security-outsider@example.com", password="test-password")
        for user in (self.owner, self.member, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Security org")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=MembershipRole.MEMBER,
        )
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="Security project",
            canonical_origin="https://security.example.com",
            aliases=["https://www.security.example.com"],
        )

    def test_private_api_enforces_scope_and_only_returns_the_challenge_once(self):
        path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/origin-verifications/"
        member = Client()
        member.force_login(self.member)
        self.assertEqual(
            member.post(path, data=json.dumps({"origin": self.project.canonical_origin}), content_type="application/json").status_code,
            403,
        )
        outsider = Client()
        outsider.force_login(self.outsider)
        self.assertEqual(outsider.get(path).status_code, 404)

        owner = Client()
        owner.force_login(self.owner)
        response = owner.post(
            path,
            data=json.dumps({"origin": self.project.canonical_origin}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        challenge = response.json()["challenge"]["content"]
        verification = ProjectOriginVerification.objects.get(project=self.project)
        self.assertEqual(verification.challenge_digest, hashlib.sha256(challenge.encode()).hexdigest())
        self.assertNotContains(response, verification.challenge_digest, status_code=201)
        self.assertNotContains(owner.get(path), challenge)
        event = AuditEvent.objects.get(event_type=AuditEventType.ORIGIN_VERIFICATION_CREATED)
        self.assertNotIn(challenge, json.dumps(event.details))
        detail_path = f"{path}{verification.pk}/"
        queued = owner.post(
            detail_path,
            data=json.dumps({"idempotency_key": "verification-api"}),
            content_type="application/json",
        )
        self.assertEqual(queued.status_code, 202)
        self.assertEqual(owner.delete(detail_path).status_code, 200)
        verification.refresh_from_db()
        self.assertEqual(verification.state, ProjectOriginVerification.State.REVOKED)

    def test_queue_is_idempotent_and_success_uses_zero_units(self):
        verification, challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        first = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-one",
        )
        repeated = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-one",
        )
        self.assertEqual(first.pk, repeated.pk)
        self.assertEqual(first.usage.provider, "passive_security")
        self.assertEqual(first.usage.reserved_units, 0)
        self.organization.trial.started_at = timezone.now() - timedelta(days=31)
        self.organization.trial.ends_at = timezone.now() - timedelta(days=1)
        self.organization.trial.save(update_fields=["started_at", "ends_at"])

        response = FetchResponse(
            url=f"{self.project.canonical_origin}/.well-known/organicseoops-verification.txt",
            status=200,
            headers={"content-type": "text/plain"},
            body=challenge.encode(),
        )
        fetcher = Mock()
        fetcher.fetch.side_effect = lambda url, before_request: (before_request(url), response)[1]
        with patch("jobs.security.SafeFetcher", return_value=fetcher):
            execute_origin_verification(first.pk)

        first.refresh_from_db()
        verification.refresh_from_db()
        first.usage.refresh_from_db()
        self.assertEqual(first.status, JobStatus.SUCCEEDED)
        self.assertEqual(first.usage.state, UsageReservation.State.RELEASED)
        self.assertEqual(verification.state, ProjectOriginVerification.State.VERIFIED)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEventType.ORIGIN_VERIFICATION_VERIFIED).exists())
        self.assertEqual(
            require_passive_security_scope(
                project=self.project,
                user=self.owner,
                origin=self.project.canonical_origin,
            ),
            verification,
        )

    def test_released_reservation_stops_verification_before_fetch(self):
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        job = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-unreserved",
        )
        job.usage.state = UsageReservation.State.RELEASED
        job.usage.settled_at = timezone.now()
        job.usage.save(update_fields=["state", "settled_at"])

        with patch("jobs.security.SafeFetcher") as fetcher:
            self.assertTrue(execute_origin_verification(job.pk))
        fetcher.assert_not_called()
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "usage_unreserved"))

    def test_mismatch_fails_without_granting_ownership(self):
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        job = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-mismatch",
        )
        fetcher = Mock()
        fetcher.fetch.return_value = FetchResponse(
            url=f"{self.project.canonical_origin}/.well-known/organicseoops-verification.txt",
            status=200,
            headers={},
            body=b"wrong challenge",
        )
        with patch("jobs.security.SafeFetcher", return_value=fetcher):
            execute_origin_verification(job.pk)

        job.refresh_from_db()
        verification.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_category, "verification_mismatch")
        self.assertEqual(verification.state, ProjectOriginVerification.State.PENDING)

    def test_rotated_challenge_invalidates_a_queued_job(self):
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        job = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-stale",
        )
        create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        with patch("jobs.security.SafeFetcher") as fetcher:
            execute_origin_verification(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.error_category, "verification_stale")
        fetcher.assert_not_called()

    def test_cancellation_and_removed_alias_are_rechecked_before_fetch(self):
        alias = DomainAlias.objects.get(project=self.project)
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=alias.origin,
        )
        cancelled = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-cancelled",
        )
        JobCancellation.objects.create(job=cancelled, requested_by=self.owner)
        with patch("jobs.security.SafeFetcher") as fetcher:
            execute_origin_verification(cancelled.pk)
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)
        self.assertEqual(cancelled.error_category, "cancelled")
        fetcher.assert_not_called()

        active, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=alias.origin,
        )
        scoped = queue_origin_verification(
            verification=active,
            actor=self.owner,
            idempotency_key="verification-scope-removed",
        )
        alias.delete()
        with patch("jobs.security.SafeFetcher") as fetcher:
            execute_origin_verification(scoped.pk)
        scoped.refresh_from_db()
        self.assertEqual(scoped.status, JobStatus.CANCELLED)
        self.assertEqual(scoped.error_category, "scope_revoked")
        fetcher.assert_not_called()
        active, changed = revoke_origin_verification(verification=active, user=self.owner)
        self.assertTrue(changed)
        self.assertEqual(active.state, ProjectOriginVerification.State.REVOKED)

    def test_wrong_domain_and_removed_verified_origin_cannot_authorize_passive_work(self):
        with self.assertRaises(ValidationError):
            create_origin_verification(
                project=self.project,
                user=self.owner,
                origin="https://wrong.example.com",
            )
        self.assertFalse(ProjectOriginVerification.objects.filter(origin="https://wrong.example.com").exists())

        alias = DomainAlias.objects.get(project=self.project)
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=alias.origin,
        )
        verification.state = ProjectOriginVerification.State.VERIFIED
        verification.verified_at = timezone.now()
        verification.save(update_fields=["state", "verified_at", "updated_at"])
        self.assertEqual(
            require_passive_security_scope(project=self.project, user=self.owner, origin=alias.origin),
            verification,
        )
        update_project(project=self.project, user=self.owner, aliases=[])
        verification.refresh_from_db()
        self.assertEqual(verification.state, ProjectOriginVerification.State.REVOKED)
        with self.assertRaises(PermissionDenied):
            require_passive_security_scope(project=self.project, user=self.owner, origin=alias.origin)

    def test_sensitive_job_permissions_and_stale_recovery_use_the_audit_queue(self):
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        with self.assertRaises(PermissionDenied):
            queue_origin_verification(
                verification=verification,
                actor=self.member,
                idempotency_key="verification-member",
            )
        job = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-recovery",
        )
        dispatch_job = queue_origin_verification(
            verification=verification,
            actor=self.owner,
            idempotency_key="verification-dispatch-permission",
        )
        with self.assertRaises(PermissionDenied):
            cancel_job(job=job, actor=self.member)

        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        job.__class__.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
        with patch("jobs.tasks.verify_project_origin_task.apply_async") as apply_async:
            self.assertEqual(reconcile_stuck_origin_verifications(stale_seconds=60), 1)
        apply_async.assert_called_once_with(
            args=[job.pk],
            queue="audit",
            task_id=f"job-{job.pk}",
            retry=False,
        )

        job.usage.state = UsageReservation.State.RELEASED
        job.usage.settled_at = timezone.now()
        job.usage.save(update_fields=["state", "settled_at"])
        job.__class__.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
        with patch("jobs.tasks.verify_project_origin_task.apply_async") as apply_async:
            self.assertEqual(reconcile_stuck_origin_verifications(stale_seconds=60), 0)
        apply_async.assert_not_called()
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "usage_unreserved"))

        self.organization.memberships.filter(user=self.owner).update(role=MembershipRole.MEMBER)
        with patch("jobs.tasks.verify_project_origin_task.apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertFalse(dispatch_pending(dispatch_job.pk))
        apply_async.assert_not_called()
        dispatch_job.refresh_from_db()
        dispatch_job.usage.refresh_from_db()
        self.assertEqual(dispatch_job.status, JobStatus.CANCELLED)
        self.assertEqual(dispatch_job.usage.state, UsageReservation.State.RELEASED)

    def test_verification_api_preserves_internal_capacity_reason(self):
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        client = Client()
        client.force_login(self.owner)
        with patch(
            "jobs.security.queue_origin_verification",
            side_effect=UsageLimitError("limited", category="internal_capacity"),
        ) as queue:
            response = client.post(
                f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/"
                f"origin-verifications/{verification.pk}/",
                data=json.dumps({"idempotency_key": "capacity-verification"}),
                content_type="application/json",
            )
        queue.assert_called_once()
        self.assertEqual(response.status_code, 429, response.content)
        self.assertEqual(response.json()["errors"][0]["code"], "internal_capacity")

    @override_settings(ACCOUNT_RATE_LIMITS={"origin_verification": "2/h/user,100/h/ip"})
    def test_verification_queue_is_throttled_before_creating_more_jobs(self):
        verification, _challenge = create_origin_verification(
            project=self.project,
            user=self.owner,
            origin=self.project.canonical_origin,
        )
        client = Client()
        client.force_login(self.owner)
        path = (
            f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/"
            f"origin-verifications/{verification.pk}/"
        )
        for key in ("throttle-one", "throttle-two"):
            response = client.post(
                path,
                data=json.dumps({"idempotency_key": key}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 202)
        response = client.post(
            path,
            data=json.dumps({"idempotency_key": "throttle-three"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(JobRun.objects.filter(handler="verify_project_origin").count(), 2)


class OriginVerificationConcurrencyTests(TransactionTestCase):
    def test_queue_reloads_challenge_after_concurrent_rotation(self):
        user_model = get_user_model()
        owner = user_model.objects.create_user("security-race@example.com", password="test-password")
        EmailAddress.objects.create(user=owner, email=owner.email, verified=True, primary=True)
        organization = create_organization(user=owner, name="Security race org")
        project = create_project(
            organization=organization,
            user=owner,
            name="Security race project",
            canonical_origin="https://race.example.com",
        )
        stale, _challenge = create_origin_verification(
            project=project,
            user=owner,
            origin=project.canonical_origin,
        )
        old_digest = stale.challenge_digest
        barrier = Barrier(2)

        def rotate():
            close_old_connections()
            try:
                with transaction.atomic():
                    Organization.objects.select_for_update().get(pk=organization.pk)
                    barrier.wait()
                    create_origin_verification(
                        project=ProjectOriginVerification.objects.select_related("project").get(pk=stale.pk).project,
                        user=user_model.objects.get(pk=owner.pk),
                        origin=project.canonical_origin,
                    )
            finally:
                close_old_connections()

        def queue():
            close_old_connections()
            try:
                barrier.wait()
                return queue_origin_verification(
                    verification=stale,
                    actor=user_model.objects.get(pk=owner.pk),
                    idempotency_key="verification-race",
                ).pk
            finally:
                close_old_connections()

        with patch("jobs.services.dispatch_pending"), ThreadPoolExecutor(max_workers=2) as executor:
            rotate_future = executor.submit(rotate)
            queue_future = executor.submit(queue)
            rotate_future.result(timeout=10)
            job_id = queue_future.result(timeout=10)

        current = ProjectOriginVerification.objects.get(pk=stale.pk)
        job = JobRun.objects.get(pk=job_id)
        self.assertNotEqual(current.challenge_digest, old_digest)
        self.assertEqual(job.config_snapshot, {"challenge_digest": current.challenge_digest})
