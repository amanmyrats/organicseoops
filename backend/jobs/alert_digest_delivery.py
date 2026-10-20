"""Default-off daily SMTP kernel with durable related claims, never uncertain replay."""
from datetime import timedelta

from django.conf import settings

from accounts.localization import product_email_language
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .alert_digest_source import _binding, _day, _fingerprint, current_daily_digest_source
from .models import ProjectAlertDelivery, ProjectAlertEpisodeClaim
from .summary_delivery import _locked_scope


def _source_identity(source, episodes):
    metadata = {"source": {key: value for key, value in source.items() if key != "source_fingerprint"},
                "claimed_episodes": episodes}
    return metadata, _fingerprint({"source_fingerprint": source["source_fingerprint"], "metadata": metadata})


def _current(delivery, project, recipient):
    delivery.clean()
    if delivery.day_start != _day()[0].date():
        raise PermissionDenied
    binding = _binding(project, recipient)
    if binding is None or (binding[0], binding[1], binding[4]) != (
            delivery.preference_id, delivery.preference_revision, delivery.primary_address_id):
        raise PermissionDenied
    source = current_daily_digest_source(project=project, recipient=recipient)
    episodes = delivery.source_metadata["claimed_episodes"]
    claims = list(ProjectAlertEpisodeClaim.objects.filter(delivery=delivery).order_by("episode_key").values_list(
        "project_id", "recipient_id", "episode_key")[:41])
    if (source is None or not set(episodes) <= set(source["episodes"])
        or _source_identity(source, episodes) != (delivery.source_metadata, delivery.source_fingerprint)
        or claims != [(project.pk, recipient.pk, key) for key in sorted(episodes)]
        or _binding(project, recipient) != binding or delivery.day_start != _day()[0].date()):
        raise PermissionDenied
    return binding


def reserve_daily_alert_digest(*, project, recipient):
    if not settings.ALERT_DIGEST_DELIVERY_ENABLED:
        return None
    with transaction.atomic():
        project, recipient = _locked_scope(project.pk, recipient.pk)
        binding = _binding(project, recipient)
        if binding is None:
            return None
        day = _day()[0].date()
        existing = ProjectAlertDelivery.objects.filter(project=project, recipient=recipient, day_start=day).first()
        if existing:
            return existing.pk  # No same-day rebinding or replacement, even after a skip.
        source = current_daily_digest_source(project=project, recipient=recipient)
        if source is None:
            return None
        consumed = set(ProjectAlertEpisodeClaim.objects.filter(project=project, recipient=recipient,
            episode_key__in=source["episodes"]).values_list("episode_key", flat=True))
        episodes = [key for key in source["episodes"] if key not in consumed]
        if not episodes:
            return None
        metadata, fingerprint = _source_identity(source, episodes)
        delivery = ProjectAlertDelivery.objects.create(project=project, recipient=recipient,
            preference_id=binding[0], preference_revision=binding[1], primary_address_id=binding[4],
            day_start=day, source_metadata=metadata, source_fingerprint=fingerprint)
        ProjectAlertEpisodeClaim.objects.bulk_create([ProjectAlertEpisodeClaim(
            project=project, recipient=recipient, delivery=delivery, episode_key=key) for key in episodes])
        _current(delivery, project, recipient)  # Loss after either insert rolls back the complete reservation.
        return delivery.pk


def _message(delivery, project, recipient):
    count = len(delivery.source_metadata["claimed_episodes"])
    link = f"{settings.FRONTEND_ORIGIN}/app/reports/{project.organization_id}/{project.pk}"
    if product_email_language(recipient) == "tr":
        return ("[OrganicSEOOps] İsteğe bağlı günlük işlem özeti (Türkçe taslak)",
                f"Bu özet, tamamlanan {delivery.day_start:%Y-%m-%d} UTC gününden {count} işlem kaynak kaydı seçer. "
                "Bunlar seçtiğiniz kaynak aileleri ve sınırlı kapsam içindeki saklanan kök tarama başarısızlık durum "
                "güncellemeleri veya Search Console yeniden bağlantı gereksinimi denetim kayıtlarıdır. Diğer kayıtlar bu "
                "kapsamın dışında olabilir. Kayıt tarihleri değişmez olay zamanları değildir; bu seçimler güncel olayları, "
                "önem derecesini, eskime süresini, doğrulanmış SEO gerilemelerini veya tam sağlayıcı kapsamını kanıtlamaz. "
                f"Özgün tarihleri ve kapsamı özel uygulamada inceleyin: {link}. Kaynak kayıtlarını incelemek ve isteğe bağlı "
                "günlük tercihinizi kapatmak için güncel proje erişiminizle giriş yapın. Bu ileti için yeni analiz çalıştırılmadı.")
    return ("[OrganicSEOOps] Optional daily operational digest",
            f"This digest selects {count} operational source records from the completed UTC day {delivery.day_start:%Y-%m-%d}. "
            "They are retained root crawl failure status updates or Search Console reconnect-required audit records, "
            "within your selected source families and bounded coverage. Other records may be outside that coverage. "
            "Record dates are not immutable incident times; these selections do not establish current incidents, "
            "severity, stale age, confirmed SEO regressions or complete provider coverage. "
            f"Review original dates and coverage in the private app: {link}. Sign in with current project access "
            "to inspect source records and turn off your optional daily preference. No new analysis was run for this message.")


def _skip(delivery):
    delivery.state = delivery.State.SKIPPED
    delivery.error_category = "current_source_or_recipient_changed"


def deliver_daily_alert_digest(delivery_id):
    if not settings.ALERT_DIGEST_DELIVERY_ENABLED:
        return "disabled"
    if not transaction.get_autocommit():
        raise RuntimeError("Daily SMTP delivery requires its own committed transaction.")
    identity = ProjectAlertDelivery.objects.filter(pk=delivery_id).values_list("project_id", "recipient_id").first()
    if identity is None:
        return "missing"
    with transaction.atomic(durable=True):
        project, recipient = _locked_scope(*identity)
        delivery = ProjectAlertDelivery.objects.select_for_update().get(pk=delivery_id, project=project, recipient=recipient)
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
    # A crash after this commit can never restore queued or release episode claims.
    with transaction.atomic(durable=True):
        project, recipient = _locked_scope(*identity)
        delivery = ProjectAlertDelivery.objects.select_for_update().get(pk=delivery_id, project=project, recipient=recipient)
        if delivery.state != delivery.State.SENDING:
            return delivery.state
        try:
            subject, body = _message(delivery, project, recipient)
            binding = _current(delivery, project, recipient)
            if (_binding(project, recipient) != binding or delivery.day_start != _day()[0].date()
                or not settings.ALERT_DIGEST_DELIVERY_ENABLED):
                raise PermissionDenied
        except (PermissionDenied, ValidationError):
            _skip(delivery)
        else:
            try:
                sent = send_mail(subject, body, None, [binding[5]], fail_silently=False)
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


def recover_daily_alert_digests(*, limit=20):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Choose a bounded daily digest recovery batch.")
    cutoff = timezone.now() - timedelta(minutes=2)
    stale = list(ProjectAlertDelivery.objects.filter(state="sending", attempted_at__lte=cutoff).order_by("pk")
                 .values_list("pk", "project_id", "recipient_id")[:limit])
    for delivery_id, project_id, recipient_id in stale:
        with transaction.atomic():
            _locked_scope(project_id, recipient_id)
            delivery = ProjectAlertDelivery.objects.select_for_update().filter(pk=delivery_id,
                state="sending", attempted_at__lte=cutoff).first()
            if delivery:
                delivery.state = delivery.State.UNKNOWN
                delivery.error_category = "worker_outcome_unknown"
                delivery.save(update_fields=["state", "error_category"])
    if not settings.ALERT_DIGEST_DELIVERY_ENABLED:
        return []
    return list(ProjectAlertDelivery.objects.filter(state="queued").order_by("pk").values_list("pk", flat=True)[:limit])
