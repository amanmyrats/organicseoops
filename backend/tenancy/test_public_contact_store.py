from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from . import test_public_contact as fixtures
from .customer_inventory import CUSTOMER, GLOBAL, require_complete_ownership_map
from .models import PublicContactRequest
from .public_contact_store import create_contact_request, own_contact_receipt, purge_expired_contact_requests
from .tasks import purge_public_contact_task


@override_settings(PUBLIC_CONTACT_RETENTION_DAYS=2)
class PublicContactStoreTests(TestCase):
    command = fixtures.PublicContactCommandTests.command
    browser_key = "a" * 43

    def create(self, **changes):
        return create_contact_request(browser_key=self.browser_key, command=self.command(**changes))

    def test_browser_scoped_idempotency_minimized_receipts_global_ownership_and_no_delivery(self):
        with patch("django.core.mail.send_mail", side_effect=AssertionError("mail")), \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            result = self.create()
            self.assertEqual(self.create(), result)
            self.assertEqual(own_contact_receipt(browser_key=self.browser_key, request_key=result["request_key"]), result)
            self.assertIsNone(own_contact_receipt(browser_key="b" * 43, request_key=result["request_key"]))
            other = create_contact_request(browser_key="b" * 43, command=self.command())
            self.assertEqual(other["status"], "received")
        self.assertEqual(PublicContactRequest.objects.count(), 2)
        self.assertEqual(set(result), {"request_key", "status", "created_at", "expires_at", "scope"})
        self.assertNotIn(self.command()["reply_email"], str(result))
        self.assertNotIn(self.command()["question"], str(result))
        row = PublicContactRequest.objects.first()
        self.assertNotEqual(row.browser_key_hash, self.browser_key)
        self.assertEqual(row.expires_at - row.created_at, timedelta(days=2))
        require_complete_ownership_map()
        self.assertIn("tenancy.PublicContactRequest", GLOBAL)
        self.assertNotIn("tenancy.PublicContactRequest", CUSTOMER)
        for change in ({"question": "Changed question"}, {"reply_email": "other@example.invalid"},
                       {"category": "privacy"}, {"language": "tr"}):
            with self.assertRaises(ValidationError):
                self.create(**change)
        row.question = "Changed question"
        with self.assertRaises(ValidationError):
            row.save()
        self.assertEqual(PublicContactRequest.objects.first().question, self.command()["question"])

    def test_configuration_and_capability_fail_closed_before_storage(self):
        for days in (None, 0, 366, True, "2"):
            with override_settings(PUBLIC_CONTACT_RETENTION_DAYS=days), self.assertRaises(ValidationError):
                self.create()
        for key in (None, "short", "a" * 44, [self.browser_key], "!" * 43):
            with self.assertRaises(ValidationError):
                create_contact_request(browser_key=key, command=self.command())
        self.assertFalse(PublicContactRequest.objects.exists())

    def test_expired_receipts_cannot_recreate_or_disclose_content_and_corrupt_dates_fail_closed(self):
        result = self.create()
        row = PublicContactRequest.objects.get()
        future = row.expires_at
        with patch("tenancy.public_contact_store.timezone.now", return_value=future):
            self.assertIsNone(own_contact_receipt(browser_key=self.browser_key, request_key=result["request_key"]))
            with self.assertRaises(ValidationError):
                self.create()
            retained = create_contact_request(browser_key="b" * 43, command=self.command())
            self.assertEqual(purge_expired_contact_requests(), 1)
            self.assertEqual(purge_expired_contact_requests(), 0)
            self.assertEqual(own_contact_receipt(browser_key="b" * 43, request_key=retained["request_key"]), retained)
        self.assertEqual(PublicContactRequest.objects.count(), 1)
        self.assertFalse(PublicContactRequest.objects.filter(pk=row.pk).exists())
        PublicContactRequest.objects.update(created_at=future + timedelta(hours=1))
        with self.assertRaises(ValidationError):
            own_contact_receipt(browser_key="b" * 43, request_key=result["request_key"])
        with self.assertRaises(ValidationError):
            own_contact_receipt(browser_key=self.browser_key, request_key="bad")

    def expired_rows(self, count):
        assessed = timezone.now()
        PublicContactRequest.objects.bulk_create([PublicContactRequest(browser_key_hash="f" * 64,
            **self.command(request_key=f"expired-contact-{index}"), created_at=assessed - timedelta(days=3),
            expires_at=assessed - timedelta(days=1)) for index in range(count)])

    def test_registered_cleanup_drains_bounded_expired_batches_when_intake_and_retention_are_off(self):
        self.create(); self.expired_rows(201)
        with override_settings(PUBLIC_CONTACT_ENABLED=False, PUBLIC_CONTACT_RETENTION_DAYS=None), \
                patch.object(purge_public_contact_task, "apply_async") as dispatch:
            self.assertEqual(purge_public_contact_task.run(), {"removed": 100, "expired_pending": True})
            self.assertEqual(purge_public_contact_task.run(), {"removed": 100, "expired_pending": True})
            self.assertEqual(purge_public_contact_task.run(), {"removed": 1, "expired_pending": False})
            self.assertEqual(purge_public_contact_task.run(), {"removed": 0, "expired_pending": False})
        self.assertEqual(dispatch.call_count, 2)
        dispatch.assert_called_with(args=[], queue="default", countdown=1, retry=False)
        self.assertEqual(PublicContactRequest.objects.count(), 1)
        self.assertEqual(own_contact_receipt(browser_key=self.browser_key,
            request_key=self.command()["request_key"])["status"], "received")
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["public-contact-expiry"],
            {"task": "tenancy.purge_public_contact", "schedule": 3600.0, "options": {"queue": "default"}})
        self.assertTrue(purge_public_contact_task.acks_late)
        self.assertTrue(purge_public_contact_task.reject_on_worker_lost)
        self.assertTrue(purge_public_contact_task.ignore_result)

    def test_cleanup_broker_failure_keeps_expired_backlog_visible_without_payload_logs(self):
        self.expired_rows(101)
        with patch.object(purge_public_contact_task, "apply_async", side_effect=OperationalError), \
                self.assertLogs("tenancy.tasks", level="ERROR") as logs:
            self.assertEqual(purge_public_contact_task.run(), {"removed": 100, "expired_pending": True})
        self.assertEqual(logs.output, ["ERROR:tenancy.tasks:public_contact.cleanup_dispatch_failed"])
        self.assertEqual(purge_public_contact_task.run(), {"removed": 1, "expired_pending": False})
        self.assertFalse(PublicContactRequest.objects.exists())


@override_settings(PUBLIC_CONTACT_RETENTION_DAYS=2)
class ConcurrentPublicContactTests(TransactionTestCase):
    def test_concurrent_same_capability_key_creates_once_and_changed_command_conflicts(self):
        def submit(question):
            connections.close_all()
            try:
                return create_contact_request(browser_key="a" * 43,
                    command=fixtures.PublicContactCommandTests.command(self, question=question))
            except ValidationError:
                return "conflict"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            same = list(executor.map(submit, ["Original question"] * 2))
        self.assertEqual(same[0], same[1])
        self.assertIsInstance(same[0], dict)
        self.assertEqual(PublicContactRequest.objects.count(), 1)
        PublicContactRequest.objects.all().delete()
        with ThreadPoolExecutor(max_workers=2) as executor:
            changed = list(executor.map(submit, ["Question one", "Question two"]))
        self.assertEqual(changed.count("conflict"), 1)
        self.assertEqual(PublicContactRequest.objects.count(), 1)
