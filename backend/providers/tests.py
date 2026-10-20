import json
import os
from datetime import timedelta
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType

from .admin import AIProviderAccountAdmin
from .models import AIModel, AIModelCapability, AIProvider, AIProviderAccount, normalize_compatible_endpoint
from .services import (
    UnsupportedCapability,
    configure_model,
    create_provider,
    create_provider_account,
    require_model_capabilities,
    resolve_provider_secret,
    revoke_provider_account,
    rotate_provider_account,
)


class ProviderFoundationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.operator = user_model.objects.create_superuser("provider-operator@example.com", "test-password")
        self.staff = user_model.objects.create_user(
            "provider-staff@example.com",
            "test-password",
            is_staff=True,
        )
        self.user = user_model.objects.create_user("provider-user@example.com", "test-password")

    def provider(self, *, enabled=True):
        return create_provider(
            actor=self.operator,
            key="openai",
            name="OpenAI",
            kind=AIProvider.Kind.OPENAI,
            enabled=enabled,
        )

    def test_compatible_endpoints_are_https_public_and_normalized_without_network_access(self):
        self.assertEqual(
            normalize_compatible_endpoint("https://API.Example.COM:443/v1/"),
            "https://api.example.com/v1",
        )
        self.assertEqual(normalize_compatible_endpoint("https://8.8.8.8/v1"), "https://8.8.8.8/v1")
        for value in (
            "http://api.example.com/v1",
            "https://user:secret@api.example.com/v1",
            "https://api.example.com:8443/v1",
            "https://api.example.com/v1?key=secret",
            "https://localhost/v1",
            "https://service.internal/v1",
            "https://127.0.0.1/v1",
            "https://169.254.169.254/v1",
            "https://[::1]/v1",
            "https://singlelabel/v1",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_compatible_endpoint(value)

        provider = create_provider(
            actor=self.operator,
            key="compatible",
            name="Compatible endpoint",
            kind=AIProvider.Kind.OPENAI_COMPATIBLE,
            base_url="https://API.Example.COM/v1/",
        )
        self.assertEqual(provider.base_url, "https://api.example.com/v1")
        self.assertEqual(provider.egress_policy, AIProvider.EgressPolicy.PUBLIC_HTTPS)
        with self.assertRaises(ValidationError):
            create_provider(
                actor=self.operator,
                key="native-custom",
                name="Native custom",
                kind=AIProvider.Kind.OPENAI,
                base_url="https://api.example.com/v1",
            )

    def test_provider_configuration_requires_explicit_staff_permissions(self):
        for actor in (self.user, self.staff):
            with self.subTest(actor=actor.email), self.assertRaises(PermissionDenied):
                create_provider(
                    actor=actor,
                    key="denied",
                    name="Denied",
                    kind=AIProvider.Kind.OPENAI,
                )
        provider = self.provider()
        with self.assertRaises(PermissionDenied):
            create_provider_account(
                actor=self.staff,
                provider=provider,
                label="Platform",
                secret_reference="env:OPENAI_API_KEY",
            )

        add_provider = Permission.objects.get(codename="add_aiprovider", content_type__app_label="providers")
        self.staff.user_permissions.add(add_provider)
        self.assertTrue(self.staff.has_perm("providers.add_aiprovider"))
        self.staff.user_permissions.remove(add_provider)
        with self.assertRaises(PermissionDenied):
            create_provider(
                actor=self.staff,
                key="stale-permission",
                name="Stale permission",
                kind=AIProvider.Kind.OPENAI,
            )

        get_user_model().objects.filter(pk=self.operator.pk).update(is_superuser=False)
        with self.assertRaises(PermissionDenied):
            create_provider(
                actor=self.operator,
                key="stale-superuser",
                name="Stale superuser",
                kind=AIProvider.Kind.OPENAI,
            )

    def test_platform_secret_references_rotate_revoke_and_never_enter_audit_or_admin(self):
        provider = self.provider()
        with self.assertRaises(ValidationError):
            create_provider_account(
                actor=self.operator,
                provider=provider,
                label="Plaintext",
                secret_reference="sk-plaintext-secret",
            )
        with self.assertRaises(ValidationError):
            create_provider_account(
                actor=self.operator,
                provider=provider,
                label="Unknown",
                secret_reference="env:UNAPPROVED_PROVIDER_KEY",
            )

        account = create_provider_account(
            actor=self.operator,
            provider=provider,
            label="Platform",
            secret_reference="env:OPENAI_API_KEY",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "first-secret"}, clear=False):
            self.assertEqual(resolve_provider_secret(account), "first-secret")
        account = rotate_provider_account(
            actor=self.operator,
            account=account,
            secret_reference="env:OPENAI_COMPATIBLE_API_KEY",
        )
        account.refresh_from_db()
        self.assertEqual(account.secret_reference, "env:OPENAI_COMPATIBLE_API_KEY")
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": "second-secret"}, clear=False):
            self.assertEqual(resolve_provider_secret(account), "second-secret")

        serialized_audit = json.dumps(list(AuditEvent.objects.values("event_type", "details")))
        for forbidden in (
            "first-secret",
            "second-secret",
            "OPENAI_API_KEY",
            "OPENAI_COMPATIBLE_API_KEY",
        ):
            self.assertNotIn(forbidden, serialized_audit)
        self.assertEqual(
            set(AuditEvent.objects.values_list("event_type", flat=True)),
            {AuditEventType.PROVIDER_ACCOUNT_CREATED, AuditEventType.PROVIDER_ACCOUNT_ROTATED},
        )
        model_admin = AIProviderAccountAdmin(AIProviderAccount, admin.site)
        self.assertNotIn("secret_reference", model_admin.get_fields(request=None, obj=account))
        self.assertEqual(model_admin.credential_status(account), "configured")

        account, changed = revoke_provider_account(actor=self.operator, account=account)
        self.assertTrue(changed)
        account, changed = revoke_provider_account(actor=self.operator, account=account)
        self.assertFalse(changed)
        with self.assertRaises(PermissionDenied):
            resolve_provider_secret(account)
        with self.assertRaises(ValidationError):
            rotate_provider_account(
                actor=self.operator,
                account=account,
                secret_reference="env:OPENAI_API_KEY",
            )

    def test_model_catalog_requires_dated_evidence_and_gates_capabilities(self):
        provider = self.provider()
        observed_at = timezone.now()
        model = configure_model(
            actor=self.operator,
            provider=provider,
            identifier="model-1",
            name="Model 1",
            capabilities=[AIModelCapability.STRUCTURED_OUTPUT, AIModelCapability.TEXT_GENERATION],
            context_window=128_000,
            max_output_tokens=16_384,
            capability_source="https://platform.openai.com/docs/models/model-1",
            capabilities_verified_at=observed_at,
            enabled=True,
        )
        self.assertEqual(
            model.capabilities,
            [AIModelCapability.STRUCTURED_OUTPUT, AIModelCapability.TEXT_GENERATION],
        )
        self.assertEqual(
            require_model_capabilities(model, {AIModelCapability.STRUCTURED_OUTPUT}),
            model,
        )
        with self.assertRaises(UnsupportedCapability):
            require_model_capabilities(model, {AIModelCapability.WEB_SEARCH})

        for index, capabilities in enumerate((
            [AIModelCapability.TEXT_GENERATION, AIModelCapability.TEXT_GENERATION],
            ["unknown"],
            "text_generation",
        )):
            with self.subTest(capabilities=capabilities), self.assertRaises(ValidationError):
                configure_model(
                    actor=self.operator,
                    provider=provider,
                    identifier=f"invalid-capabilities-{index}",
                    name="Invalid",
                    capabilities=capabilities,
                )
        with self.assertRaises(ValidationError):
            configure_model(
                actor=self.operator,
                provider=provider,
                identifier="missing-evidence",
                name="Missing evidence",
                capabilities=[AIModelCapability.TEXT_GENERATION],
                enabled=True,
            )
        for index, source in enumerate((
            "http://docs.example.com/model",
            "https://user:secret@docs.example.com/model",
            "https://docs.example.com/model?api_key=secret",
            "https://docs.example.com/model#private",
            "https://127.0.0.1/model",
        )):
            with self.subTest(source=source), self.assertRaises(ValidationError):
                configure_model(
                    actor=self.operator,
                    provider=provider,
                    identifier=f"invalid-evidence-{index}",
                    name="Invalid evidence",
                    capabilities=[AIModelCapability.TEXT_GENERATION],
                    capability_source=source,
                )
        with self.assertRaises(ValidationError):
            configure_model(
                actor=self.operator,
                provider=provider,
                identifier="future-evidence",
                name="Future evidence",
                capabilities=[AIModelCapability.TEXT_GENERATION],
                capability_source="https://docs.example.com/model",
                capabilities_verified_at=timezone.now() + timedelta(minutes=1),
            )
        with self.assertRaises(ValidationError):
            AIModel.objects.create(
                provider=provider,
                identifier="invalid-limit",
                name="Invalid limit",
                capabilities=[AIModelCapability.TEXT_GENERATION],
                context_window=100,
                max_output_tokens=101,
            )

        provider.enabled = False
        provider.save(update_fields=["enabled", "updated_at"])
        with self.assertRaises(UnsupportedCapability):
            require_model_capabilities(model, {AIModelCapability.TEXT_GENERATION})

    def test_add_only_model_permission_cannot_modify_an_existing_model(self):
        provider = self.provider()
        add_model = Permission.objects.get(codename="add_aimodel", content_type__app_label="providers")
        self.staff.user_permissions.add(add_model)
        model = configure_model(
            actor=self.staff,
            provider=provider,
            identifier="add-only-model",
            name="Add only model",
            capabilities=[AIModelCapability.TEXT_GENERATION],
        )
        with self.assertRaises(PermissionDenied):
            configure_model(
                actor=self.staff,
                provider=provider,
                identifier=model.identifier,
                name="Unauthorized update",
                capabilities=[AIModelCapability.TEXT_GENERATION],
            )
        model.refresh_from_db()
        self.assertEqual(model.name, "Add only model")
