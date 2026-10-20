import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_api as api, competitor_collection as root, competitor_page_formats_collection as page
from . import test_competitor_api as root_fixtures, test_competitor_page_formats_collection as page_fixtures
from .models import Artifact, JobCancellation, JobRun, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "competitor-page-formats-api"}})
class CompetitorPageFormatsApiTests(TransactionTestCase):
    transport = root_fixtures.CompetitorApiTests.transport
    fetcher = page_fixtures.CompetitorPageFormatsCollectionTests.fetcher
    HTML = page_fixtures.CompetitorPageFormatsCollectionTests.HTML
    revoke = root_fixtures.CompetitorApiTests.revoke
    post = root_fixtures.CompetitorApiTests.post
    command = root_fixtures.CompetitorApiTests.command

    def setUp(self):
        root_fixtures.CompetitorApiTests.setUp(self)
        self.root_data = dict(self.data)
        self.data["url"] = self.data["origin"] + "/selected/article"
        self.root_base = self.base
        self.base = self.base.replace("competitor-roots/", "competitor-page-formats/")

    def test_actual_page_preview_once_only_queue_own_lookup_private_original_uri_independent_reader_and_closed_root(self):
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            command = self.command("page-api")
            preview = self.post("selection/").json()
            self.assertEqual(preview["selection"]["method"], page.METHOD)
            self.assertFalse(JobRun.objects.exists())
            queued = self.post(data=command); self.assertEqual(queued.status_code, 202, queued.content)
            job_id = queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
            self.assertEqual(self.client.get(self.base + "?idempotency_key=page-api", secure=True).json()["jobs"][0]["id"], job_id)
            self.assertEqual(self.client.get(self.root_base, secure=True).json()["jobs"], [])
            old_page = self.root_base.replace("competitor-roots/", "competitor-pages/")
            self.assertEqual(self.client.get(old_page, secure=True).json()["jobs"], [])
            self.assertEqual(self.client.get(old_page + f"{job_id}/", secure=True).status_code, 403)
            self.assertEqual(self.client.get(self.root_base + f"{job_id}/", secure=True).status_code, 403)
            self.assertTrue(page.execute_competitor_page_formats_collection(job_id, fetcher=self.fetcher()))
            response = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["evidence"]["collection"]["evidence"]["counts"],
                {"p": 1, "ul": 1, "ol": 0, "table": 0, "img": 1, "picture": 0, "video": 0, "audio": 0})
            self.assertEqual(response.json()["evidence"]["collection"]["requested_url"], self.data["url"])
            self.assertEqual(self.connections[1].request.call_args.args, ("GET", "/selected/article"))
            self.assertNotIn(b"private@example.invalid", response.content)
            self.assertNotIn(b"Private transient title", response.content)
            links_base = self.root_base.replace("competitor-roots/", "competitor-links-roots/")
            self.assertEqual(self.client.get(links_base, secure=True).json()["jobs"], [])
            self.assertEqual(self.client.get(links_base + f"{job_id}/", secure=True).status_code, 403)
            schema_base = self.root_base.replace("competitor-roots/", "competitor-schema-roots/")
            self.assertEqual(self.client.get(schema_base, secure=True).json()["jobs"], [])
            self.assertEqual(self.client.get(schema_base + f"{job_id}/", secure=True).status_code, 403)
            date_base = self.root_base.replace("competitor-roots/", "competitor-page-dates/")
            self.assertEqual(self.client.get(date_base, secure=True).json()["jobs"], [])
            self.assertEqual(self.client.get(date_base + f"{job_id}/", secure=True).status_code, 403)
            reference_base = self.root_base.replace("competitor-roots/", "competitor-page-destinations/")
            self.assertEqual(self.client.get(reference_base, secure=True).json()["jobs"], [])
            self.assertEqual(self.client.get(reference_base + f"{job_id}/", secure=True).status_code, 403)
            heading_base = self.root_base.replace("competitor-roots/", "competitor-page-headings/")
            self.assertEqual(self.client.get(heading_base, secure=True).json()["jobs"], [])
            self.assertEqual(self.client.get(heading_base + f"{job_id}/", secure=True).status_code, 403)
            self.assertEqual(self.client.post(heading_base + f"{job_id}/", "{}", content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 403)
            self.assertEqual(self.client.get(self.root_base + f"comparison/?previous_job_id={job_id}&current_job_id={job_id+1}", secure=True).status_code, 403)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
            other = Client(); other.force_login(self.admin)
            self.assertEqual(other.get(self.base + f"{job_id}/", secure=True).json()["evidence"], response.json()["evidence"])
            self.assertEqual(other.get(self.base + "?idempotency_key=page-api", secure=True).json()["jobs"], [])
            waiting = self.post(data=self.command("page-cancel")).json()["job"]["id"]
            self.assertEqual(self.post(f"{waiting}/", {}).status_code, 202)
            replay = self.post(data=self.command("page-cancel"))
            self.assertEqual((replay.status_code, replay.json()["job"]["id"], replay.json()["job"]["status"]), (202, waiting, "cancelled"))
            self.assertFalse(page.execute_competitor_page_formats_collection(job_id, fetcher=self.fetcher()))

    def test_exact_fields_csrf_declarations_digest_method_family_project_and_retained_expiry(self):
        command = self.command()
        self.assertEqual(self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True).status_code, 403)
        original_digest = api._digest(root.selection_snapshot(self.project, self.owner, self.root_data))
        for change in ({"handler": root.HANDLER}, {"raw_body": "private"}, {"url": self.data["origin"] + "/"},
            {"url": self.data["origin"] + "/other"}, {"url": self.data["url"] + "?secret=x"}, {"url": "https://foreign.example.invalid/page"}, {"collection_permission": 1},
            {"use_permission": False}, {"storage_permission": "true"}, {"selection_digest": original_digest}):
            cache.clear()
            self.assertIn(self.post(data={**command, **change}).status_code, (403, 409))
        self.assertFalse(JobRun.objects.exists())
        for body in ('{"origin":"x","origin":"y"}', '{', 'null', '[]', '{"origin":NaN}', ' ' * 2049):
            cache.clear()
            response = self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.post("?handler=collect_competitor_root", command).status_code, 400)
        for query in ("?other=1", "?idempotency_key=a&idempotency_key=a"):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 409)
        self.assertEqual(self.client.get(self.base + "selection/", secure=True).status_code, 405)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        job_id = self.post(data=command).json()["job"]["id"]
        page.execute_competitor_page_formats_collection(job_id, fetcher=self.fetcher())
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        wrong = self.base.replace(f"projects/{self.project.pk}/", f"projects/{other.pk}/")
        self.assertEqual(self.client.get(wrong + f"{job_id}/", secure=True).status_code, 403)
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 404)
        self.client.force_login(self.owner)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(days=1))
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
        self.assertEqual(self.client.get(self.base + f"{job_id}/", secure=True).status_code, 403)
        self.assertEqual(self.post("selection/").status_code, 403)

    def test_four_page_budgets_are_independent_of_each_other_all_three_roots_and_shared_ip(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        other = Client(); other.force_login(self.admin)
        actions = ("read", "selection", "request", "cancel")
        limits = {f"{family}_{action}": "1/h/ip" for family in ("competitor_root", "competitor_schema_root", "competitor_links_root", "competitor_page", "competitor_page_headings", "competitor_page_destinations", "competitor_page_dates", "competitor_page_formats") for action in actions}
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS=limits):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base, secure=True).status_code, 429)
            self.assertEqual(self.client.get(self.root_base, secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.root_base.replace("competitor-roots/", "competitor-pages/"), secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.root_base.replace("competitor-roots/", "competitor-schema-roots/"), secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.root_base.replace("competitor-roots/", "competitor-links-roots/"), secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.root_base.replace("competitor-roots/", "competitor-page-headings/"), secure=True).status_code, 200)
            self.assertEqual(self.post("selection/").status_code, 200)
            self.assertEqual(self.post("selection/").status_code, 429)
            self.assertEqual(self.post(data=command).status_code, 202)
            self.assertEqual(self.post(data=command).status_code, 429)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)
        from django.conf import settings
        self.assertTrue(all(f"competitor_page_formats_{action}" in settings.ACCOUNT_RATE_LIMITS for action in actions))

    def test_final_queue_metadata_then_original_source_cancel_commercial_and_serialization_rollback(self):
        original_metadata, original_response = api._metadata, api._response
        for family in ("page", "root"):
            self.base = self.root_base.replace("competitor-roots/", "competitor-page-formats/") if family == "page" else self.root_base
            self.data = {**self.root_data, "url": self.root_data["origin"] + "/selected/article"} if family == "page" else dict(self.root_data)
            command = self.command("final-" + family)
            for loss in ("actor", "configuration", "cancel", "expiry", "verified"):
                with self.subTest(family=family, loss=loss), transaction.atomic():
                    clock, calls = [timezone.now()], [0]
                    deadline = clock[0] + timedelta(seconds=20)
                    OrganizationTrial.objects.filter(organization=self.organization).update(started_at=deadline-timedelta(days=30), ends_at=deadline)
                    def changed(job_id):
                        value = original_metadata(job_id); calls[0] += 1
                        if calls[0] == 2:
                            if loss == "actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin")
                            elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]])
                            elif loss == "cancel": JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)
                            elif loss == "expiry": clock[0] = deadline
                            else: EmailAddress.objects.filter(user=self.owner).update(verified=False)
                        return value
                    with patch.object(api, "_metadata", side_effect=changed), patch("jobs.usage.timezone.now", side_effect=lambda: clock[0]), \
                        patch("jobs.tasks.execute_competitor_page_formats_collection_task.apply_async") as page_dispatch, \
                        patch("jobs.tasks.execute_competitor_collection_task.apply_async") as root_dispatch:
                        response = self.post(data=command)
                    self.assertEqual(calls[0], 2)
                    self.assertEqual(response.status_code, 403, response.content)
                    self.assertFalse(JobRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
                    page_dispatch.assert_not_called(); root_dispatch.assert_not_called()
                    transaction.set_rollback(True)
        self.base = self.root_base.replace("competitor-roots/", "competitor-page-formats/")
        self.data = {**self.root_data, "url": self.root_data["origin"] + "/selected/article"}
        command = self.command("serialize")
        with transaction.atomic():
            def changed_response(data, *args, **kwargs):
                response = original_response(data, *args, **kwargs)
                if "job" in data: self.revoke()
                return response
            with patch.object(api, "_response", side_effect=changed_response): response = self.post(data=command)
            self.assertEqual(response.status_code, 403)
            self.assertFalse(JobRun.objects.exists()); transaction.set_rollback(True)

    def test_genuine_empty_unavailable_and_private_last_metadata_original_actor_independent_reader_losses(self):
        job_id = self.post(data=self.command()).json()["job"]["id"]
        page.execute_competitor_page_formats_collection(job_id, fetcher=self.fetcher())
        self.client.force_login(self.admin)
        healthy = self.client.get(self.base + f"{job_id}/", secure=True)
        self.assertEqual(healthy.status_code, 200)
        original = api._metadata
        for loss in ("original_actor", "caller", "configuration", "cancel", "organization", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = [0]
                def changed(pk):
                    value = original(pk); calls[0] += 1
                    if calls[0] == 2:
                        if loss == "original_actor": self.revoke()
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]])
                        elif loss == "cancel": JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)
                        elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                        else:
                            now = timezone.now()
                            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(days=1))
                    return value
                with patch.object(api, "_metadata", side_effect=changed): response = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertIn(response.status_code, (403, 409), response.content)
                self.assertNotIn(b'"counts"', response.content); transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + f"{job_id}/", secure=True).json(), healthy.json())
        with transaction.atomic():
            original_response = api._response
            def changed_artifact(data, *args, **kwargs):
                response = original_response(data, *args, **kwargs)
                if "evidence" in data: Artifact.objects.filter(job_id=job_id).update(size_bytes=1)
                return response
            with patch.object(api, "_response", side_effect=changed_artifact):
                response = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(response.status_code, 403, response.content)
            transaction.set_rollback(True)
        self.client.force_login(self.owner)
        for state, body in (("observed", b'<h1>No selected elements</h1>'), ("unavailable", b"<title>Unclosed")):
            pk = self.post(data=self.command(state)).json()["job"]["id"]
            page.execute_competitor_page_formats_collection(pk, fetcher=self.fetcher(body=body))
            response = self.client.get(self.base + f"{pk}/", secure=True)
            self.assertEqual(response.status_code, 200, response.content)
            evidence = response.json()["evidence"]["collection"]["evidence"]
            self.assertEqual(evidence["state"], state)
            self.assertTrue(all(value == (0 if state == "observed" else None) for value in evidence["counts"].values()))
            
    def test_all_seven_old_static_families_cannot_enter_fixed_format_history_detail_or_cancel(self):
        families = ("collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates")
        ids = []
        for handler in families:
            data = self.data if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates"} else self.root_data
            job = root.queue_competitor_collection(project=self.project, actor=self.owner, data=data,
                idempotency_key="old-" + handler, handler=handler)
            ids.append(job.pk)
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(root.execute_competitor_collection(job.pk, fetcher=self.fetcher(), handler=handler))
            self.assertEqual(self.client.get(self.base, secure=True).json()["jobs"], [])
            self.assertEqual(self.client.get(self.base + f"{job.pk}/", secure=True).status_code, 403)
            self.assertEqual(self.post(f"{job.pk}/", {}).status_code, 403)
            job.refresh_from_db(); self.assertEqual(job.status, "succeeded")
            self.assertFalse(JobCancellation.objects.filter(job=job).exists())
        response = self.client.get(self.base + f"comparison/?previous_job_id={ids[0]}&current_job_id={ids[1]}", secure=True)
        self.assertEqual(response.status_code, 403)
