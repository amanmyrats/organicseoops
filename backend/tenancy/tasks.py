from celery import shared_task
from kombu.exceptions import OperationalError
import logging


@shared_task(name="tenancy.capture_customer_snapshot", ignore_result=True, soft_time_limit=600, time_limit=630,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def capture_customer_snapshot_task(snapshot_id, stage=None):
    if stage is not None:
        from .customer_source_parts import capture_source_stage
        return capture_source_stage(snapshot_id, stage)
    from .customer_snapshot import capture_reserved_customer_snapshot
    return capture_reserved_customer_snapshot(snapshot_id)


@shared_task(name="tenancy.purge_expired_customer_copies", ignore_result=True, soft_time_limit=35, time_limit=45,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def purge_expired_customer_copies_task():
    from .customer_copy_cleanup import purge_expired_customer_copies
    return purge_expired_customer_copies()


@shared_task(name="tenancy.reconcile_paddle_receipt", ignore_result=True, soft_time_limit=40, time_limit=50,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def reconcile_paddle_receipt_task(receipt_id):
    from .paddle_jobs import execute_paddle_receipt
    return execute_paddle_receipt(receipt_id)


@shared_task(name="tenancy.send_organization_notice", ignore_result=True, soft_time_limit=20, time_limit=30,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def send_organization_notice_task(notice_id):
    from .notices import deliver_organization_notice
    return deliver_organization_notice(notice_id)


@shared_task(name="tenancy.schedule_organization_notices", ignore_result=True, soft_time_limit=30, time_limit=40,
             acks_late=True, max_retries=0)
def schedule_organization_notices_task():
    from .notices import (recover_organization_notices, reserve_due_trial_notices,
                          reserve_due_payment_notices, reserve_exhausted_paid_notices)
    from .models import NoticeKind
    reserve_due_trial_notices()
    reserve_due_trial_notices(kind=NoticeKind.TRIAL_UNITS_EXHAUSTED)
    reserve_due_payment_notices()
    reserve_exhausted_paid_notices()
    for notice_id in recover_organization_notices():
        try:
            send_organization_notice_task.apply_async(
                args=[notice_id], queue="default", task_id=f"organization-notice-{notice_id}", retry=False,
            )
        except (OperationalError, OSError, TimeoutError):
            # The next bounded scan requeues only DB-queued records, never an uncertain SMTP send.
            continue


@shared_task(name="tenancy.poll_ses_feedback", ignore_result=True, soft_time_limit=40, time_limit=50,
             acks_late=True, max_retries=0)
def poll_ses_feedback_task():
    from .email_feedback import record_ses_feedback
    from .ses_feedback_transport import poll_ses_feedback
    return poll_ses_feedback(handle=record_ses_feedback)


@shared_task(name="tenancy.purge_public_analytics", ignore_result=True, soft_time_limit=35, time_limit=45,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def purge_public_analytics_task():
    from .public_analytics import drain_expired_public_analytics_epochs
    status = drain_expired_public_analytics_epochs()
    if status["expired_pending"]:
        try:
            purge_public_analytics_task.apply_async(args=[], queue="default", countdown=1, retry=False)
        except (OperationalError, OSError, TimeoutError):
            logging.getLogger(__name__).error("public_analytics.cleanup_dispatch_failed")
    return status


@shared_task(name="tenancy.purge_public_contact", ignore_result=True, soft_time_limit=35, time_limit=45,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def purge_public_contact_task():
    from django.utils import timezone
    from .models import PublicContactRequest
    from .public_contact_store import purge_expired_contact_requests
    removed = purge_expired_contact_requests()
    pending = PublicContactRequest.objects.filter(expires_at__lte=timezone.now()).exists()
    if pending:
        try:
            purge_public_contact_task.apply_async(args=[], queue="default", countdown=1, retry=False)
        except (OperationalError, OSError, TimeoutError):
            logging.getLogger(__name__).error("public_contact.cleanup_dispatch_failed")
    return {"removed": removed, "expired_pending": pending}
