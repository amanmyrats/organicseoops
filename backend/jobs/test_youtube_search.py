from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as utc
import json
from threading import Event
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from providers.models import YouTubeAPIKey
from providers.youtube_key import set_youtube_key, revoke_youtube_key
from tenancy.models import ProjectConfiguration, OrganizationTrial
from tenancy.models import OrganizationMembership, MembershipRole
from .models import JobRun, JobStatus, UsageReservation, Artifact, TopicCandidateSnapshot, SourceCitation
from .recovery import reconcile_stuck_youtube_search
from .youtube import YouTubeSourceError
from .youtube_search import search_youtube, youtube_quota_day, POLICY_VERSION
from config.test_foundations import TEST_STORAGES

ENCRYPTION = Fernet.generate_key().decode()
SETTINGS = {"PROVIDER_ENCRYPTION_KEYS": (ENCRYPTION,),
    "STORAGES": TEST_STORAGES,
    "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}}


def setup_case(case):
    from .test_youtube import YouTubeSourceTests
    YouTubeSourceTests.setUp(case)
    cache.clear()
    case.staff = get_user_model().objects.create_superuser("yt-search-staff@example.invalid", "test-password")
    set_youtube_key(actor=case.staff, value=case.key, api_project="client-project", daily_limit=5)


@override_settings(**SETTINGS)
class YouTubeSearchTests(TransactionTestCase):
    def setUp(self):
        setup_case(self)

    def search(self, key="search-1", **kwargs):
        return search_youtube(project=self.project, actor=self.owner, selection=self.selection,
            policy_version=POLICY_VERSION, accepted=True, request_key=key,
            transport=kwargs.pop("transport", lambda **unused: self.page), **kwargs)

    def test_response_metadata_never_enters_database_artifacts_or_customer_export(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from io import BytesIO
        from zipfile import ZipFile
        result = self.search()
        self.assertEqual(result["page"], self.page)
        job = JobRun.objects.get(pk=result["job_id"])
        self.assertEqual((job.status, job.output, job.usage.actual_units), ("succeeded", {}, 1))
        self.assertEqual((Artifact.objects.count(), TopicCandidateSnapshot.objects.count(), SourceCitation.objects.count()), (0, 0, 0))
        job.output = self.page
        with self.assertRaises(ValidationError):
            job.save()
        archive = complete_bounded_customer_archive(organization=self.project.organization, actor=self.owner)
        # Full logical DB backup contains only these input/status rows; no API result table exists.
        stored = json.dumps(list(JobRun.objects.values()), cls=DjangoJSONEncoder)
        for marker in ("video_12345", "Original channel title", "bounded-next-token"):
            self.assertNotIn(marker, stored)
        with ZipFile(BytesIO(archive)) as zipped:
            text = "".join(zipped.read(name).decode() for name in zipped.namelist())
        self.assertNotIn("video_12345", text)
        with self.assertRaises(YouTubeSourceError) as denied:
            self.search()
        self.assertEqual(denied.exception.category, "request_already_attempted")
        self.assertEqual(YouTubeAPIKey.objects.get().attempted_requests, 1)

    def test_api_csrf_role_foreign_policy_and_no_history_delivery(self):
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/youtube-search/"
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get(path).status_code, 401)
        browser.force_login(self.outsider)
        self.assertEqual(browser.get(path).status_code, 404)
        browser.force_login(self.owner)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        data = {"selection": self.selection, "policy_version": POLICY_VERSION, "accepted": True, "request_key": "api-1"}
        def post(payload, csrf=True):
            return browser.post(path, json.dumps(payload), content_type="application/json", secure=True,
                **({"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"} if csrf else {}))
        self.assertEqual(post(data, False).status_code, 403)
        with patch("jobs.youtube_search.youtube_search_request", return_value=self.page) as transport:
            self.assertEqual(post({**data, "accepted": False}).status_code, 409)
            self.assertEqual(post({**data, "policy_version": "old"}).status_code, 409)
            response = post(data)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response.json()["page"], self.page)
            self.assertEqual(post(data).status_code, 409)
            self.assertEqual(transport.call_count, 1)
        self.assertNotIn("page", browser.get(path).json())

    def test_quota_failures_revoke_source_expiry_and_unknown_crash_never_replay(self):
        def fail(**unused):
            raise YouTubeSourceError("quota_or_access_denied")
        with self.assertRaises(YouTubeSourceError):
            self.search(transport=fail)
        self.assertEqual(JobRun.objects.get().usage.actual_units, 1)
        def mutate(**unused):
            ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=[])
            return self.page
        with self.assertRaises(PermissionDenied):
            self.search("source-change", transport=mutate)
        self.assertEqual(JobRun.objects.latest("pk").output, {})
        ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=["service news"])
        def revoke(**unused):
            revoke_youtube_key(actor=self.staff)
            return self.page
        with self.assertRaises(ValidationError):
            self.search("revoke", transport=revoke)
        set_youtube_key(actor=self.staff, value=self.key, api_project="client-project", daily_limit=5)
        def crash(**unused):
            raise SystemExit
        with self.assertRaises(SystemExit):
            self.search("crash", transport=crash)
        current = JobRun.objects.latest("pk")
        JobRun.objects.filter(pk=current.pk).update(updated_at=timezone.now() - timedelta(seconds=100))
        self.assertEqual(reconcile_stuck_youtube_search(), 1)
        current.refresh_from_db()
        self.assertEqual((current.error_category, current.usage.actual_units), ("request_outcome_unknown", 1))
        self.assertEqual(reconcile_stuck_youtube_search(), 0)
        trial = OrganizationTrial.objects.get(organization=self.project.organization)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1))
        from .usage import UsageLimitError
        with self.assertRaises(UsageLimitError):
            self.search("expired")
        self.assertEqual(YouTubeAPIKey.objects.get().attempted_requests, 4)

    def test_client_limit_and_pacific_midnight_do_not_reset_on_rotation(self):
        before = youtube_quota_day(datetime(2026, 10, 1, 6, 59, tzinfo=utc.utc))
        after = youtube_quota_day(datetime(2026, 10, 1, 7, 1, tzinfo=utc.utc))
        self.assertEqual((str(before), str(after)), ("2026-09-30", "2026-10-01"))
        with patch("jobs.youtube_search.youtube_quota_day", return_value=before):
            self.search()
        record = YouTubeAPIKey.objects.get()
        self.assertEqual(str(record.quota_day), "2026-09-30")
        # Midnight Pacific begins a new bucket, independent of UTC date.
        with patch("jobs.youtube_search.youtube_quota_day", return_value=after):
            self.search("new-day")
        record.refresh_from_db()
        self.assertEqual((str(record.quota_day), record.attempted_requests), ("2026-10-01", 1))
        set_youtube_key(actor=self.staff, value=self.key, api_project="client-project", daily_limit=1)
        with patch("jobs.youtube_search.youtube_quota_day", return_value=after), self.assertRaises(YouTubeSourceError) as denied:
            self.search("over-limit")
        self.assertEqual(denied.exception.category, "client_daily_quota")

    def test_viewer_cancellation_and_inflight_trial_expiry_cannot_deliver(self):
        from .models import JobCancellation
        from .usage import UsageLimitError
        OrganizationMembership.objects.create(organization=self.project.organization, user=self.outsider, role=MembershipRole.VIEWER)
        with self.assertRaises(PermissionDenied):
            search_youtube(project=self.project, actor=self.outsider, selection=self.selection,
                policy_version=POLICY_VERSION, accepted=True, request_key="viewer", transport=lambda **kw: self.page)
        self.assertFalse(JobRun.objects.exists())
        def cancel(**unused):
            JobCancellation.objects.create(job=JobRun.objects.get(), requested_by=self.owner)
            return self.page
        with self.assertRaises(YouTubeSourceError) as denied:
            self.search(transport=cancel)
        self.assertEqual(denied.exception.category, "cancelled")
        def expire(**unused):
            OrganizationTrial.objects.filter(organization=self.project.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1))
            return self.page
        with self.assertRaises(UsageLimitError):
            self.search("inflight-expiry", transport=expire)
        self.assertEqual(list(JobRun.objects.values_list("output", flat=True)), [{}, {}])
        self.assertEqual(list(UsageReservation.objects.values_list("actual_units", flat=True)), [1, 1])
        from .youtube import validate_youtube_selection
        with self.assertRaises(ValidationError):
            validate_youtube_selection({**self.selection, "phrase": "service -news"})


@override_settings(**SETTINGS)
class YouTubeQuotaConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup_case(self)
        from tenancy.services import create_organization, create_project, update_project_configuration
        other_org = create_organization(user=self.outsider, name="Other synthetic video org")
        self.other_project = create_project(organization=other_org, user=self.outsider, name="Other synthetic video site",
            canonical_origin="https://other-video.example.invalid")
        update_project_configuration(project=self.other_project, user=self.outsider, expected_revision=0,
            changes={"seed_topics": ["service news"], "target_languages": ["en"]})

    def test_two_connections_share_one_client_inflight_slot(self):
        started, release = Event(), Event()
        def transport(**unused):
            started.set()
            if not release.wait(20):
                raise AssertionError("Concurrent fixture did not release.")
            return self.page
        def run():
            close_old_connections()
            try:
                return search_youtube(project=self.project, actor=self.owner, selection=self.selection,
                    policy_version=POLICY_VERSION, accepted=True, request_key="thread-1", transport=transport)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(run)
            try:
                self.assertTrue(started.wait(20))
                with self.assertRaises(YouTubeSourceError) as denied:
                    search_youtube(project=self.other_project, actor=self.outsider, selection=self.selection,
                        policy_version=POLICY_VERSION, accepted=True, request_key="thread-2", transport=transport)
                self.assertEqual(denied.exception.category, "client_busy")
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=20)["page"], self.page)
        self.assertEqual((JobRun.objects.count(), YouTubeAPIKey.objects.get().attempted_requests), (1, 1))
