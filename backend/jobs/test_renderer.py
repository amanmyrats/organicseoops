from tenancy.customer_artifact_barrier import project_artifact_barrier
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from celery.exceptions import Retry
from django.test import TransactionTestCase, override_settings

from config.artifacts import save_private_artifact
from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import project_artifact_scope
from tenancy.services import create_organization, create_project

from . import renderer
from .models import Artifact, CrawlPageSnapshot, CrawlRun, JobCancellation, JobRun, RenderAttempt, RenderedPageSnapshot
from .renderer import METHOD_VERSION, _write_spool, render_page_snapshot


@override_settings(
    STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/csv", "text/html", "text/plain"}),
)
class RendererTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("renderer@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Renderer org")
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="Renderer project",
            canonical_origin="https://render.example.com",
        )
        self.job = JobRun.objects.create(
            organization=self.organization,
            project=self.project,
            actor=self.owner,
            handler="crawl_site",
            input_snapshot={"seeds": [], "page_limit": 3},
            config_snapshot={"host_delay_seconds": 1},
            method_version="crawl-http-v1",
        )
        self.run = CrawlRun.objects.create(
            job=self.job,
            organization=self.organization,
            project=self.project,
            page_limit=3,
        )

    def page(self, raw_html, *, url="https://render.example.com/"):
        source_hash = hashlib.sha256(raw_html).hexdigest()
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_private_artifact(
                scope=f"{project_artifact_scope(self.project)}/jobs/{self.job.pk}",
                content=raw_html,
                content_type="text/html",
                key_stem=source_hash[:32],
            )
        artifact = Artifact.objects.create(
            job=self.job,
            project=self.project,
            key=key,
            content_type="text/html",
            size_bytes=len(raw_html),
        )
        return CrawlPageSnapshot.objects.create(
            crawl_run=self.run,
            project=self.project,
            requested_url=url,
            final_url=url,
            status_code=200,
            content_hash=source_hash,
            raw_artifact=artifact,
            title="Raw title",
            headings=[{"level": "h1", "text": "Raw"}],
        )

    def test_inline_javascript_difference_is_immutable_evidence(self):
        page = self.page(
            b'<title>Raw title</title><h1 id="value">Raw</h1>'
            b'<script>document.title="Rendered title";document.querySelector("#value").textContent="Rendered"</script>'
        )
        rendered = b'<html><head><title>Rendered title</title></head><body><h1 id="value">Rendered</h1></body></html>'
        with TemporaryDirectory() as requests, TemporaryDirectory() as results:
            wrote = False

            def respond(_seconds):
                nonlocal wrote
                if wrote:
                    return
                filename = next(Path(requests).iterdir()).name
                request = json.loads((Path(requests) / filename).read_text())
                _write_spool(Path(results), filename, {
                    "protocol": request["protocol"],
                    "request_id": request["request_id"],
                    "token": request["token"],
                    "request_hash": request["request_hash"],
                    "source_hash": request["source_hash"],
                    "method_version": request["method_version"],
                    "status": "partial",
                    "error_category": "external_resources_blocked",
                    "duration_ms": 12,
                    "blocked_requests": [
                        {"kind": "request", "url": "https://user:password@cdn.example.test/image.png?token=secret#marker"},
                        {"kind": "websocket", "url": "wss://socket.example.test/feed?ticket=secret#fragment"},
                        {"kind": "popup", "url": "https://popup.example.test/path?code=secret#fragment"},
                    ],
                    "html_b64": base64.b64encode(rendered).decode(),
                })
                wrote = True

            observation = render_page_snapshot(
                page.pk,
                request_dir=Path(requests),
                result_dir=Path(results),
                sleep=respond,
            )

        self.assertIsInstance(observation, RenderedPageSnapshot)
        self.assertEqual(observation.attempt.status, RenderAttempt.Status.PARTIALLY_SUCCEEDED)
        self.assertEqual(observation.method_version, METHOD_VERSION)
        self.assertEqual((observation.title, observation.text_excerpt), ("Rendered title", "Rendered title Rendered"))
        self.assertTrue(observation.comparison["content_changed"])
        self.assertTrue(observation.comparison["title_changed"])
        self.assertEqual(observation.comparison["completeness"], "unknown")
        self.assertIn("not proof of search-engine rendering", observation.comparison["observation_label"])
        self.assertEqual(observation.blocked_requests, [
            {"kind": "request", "url": "https://cdn.example.test/image.png"},
            {"kind": "websocket", "url": "wss://socket.example.test/feed"},
            {"kind": "popup", "url": "https://popup.example.test/path"},
        ])
        self.assertNotIn("secret", json.dumps(observation.blocked_requests))
        with self.assertRaises(ValidationError):
            observation.save()

    def test_task_retries_only_prework_admission_and_rechecks_cancellation_before_spool(self):
        from functools import partial
        from config.artifacts import ArtifactStorageError
        from tenancy.customer_artifact_barrier import ArtifactAdmissionUnavailable
        from tenancy.models import ProjectArtifactMutationAttempt
        from .tasks import execute_render_task
        page = self.page(b"<title>Raw retry fixture</title>")
        with TemporaryDirectory() as requests, TemporaryDirectory() as results:
            render = partial(render_page_snapshot, request_dir=Path(requests), result_dir=Path(results))
            real_retry = execute_render_task.retry
            def worker(retries=None):
                close_old_connections()
                if retries is not None:
                    execute_render_task.push_request(retries=retries, called_directly=False, is_eager=False,
                        id="00000000-0000-0000-0000-000000000001", args=(page.pk,), kwargs={})
                try:
                    return execute_render_task.run(page.pk)
                finally:
                    if retries is not None:
                        execute_render_task.pop_request()
                    close_old_connections()
            with patch("jobs.tasks.render_page_snapshot", side_effect=render), \
                    patch.object(execute_render_task, "retry", side_effect=Retry()) as retry:
                with project_artifact_barrier(self.organization.pk, shared=False):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with self.assertRaises(Retry):
                            pool.submit(worker).result(timeout=10)
                    self.assertFalse(RenderAttempt.objects.exists())
                    self.assertFalse(ProjectArtifactMutationAttempt.objects.filter(organization=self.organization).exists())
                    self.assertEqual(list(Path(requests).iterdir()), [])
                    self.assertIsInstance(retry.call_args.kwargs["exc"], ArtifactAdmissionUnavailable)
                    self.assertEqual(retry.call_args.kwargs["countdown"], 10)
                    with patch.object(execute_render_task, "retry", wraps=real_retry), \
                            patch.object(execute_render_task, "apply_async") as publish:
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            with self.assertRaises(Retry):
                                pool.submit(worker, 7).result(timeout=10)
                            self.assertEqual(publish.call_args.kwargs["countdown"], 120)
                            self.assertEqual(publish.call_args.args[0], (page.pk,))
                            self.assertEqual(publish.call_args.kwargs["task_id"], "00000000-0000-0000-0000-000000000001")
                            self.assertEqual(publish.call_args.kwargs["retries"], 8)
                            publish.reset_mock()
                            with self.assertRaises(ArtifactAdmissionUnavailable):
                                pool.submit(worker, 8).result(timeout=10)
                            publish.assert_not_called()
                    self.assertFalse(RenderAttempt.objects.exists())
                retry.reset_mock()
                def response(_directory, filename):
                    request = json.loads((Path(requests) / filename).read_text())
                    return {**{field: request[field] for field in ("protocol", "request_id", "token", "request_hash",
                        "source_hash", "method_version", "html_b64")}, "status": "succeeded", "error_category": "",
                        "duration_ms": 1, "blocked_requests": []}
                with patch("jobs.renderer._read_spool", side_effect=response):
                    self.assertTrue(execute_render_task.run(page.pk))
                retry.assert_not_called()
                self.assertEqual(RenderAttempt.objects.count(), 1)
                self.assertEqual(RenderedPageSnapshot.objects.count(), 1)
                self.assertEqual(list(Path(requests).iterdir()), [])
                def lose_admitted_session(_page_id):
                    with project_artifact_barrier(self.organization.pk, shared=True) as owner:
                        owner.close()
                with patch("jobs.tasks.render_page_snapshot", side_effect=lose_admitted_session), \
                        self.assertRaisesRegex(ArtifactStorageError, "admission was lost") as lost:
                    execute_render_task.run(page.pk)
                self.assertNotIsInstance(lost.exception, ArtifactAdmissionUnavailable)
                retry.assert_not_called()
                JobCancellation.objects.create(job=self.job, requested_by=self.owner)
                with self.assertRaisesRegex(ValidationError, "no longer permits rendering"):
                    execute_render_task.run(page.pk)
                retry.assert_not_called()
                self.assertEqual(RenderAttempt.objects.count(), 1)
                self.assertEqual(list(Path(requests).iterdir()), [])


    def test_tampered_result_fails_without_observation(self):
        page = self.page(b"<title>Raw title</title>")
        with TemporaryDirectory() as requests, TemporaryDirectory() as results:
            wrote = False

            def respond(_seconds):
                nonlocal wrote
                if wrote:
                    return
                filename = next(Path(requests).iterdir()).name
                request = json.loads((Path(requests) / filename).read_text())
                _write_spool(Path(results), filename, {
                    "protocol": request["protocol"],
                    "request_id": request["request_id"],
                    "token": "0" * 64,
                    "request_hash": request["request_hash"],
                    "source_hash": request["source_hash"],
                    "method_version": request["method_version"],
                    "status": "succeeded",
                    "error_category": "",
                    "duration_ms": 1,
                    "blocked_requests": [],
                    "html_b64": request["html_b64"],
                })
                wrote = True

            attempt = render_page_snapshot(
                page.pk,
                request_dir=Path(requests),
                result_dir=Path(results),
                sleep=respond,
            )

        self.assertIsInstance(attempt, RenderAttempt)
        self.assertEqual((attempt.status, attempt.error_category), (RenderAttempt.Status.FAILED, "render_protocol_failed"))
        self.assertFalse(RenderedPageSnapshot.objects.exists())

    def test_symlink_result_and_render_budget_fail_closed(self):
        page = self.page(b"<title>Raw title</title>")
        with TemporaryDirectory() as requests, TemporaryDirectory() as results, TemporaryDirectory() as outside:
            wrote = False

            def attack(_seconds):
                nonlocal wrote
                if wrote:
                    return
                filename = next(Path(requests).iterdir()).name
                target = Path(outside) / "result.json"
                target.write_text("{}")
                (Path(results) / filename).symlink_to(target)
                wrote = True

            attempt = render_page_snapshot(
                page.pk,
                request_dir=Path(requests),
                result_dir=Path(results),
                sleep=attack,
            )
        self.assertEqual((attempt.status, attempt.error_category), (RenderAttempt.Status.FAILED, "render_protocol_failed"))

        for number in range(2):
            RenderAttempt.objects.create(
                crawl_page=page,
                project=self.project,
                token_hash=hashlib.sha256(f"token-{number}".encode()).hexdigest(),
                request_hash=hashlib.sha256(f"request-{number}".encode()).hexdigest(),
                source_hash=page.content_hash,
                method_version=METHOD_VERSION,
            )
        with TemporaryDirectory() as requests, TemporaryDirectory() as results:
            with self.assertRaisesMessage(ValidationError, "at most 3"):
                render_page_snapshot(page.pk, request_dir=Path(requests), result_dir=Path(results), timeout=0.01)

    def test_cancellation_after_result_read_prevents_artifact_persistence(self):
        page = self.page(b"<title>Raw title</title>")
        artifact_count = Artifact.objects.count()
        original_read = renderer._read_spool
        with TemporaryDirectory() as requests, TemporaryDirectory() as results:
            wrote = False

            def respond(_seconds):
                nonlocal wrote
                if wrote:
                    return
                filename = next(Path(requests).iterdir()).name
                request = json.loads((Path(requests) / filename).read_text())
                _write_spool(Path(results), filename, {
                    "protocol": request["protocol"], "request_id": request["request_id"],
                    "token": request["token"], "request_hash": request["request_hash"],
                    "source_hash": request["source_hash"], "method_version": request["method_version"],
                    "status": "succeeded", "error_category": "", "duration_ms": 1,
                    "blocked_requests": [], "html_b64": request["html_b64"],
                })
                wrote = True

            def cancel_after_read(*args, **kwargs):
                result = original_read(*args, **kwargs)
                JobCancellation.objects.create(job=self.job, requested_by=self.owner)
                return result

            with patch("jobs.renderer._read_spool", side_effect=cancel_after_read):
                attempt = render_page_snapshot(
                    page.pk, request_dir=Path(requests), result_dir=Path(results), sleep=respond,
                )

        self.assertEqual((attempt.status, attempt.error_category), (RenderAttempt.Status.FAILED, "cancelled"))
        self.assertEqual(Artifact.objects.count(), artifact_count)
        self.assertFalse(RenderedPageSnapshot.objects.exists())
