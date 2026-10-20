from queue import Empty

from celery.exceptions import QueueNotFound
from django.contrib.staticfiles.storage import staticfiles_storage
from django.test import SimpleTestCase, override_settings
from kombu import Connection, Producer
from kombu.exceptions import ContentDisallowed

from .celery import app


class CeleryConfigurationTests(SimpleTestCase):
    def test_queue_routing_and_json_acceptance_with_memory_transport(self):
        self.assertEqual(set(app.amqp.queues), {"default", "ai", "crawl", "audit"})
        self.assertIsNone(app.conf.result_backend)
        self.assertTrue(app.conf.task_ignore_result)
        self.assertEqual({item["task"] for item in app.conf.beat_schedule.values()},
                          {"jobs.schedule_due", "jobs.reconcile", "tenancy.poll_ses_feedback",
                           "tenancy.schedule_organization_notices", "tenancy.purge_public_analytics",
                           "tenancy.purge_public_contact", "tenancy.purge_expired_customer_copies",
                           "accounts.purge_retained_trial_identities",
                           "jobs.scan_weekly_summaries", "jobs.scan_daily_alert_digests", "jobs.scan_daily_crux_digests"})
        self.assertTrue(all(item["options"]["queue"] == "default" for item in app.conf.beat_schedule.values()))
        self.assertEqual(app.amqp.router.route({}, "checks.probe")["queue"].name, "default")
        for task in ("accounts.purge_retained_trial_identities", "tenancy.purge_public_contact", "tenancy.purge_expired_customer_copies",
                     "jobs.scan_daily_crux_digests", "jobs.send_daily_crux_digest",
                     "jobs.scan_daily_alert_digests", "jobs.send_daily_alert_digest",
                     "jobs.scan_weekly_summaries", "jobs.send_weekly_summary"):
            self.assertEqual(app.amqp.router.route({}, task)["queue"].name, "default")
        self.assertEqual(app.amqp.router.route({}, "jobs.execute_crawl")["queue"].name, "crawl")
        self.assertEqual(app.amqp.router.route({}, "jobs.verify_authority_link_source")["queue"].name, "crawl")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_competitor_root")["queue"].name, "crawl")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_competitor_schema_root")["queue"].name, "crawl")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_competitor_links_root")["queue"].name, "crawl")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_competitor_page")["queue"].name, "crawl")
        self.assertEqual(app.amqp.router.route({}, "jobs.synthesize_competitor_pair")["queue"].name, "ai")
        self.assertEqual(app.amqp.router.route({}, "jobs.execute_render")["queue"].name, "crawl")
        self.assertEqual(app.amqp.router.route({}, "jobs.verify_project_origin")["queue"].name, "audit")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_passive_headers")["queue"].name, "audit")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_passive_tls")["queue"].name, "audit")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_passive_resources")["queue"].name, "audit")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_passive_redirects")["queue"].name, "audit")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_passive_http_redirects")["queue"].name, "audit")
        self.assertEqual(app.amqp.router.route({}, "jobs.collect_passive_redirect_chain")["queue"].name, "audit")
        self.assertEqual(app.amqp.router.route({}, "tenancy.capture_customer_snapshot")["queue"].name, "audit")
        with self.assertRaises(QueueNotFound):
            app.amqp.router.route({"queue": "typo"}, "checks.probe")

        # Real Celery envelopes/serialization, without connecting to Redis or
        # registering a placeholder business task. This does not run a worker.
        with Connection("memory://") as connection:
            for name in app.amqp.queues:
                with self.subTest(queue=name), connection.SimpleQueue(
                    app.amqp.queues[name], accept=app.conf.accept_content,
                ) as queue:
                    app.send_task("checks.probe", args=[{"job_id": 1}], queue=name,
                                  connection=connection, ignore_result=True)
                    message = queue.get(block=False)
                    self.assertEqual(message.content_type, "application/json")
                    self.assertEqual(message.headers["task"], "checks.probe")
                    self.assertEqual(message.payload[0], [{"job_id": 1}])
                    message.ack()
                    with self.assertRaises(Empty):
                        queue.get(block=False)
                    Producer(connection).publish(
                        {"untrusted": True}, serializer="pickle",
                        exchange=app.amqp.queues[name].exchange, routing_key=name,
                    )
                    with self.assertRaises(ContentDisallowed):
                        queue.get(block=False).payload


@override_settings(DEBUG=False, WHITENOISE_AUTOREFRESH=False, WHITENOISE_USE_FINDERS=False)
class StaticServingTests(SimpleTestCase):
    def test_collected_admin_assets_work_without_debug_or_runserver(self):
        url = staticfiles_storage.url("admin/css/base.css")
        self.assertNotEqual(url, "/static/admin/css/base.css")
        response = self.client.get(url, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "text/css; charset=\"utf-8\"")
        self.assertIn("immutable", response.headers["Cache-Control"])
        self.assertTrue(b"".join(response.streaming_content))
        self.assertEqual(self.client.get("/static/not-present.css", secure=True).status_code, 404)
