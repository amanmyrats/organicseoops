"""Operator-owned DataForSEO configuration; customer evidence lives in scoped jobs."""
from datetime import timedelta
from decimal import Decimal
import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SerpConfiguration(models.Model):
    key = models.CharField(max_length=8, unique=True, default="primary", editable=False)
    encrypted_credentials = models.TextField(editable=False)
    enabled = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1, editable=False)
    locations = models.JSONField(default=dict, help_text='Reviewed Google location codes mapped to labels, e.g. {"2840": "United States"}.')
    languages = models.JSONField(default=dict, help_text='Reviewed Google language codes mapped to labels, e.g. {"en": "English"}.')
    estimated_task_cost_usd = models.DecimalField(max_digits=10, decimal_places=6)
    monthly_exposure_usd = models.DecimalField(max_digits=10, decimal_places=6)
    budget_month = models.CharField(max_length=7, blank=True, editable=False)
    reserved_exposure_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0, editable=False)
    reviewed_until = models.DateTimeField(help_text="Recheck provider capabilities/pricing within 30 days. This is an estimate, not a provider-enforced charge cap.")
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.key != "primary" or not self.encrypted_credentials.startswith("v1:"):
            raise ValidationError("Use encrypted operator credentials.")
        for values, pattern in ((self.locations, r"[1-9][0-9]{0,8}"), (self.languages, r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?")):
            if (type(values) is not dict or not 1 <= len(values) <= 100
                or any(type(key) is not str or not re.fullmatch(pattern, key) or type(label) is not str
                    or not 1 <= len(label) <= 100 or any(ord(c) < 32 for c in label) for key, label in values.items())):
                raise ValidationError("Provide bounded explicitly reviewed provider codes and labels.")
        if (not isinstance(self.estimated_task_cost_usd, Decimal) or not isinstance(self.monthly_exposure_usd, Decimal)
            or not Decimal("0") < self.estimated_task_cost_usd <= self.monthly_exposure_usd <= Decimal("1000")):
            raise ValidationError("Choose a positive per-task estimate and monthly exposure of at most USD1000.")
        if self.enabled and (self.reviewed_until is None or not timezone.is_aware(self.reviewed_until)
            or not timezone.now() < self.reviewed_until <= timezone.now() + timedelta(days=30)):
            raise ValidationError("Enabled provider configuration needs a current review expiring within 30 days.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
