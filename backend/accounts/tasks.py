from celery import shared_task
from django.utils import timezone

from .models import RetainedTrialIdentity


@shared_task(name="accounts.purge_retained_trial_identities", ignore_result=True,
             soft_time_limit=30, time_limit=40, acks_late=True, max_retries=0)
def purge_retained_trial_identities_task():
    # Recheck the deadline in DELETE: cleanup may have extended it after this selection.
    now = timezone.now()
    ids = list(RetainedTrialIdentity.objects.filter(expires_at__lte=now).order_by("expires_at", "pk")
               .values_list("pk", flat=True)[:1000])
    return RetainedTrialIdentity.objects.filter(pk__in=ids, expires_at__lte=now).delete()[0]
