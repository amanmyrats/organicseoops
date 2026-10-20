"""Optional weekly SMTP kernel. No task registration or automatic unknown replay."""
from datetime import timedelta, timezone as utc
from hashlib import sha256
import json

from django.conf import settings

from accounts.localization import product_email_language
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from .models import ProjectSummaryDelivery
from .summary_delivery_source import _binding, current_weekly_delivery_source
from .weekly_summary import _date


def _source_identity(source):
    original = {key: value for key, value in source.items() if key != "assessed_at"}
    digest = sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {key: value for key, value in original.items() if key != "rows"}, digest


def _week_start():
    now = timezone.now().astimezone(utc.utc)
    return now.date() - timedelta(days=now.weekday() + 7)


def _locked_scope(project_id, recipient_id):
    organization_id = Project.objects.values_list("organization_id", flat=True).get(pk=project_id)
    Organization.objects.select_for_update().get(pk=organization_id)
    project = Project.objects.select_for_update().get(pk=project_id, organization_id=organization_id)
    recipient = get_user_model().objects.select_for_update().get(pk=recipient_id)
    return project, recipient


def _current(delivery, project, recipient):
    delivery.clean()
    if delivery.week_start != _week_start():
        raise PermissionDenied
    binding = _binding(project, recipient)
    if binding is None or binding[:3] != (delivery.preference_id, delivery.preference_revision, delivery.primary_address_id):
        raise PermissionDenied
    result = current_weekly_delivery_source(project=project, recipient=recipient)
    if (result["state"] != "eligible_current_source_not_sent" or result["preference_revision"] != delivery.preference_revision
        or result["source"]["report_id"] != delivery.report_id
        or _source_identity(result["source"]) != (delivery.source_metadata, delivery.source_fingerprint)
        or _binding(project, recipient) != binding or delivery.week_start != _week_start()):
        raise PermissionDenied
    return binding


def reserve_weekly_summary(*, project, recipient):
    if not settings.WEEKLY_SUMMARY_DELIVERY_ENABLED:
        return None
    with transaction.atomic():
        project, recipient = _locked_scope(project.pk, recipient.pk)
        binding = _binding(project, recipient)
        if binding is None:
            return None
        result = current_weekly_delivery_source(project=project, recipient=recipient)
        if result["state"] != "eligible_current_source_not_sent":
            return None
        source = result["source"]
        metadata, fingerprint = _source_identity(source)
        if _binding(project, recipient) != binding:
            raise PermissionDenied
        delivery, created = ProjectSummaryDelivery.objects.get_or_create(
            project=project, recipient=recipient, week_start=_date(source["week_start"]).date(),
            defaults={"preference_id": binding[0], "preference_revision": binding[1], "primary_address_id": binding[2],
                      "report_id": source["report_id"], "source_metadata": metadata, "source_fingerprint": fingerprint})
        if created:
            _current(delivery, project, recipient)  # Loss after insert rolls the reservation back.
        return delivery.pk


def _message(delivery, project, recipient):
    counts = delivery.source_metadata["source_counts"]
    link = f"{settings.FRONTEND_ORIGIN}/app/reports/{project.organization_id}/{project.pk}"
    if product_email_language(recipient) == "tr":
        return ("[OrganicSEOOps] İsteğe bağlı haftalık rapor özeti (Türkçe taslak)",
                f"Saklanan bir proje raporu, {delivery.week_start:%Y-%m-%d} tarihinde başlayan tamamlanmış UTC haftasında oluşturuldu. "
                f"Rapor {counts['findings']} seçilmiş bulgu, {counts['actions']} insan eylem kaydı ve "
                f"{counts['outcomes']} gözlenen sayfa sonucu kaydı içerir. Bunlar seçilmiş kaynak kayıtlarıdır; tam sağlayıcı "
                "kapsamı, haftalık SEO değişiklikleri, doğrulanmış gerilemeler veya nedensel iyileşme kanıtı değildir. "
                f"Özgün tarihler ve kapsam özel uygulamadadır: {link}. Raporu incelemek ve isteğe bağlı haftalık "
                "tercihinizi kapatmak için güncel proje erişiminizle giriş yapın. Bu ileti için yeni analiz çalıştırılmadı.")
    return ("[OrganicSEOOps] Optional weekly report summary",
            f"A retained project report was created during the completed UTC week starting {delivery.week_start:%Y-%m-%d}. "
            f"It includes {counts['findings']} selected findings, {counts['actions']} human action records and "
            f"{counts['outcomes']} observed page outcome records. These are selected source records, not complete provider "
            "coverage, weekly SEO changes, confirmed regressions or causal uplift. Original dates and coverage are in the "
            f"private app: {link}. Sign in with your current project access to review the report and turn off your optional "
            "weekly preference. No new analysis was run for this message.")


def _skip(delivery):
    delivery.state = delivery.State.SKIPPED
    delivery.error_category = "current_source_or_recipient_changed"


def deliver_weekly_summary(delivery_id):
    if not settings.WEEKLY_SUMMARY_DELIVERY_ENABLED:
        return "disabled"
    # The sending claim must survive a caller rollback. Also reject manual autocommit=False.
    if not transaction.get_autocommit():
        raise RuntimeError("Weekly SMTP delivery requires its own committed transaction.")
    identity = ProjectSummaryDelivery.objects.filter(pk=delivery_id).values_list("project_id", "recipient_id").first()
    if identity is None:
        return "missing"
    with transaction.atomic(durable=True):
        project, recipient = _locked_scope(*identity)
        delivery = ProjectSummaryDelivery.objects.select_for_update().get(pk=delivery_id, project=project, recipient=recipient)
        if delivery.state != delivery.State.QUEUED:
            return delivery.state
        delivery.attempted_at = timezone.now()
        try:
            _current(delivery, project, recipient)
        except (PermissionDenied, ValidationError):
            _skip(delivery)
        else:
            delivery.state = delivery.State.SENDING
        delivery.save(update_fields=["attempted_at", "state", "error_category"])
    if delivery.state != delivery.State.SENDING:
        return delivery.state
    # A process failure from here leaves a committed sending record, never queued for replay.
    with transaction.atomic(durable=True):
        project, recipient = _locked_scope(*identity)
        delivery = ProjectSummaryDelivery.objects.select_for_update().get(pk=delivery_id, project=project, recipient=recipient)
        if delivery.state != delivery.State.SENDING:
            return delivery.state
        try:
            subject, body = _message(delivery, project, recipient)
            binding = _current(delivery, project, recipient)
            if (_binding(project, recipient) != binding or delivery.week_start != _week_start()
                or not settings.WEEKLY_SUMMARY_DELIVERY_ENABLED):
                raise PermissionDenied
        except (PermissionDenied, ValidationError):
            _skip(delivery)
        else:
            try:
                sent = send_mail(subject, body, None, [binding[3]], fail_silently=False)
            except Exception:
                sent = 0
            if sent == 1:
                delivery.state = delivery.State.SENT
                delivery.sent_at = timezone.now()
            else:
                delivery.state = delivery.State.UNKNOWN
                delivery.error_category = "delivery_uncertain"
        delivery.save(update_fields=["state", "sent_at", "error_category"])
        return delivery.state


def recover_weekly_summaries(*, limit=20):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Choose a bounded summary recovery batch.")
    cutoff = timezone.now() - timedelta(minutes=2)
    stale = list(ProjectSummaryDelivery.objects.filter(state="sending", attempted_at__lte=cutoff).order_by("pk")
                 .values_list("pk", "project_id", "recipient_id")[:limit])
    for delivery_id, project_id, recipient_id in stale:
        with transaction.atomic():
            _locked_scope(project_id, recipient_id)
            delivery = ProjectSummaryDelivery.objects.select_for_update().filter(pk=delivery_id,
                state="sending", attempted_at__lte=cutoff).first()
            if delivery:
                delivery.state = delivery.State.UNKNOWN
                delivery.error_category = "worker_outcome_unknown"
                delivery.save(update_fields=["state", "error_category"])
    if not settings.WEEKLY_SUMMARY_DELIVERY_ENABLED:
        return []
    return list(ProjectSummaryDelivery.objects.filter(state="queued").order_by("pk").values_list("pk", flat=True)[:limit])
