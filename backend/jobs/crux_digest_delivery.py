"""Independent default-off CrUX SMTP kernel; durable claims and no uncertain replay."""
from datetime import timedelta, timezone as utc
from hashlib import sha256

from django.conf import settings

from accounts.localization import product_email_language
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .crux_delivery_source import _binding
from .crux_digest_source import current_daily_crux_digest_source
from .crux_history_source import _encoded
from .models import ProjectCruxAlertDelivery, ProjectCruxEpisodeClaim
from .summary_delivery import _locked_scope


def _day_start():
    return timezone.now().astimezone(utc.utc).date() - timedelta(days=1)


def _source_identity(source, episodes):
    metadata = {"source": {key: value for key, value in source.items() if key not in {"source_fingerprint", "assessed_at"}},
                "claimed_episodes": episodes}
    return metadata, sha256(_encoded({"source_fingerprint": source["source_fingerprint"], "metadata": metadata})).hexdigest()


def _current(delivery, project, recipient):
    delivery.clean()
    binding = _binding(project, recipient)
    if (binding is None or (binding[0], binding[1], binding[3]) != (
        delivery.preference_id, delivery.preference_revision, delivery.primary_address_id) or delivery.day_start != _day_start()):
        raise PermissionDenied
    source = current_daily_crux_digest_source(project=project, recipient=recipient)
    episodes = delivery.source_metadata["claimed_episodes"]
    claims = list(ProjectCruxEpisodeClaim.objects.filter(delivery=delivery).order_by("episode_key")
                  .values_list("project_id", "recipient_id", "episode_key")[:301])
    if (source["state"] != "eligible_current_material_digest_not_sent" or not set(episodes) <= set(source["episodes"])
        or _source_identity(source, episodes) != (delivery.source_metadata, delivery.source_fingerprint)
        or claims != [(project.pk, recipient.pk, key) for key in sorted(episodes)]
        or _binding(project, recipient) != binding or delivery.day_start != _day_start()):
        raise PermissionDenied
    return binding


def reserve_daily_crux_digest(*, project, recipient):
    if not settings.CRUX_ALERT_DELIVERY_ENABLED:
        return None
    with transaction.atomic():
        current, recipient = _locked_scope(project.pk, recipient.pk)
        if current.organization_id != project.organization_id:
            raise PermissionDenied
        project = current
        binding = _binding(project, recipient)
        if binding is None:
            return None
        day = _day_start()
        existing = ProjectCruxAlertDelivery.objects.filter(project=project, recipient=recipient, day_start=day).first()
        if existing:
            return existing.pk
        source = current_daily_crux_digest_source(project=project, recipient=recipient)
        if source["state"] != "eligible_current_material_digest_not_sent":
            return None
        consumed = set(ProjectCruxEpisodeClaim.objects.filter(project=project, recipient=recipient,
            episode_key__in=source["episodes"]).values_list("episode_key", flat=True))
        episodes = [key for key in source["episodes"] if key not in consumed]
        if not episodes:
            return None
        metadata, fingerprint = _source_identity(source, episodes)
        delivery = ProjectCruxAlertDelivery.objects.create(project=project, recipient=recipient,
            preference_id=binding[0], preference_revision=binding[1], primary_address_id=binding[3],
            day_start=day, source_metadata=metadata, source_fingerprint=fingerprint)
        ProjectCruxEpisodeClaim.objects.bulk_create([ProjectCruxEpisodeClaim(
            project=project, recipient=recipient, delivery=delivery, episode_key=key) for key in episodes])
        _current(delivery, project, recipient)
        return delivery.pk


def _message(delivery, project, recipient):
    count = len(delivery.source_metadata["claimed_episodes"])
    link = f"{settings.FRONTEND_ORIGIN}/app/reports/{project.organization_id}/{project.pk}"
    if product_email_language(recipient) == "tr":
        return ("[OrganicSEOOps] İsteğe bağlı belirgin CrUX adayları (Türkçe taslak)",
                f"Bu isteğe bağlı özet, bağımsız CrUX tercihinizden sonra tamamlanan {delivery.day_start:%Y-%m-%d} UTC gününde "
                f"toplanan en yeni gözlenmiş CrUX kaynaklarından {count} metrik-dönem adayı seçer. Ürün kuralı daha kötü bir "
                "saha derecesi, p75 değerinde en az %20 artış ve 500ms LCP, 50ms INP veya 0.05 CLS mutlak artışı gerektirir. "
                "Özgün 28 günlük dönemler örtüşür; uygun gün ve örnek sayıları ile istatistiksel anlamlılık bilinmiyor. "
                "Bunlar doğrulanmış SEO gerilemeleri, nedensel değişiklikler, güncel olaylar veya tam sağlayıcı kapsamı değildir. "
                "Toplama günü, kaynak döneminin olay zamanı değildir. "
                f"Özgün dönemleri, güncelliği ve sınırlamaları özel uygulamada inceleyin: {link}. Kanıtları incelemek veya "
                "isteğe bağlı CrUX tercihinizi kapatmak için güncel proje erişiminizle giriş yapın. Bu ileti için yeni analiz çalıştırılmadı.")
    return ("[OrganicSEOOps] Optional material CrUX candidates",
            f"This optional digest selects {count} metric-period candidates from newest observed CrUX sources "
            f"collected in the completed UTC day {delivery.day_start:%Y-%m-%d}, after your independent CrUX intent. "
            "The product heuristic requires a worse field grade, at least 20% p75 increase and an absolute increase "
            "of 500ms LCP, 50ms INP or 0.05 CLS. Original 28-day windows overlap; eligible-day and sample counts "
            "and statistical significance are unknown. These are not confirmed SEO regressions, causal changes, "
            "current incidents or complete provider coverage. Collection day is not source-period occurrence time. "
            f"Review original periods, freshness and limitations in the private app: {link}. Sign in with current "
            "project access to inspect evidence or turn off your optional CrUX intent. No new analysis was run for this message.")


def _skip(delivery):
    delivery.state = delivery.State.SKIPPED
    delivery.error_category = "current_source_or_recipient_changed"


def deliver_daily_crux_digest(delivery_id):
    if not settings.CRUX_ALERT_DELIVERY_ENABLED:
        return "disabled"
    if not transaction.get_autocommit():
        raise RuntimeError("CrUX SMTP delivery requires its own committed transaction.")
    identity = ProjectCruxAlertDelivery.objects.filter(pk=delivery_id).values_list("project_id", "recipient_id").first()
    if identity is None:
        return "missing"
    with transaction.atomic(durable=True):
        project, recipient = _locked_scope(*identity)
        delivery = ProjectCruxAlertDelivery.objects.select_for_update().get(pk=delivery_id, project=project, recipient=recipient)
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
    # External uncertainty cannot roll the first durable sending commit back to queued.
    with transaction.atomic(durable=True):
        project, recipient = _locked_scope(*identity)
        delivery = ProjectCruxAlertDelivery.objects.select_for_update().get(pk=delivery_id, project=project, recipient=recipient)
        if delivery.state != delivery.State.SENDING:
            return delivery.state
        try:
            subject, body = _message(delivery, project, recipient)
            binding = _current(delivery, project, recipient)
            if (_binding(project, recipient) != binding or delivery.day_start != _day_start()
                or not settings.CRUX_ALERT_DELIVERY_ENABLED):
                raise PermissionDenied
        except (PermissionDenied, ValidationError):
            _skip(delivery)
        else:
            try:
                sent = send_mail(subject, body, None, [binding[4]], fail_silently=False)
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


def recover_daily_crux_digests(*, limit=20):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Choose a bounded CrUX recovery batch.")
    cutoff = timezone.now() - timedelta(minutes=2)
    stale = list(ProjectCruxAlertDelivery.objects.filter(state="sending", attempted_at__lte=cutoff).order_by("pk")
                 .values_list("pk", "project_id", "recipient_id")[:limit])
    for delivery_id, project_id, recipient_id in stale:
        with transaction.atomic():
            _locked_scope(project_id, recipient_id)
            delivery = ProjectCruxAlertDelivery.objects.select_for_update().filter(pk=delivery_id, state="sending", attempted_at__lte=cutoff).first()
            if delivery:
                delivery.state = delivery.State.UNKNOWN
                delivery.error_category = "worker_outcome_unknown"
                delivery.save(update_fields=["state", "error_category"])
    if not settings.CRUX_ALERT_DELIVERY_ENABLED:
        return []
    return list(ProjectCruxAlertDelivery.objects.filter(state="queued").order_by("pk").values_list("pk", flat=True)[:limit])
