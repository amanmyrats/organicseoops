from tenancy.customer_artifact_barrier import project_artifact_barrier
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.db import connection, connections, IntegrityError, transaction
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, Project, ProjectMembership
from tenancy.services import create_organization, create_project
from . import crux_alert_preferences as preferences, test_alert_preferences as fixtures
from .alert_preferences import set_project_alert_preference
from .summary_preferences import set_project_summary_preference
from .models import ProjectCruxAlertPreference, ProjectAlertPreference, ProjectSummaryPreference


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crux-intent"}})
class CruxAlertPreferenceTests(TransactionTestCase):
    setUp = fixtures.AlertPreferenceTests.setUp

    def save(self, frequency="daily", revision=0, actor=None):
        return preferences.set_project_crux_alert_preference(project=self.project, actor=actor or self.owner,
                                                             frequency=frequency, expected_revision=revision)

    def test_defaults_and_operational_weekly_independence_save_never_read_sources_dispatch_or_send(self):
        set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=0)
        set_project_alert_preference(project=self.project, actor=self.owner, frequency="daily",
                                     source_families=["crawl_failure", "integration_health"], expected_revision=0)
        with CaptureQueriesContext(connection) as queries:
            result = preferences.project_crux_alert_preference(project=self.project, actor=self.owner)
            self.assertEqual(result, {"channel": "email", "source_family": "crux_material", "frequency": "off",
                                      "revision": 0, "delivery_state": "rollout_off"})
            self.assertEqual(self.save("off"), result)
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        with override_settings(CRUX_ALERT_DELIVERY_ENABLED=True):
            enabled = preferences.project_crux_alert_preference(project=self.project, actor=self.owner)
            self.assertEqual(enabled, {**result, "delivery_state": "enabled_optional"})
            self.assertFalse(ProjectCruxAlertPreference.objects.exists())
        with patch("http.client.HTTPSConnection.request", side_effect=AssertionError("network")), \
                patch("jobs.crux_episode_source.current_material_crux_episodes", side_effect=AssertionError("source")), \
                patch("jobs.tasks.scan_daily_alert_digests_task.apply_async", side_effect=AssertionError("dispatch")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            self.assertEqual(self.save()["revision"], 1)
        self.assertEqual(ProjectSummaryPreference.objects.get().frequency, "weekly")
        self.assertTrue(ProjectAlertPreference.objects.get().integration_health)
        from .models import JobRun, ProjectAlertDelivery, ProjectAlertEpisodeClaim
        self.assertFalse(any(model.objects.exists() for model in (JobRun, ProjectAlertDelivery, ProjectAlertEpisodeClaim)))

    def test_revision_idempotency_and_original_intent_timestamp_only_change_on_real_frequency_edits(self):
        self.assertEqual(self.save()["revision"], 1)
        row = ProjectCruxAlertPreference.objects.get(); original = row.updated_at
        self.assertEqual(self.save(revision=1)["revision"], 1)
        row.refresh_from_db(); self.assertEqual(row.updated_at, original)
        self.assertEqual(self.save("off", 1)["revision"], 2)
        row.refresh_from_db(); self.assertGreater(row.updated_at, original)
        disabled_at = row.updated_at
        with self.assertRaises(ValidationError): self.save(revision=1)
        self.assertEqual(self.save("off", 2)["revision"], 2)
        row.refresh_from_db(); self.assertEqual(row.updated_at, disabled_at)
        self.assertEqual(self.save(revision=2)["revision"], 3)

    def test_exact_frequency_revision_validation_and_postgresql_constraints(self):
        for frequency, revision in [(True, 0), ("weekly", 0), ("spam", 0), ([], 0), ("daily", True),
                                    ("daily", -1), ("off", 2**31 - 1), ("daily", "0")]:
            with self.subTest(frequency=frequency, revision=revision), self.assertRaises(ValidationError): self.save(frequency, revision)
        self.save()
        for values in ({"frequency": "spam"}, {"revision": 0}):
            with transaction.atomic(), self.assertRaises(IntegrityError):
                ProjectCruxAlertPreference.objects.filter(user=self.owner).update(**values)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectCruxAlertPreference.objects.create(project=self.project, user=self.owner)

    def test_own_viewer_restricted_foreign_and_verified_enable_only(self):
        with self.assertRaises(PermissionDenied): self.save(actor=self.other)
        member = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(self.save(actor=self.other)["frequency"], "daily")
        self.assertEqual(preferences.project_crux_alert_preference(project=self.project, actor=self.owner)["revision"], 0)
        foreign = deepcopy(self.project); foreign.organization_id += 10000
        with self.assertRaises(PermissionDenied): preferences.project_crux_alert_preference(project=foreign, actor=self.owner)
        EmailAddress.objects.filter(user=self.other).update(verified=False)
        with self.assertRaises(PermissionDenied): self.save(revision=1, actor=self.other)
        self.assertEqual(self.save("off", 1, self.other)["revision"], 2)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.save("off", 2, self.other)
        ProjectMembership.objects.create(project=self.project, organization_membership=member)
        self.assertEqual(self.save("off", 2, self.other)["revision"], 2)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True)
        with self.assertRaises(PermissionDenied): self.save("off", 2, self.other)

    def test_final_insert_and_projection_authority_loss_rollback_or_deny(self):
        create = ProjectCruxAlertPreference.objects.create
        for change in (lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
                       lambda: OrganizationMembership.objects.filter(organization=self.org, user=self.owner).delete()):
            def changed(**kwargs):
                row = create(**kwargs); change(); return row
            with patch("jobs.crux_alert_preferences.ProjectCruxAlertPreference.objects.create", side_effect=changed), self.assertRaises(PermissionDenied):
                self.save()
            self.assertFalse(ProjectCruxAlertPreference.objects.exists())
            self.assertTrue(EmailAddress.objects.get(user=self.owner).verified)
        original = preferences._preference
        def changed_projection(row):
            result = original(row)
            Organization.objects.filter(pk=self.org.pk).update(is_suspended=True)
            return result
        with patch("jobs.crux_alert_preferences._preference", side_effect=changed_projection), self.assertRaises(PermissionDenied):
            preferences.project_crux_alert_preference(project=self.project, actor=self.owner)

    def test_actual_customer_export_scoped_organization_erasure_and_personal_close(self):
        from accounts.closure import close_personal_access
        from tenancy.customer_inventory import require_complete_ownership_map
        from tenancy.customer_export import project_customer_rows, _reviewed_fields
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records, _customer_deletion_order
        self.save()
        other_org = create_organization(user=self.other, name="Other CrUX intent")
        other_project = create_project(organization=other_org, user=self.other, name="Other site", canonical_origin="https://other-crux-intent.example.invalid")
        preferences.set_project_crux_alert_preference(project=other_project, actor=self.other, frequency="daily", expected_revision=0)
        require_complete_ownership_map(); _reviewed_fields("jobs.ProjectCruxAlertPreference")
        order = [model._meta.label for model, _ in _customer_deletion_order()]
        self.assertLess(order.index("jobs.ProjectCruxAlertPreference"), order.index("tenancy.Project"))
        row = ProjectCruxAlertPreference.objects.get(project=self.project)
        exported = project_customer_rows(organization=self.org, actor=self.owner,
            model_label="jobs.ProjectCruxAlertPreference", after_id=0, through_id=row.pk)
        self.assertEqual([item["user_id"] for item in exported["rows"]], [self.owner.pk])
        self.assertEqual(exported["rows"][0]["frequency"], "daily")
        with project_artifact_barrier(self.org.pk, shared=True), transaction.atomic():
            Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
            run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
            delete_customer_database_records(run=run)
            self.assertFalse(ProjectCruxAlertPreference.objects.filter(project_id=self.project.pk).exists())
            self.assertTrue(ProjectCruxAlertPreference.objects.filter(project=other_project).exists())
            transaction.set_rollback(True)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        request = RequestFactory().post("/api/account/close/"); request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_personal_access(actor=self.owner, request=request)
        self.assertFalse(ProjectCruxAlertPreference.objects.filter(user=self.owner).exists())
        self.assertTrue(ProjectCruxAlertPreference.objects.filter(user=self.other).exists())


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crux-intent-race"}})
class ConcurrentCruxPreferenceTests(TransactionTestCase):
    setUp = fixtures.AlertPreferenceTests.setUp

    def test_two_genuine_sessions_cannot_both_create_or_overwrite_revision_zero(self):
        def save():
            connections.close_all()
            try:
                preferences.set_project_crux_alert_preference(project=self.project, actor=self.owner, frequency="daily", expected_revision=0)
                return "saved"
            except ValidationError:
                return "stale"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: save(), range(2)))
        self.assertCountEqual(results, ["saved", "stale"])
        self.assertEqual(ProjectCruxAlertPreference.objects.count(), 1)
        self.assertEqual(ProjectCruxAlertPreference.objects.get().revision, 1)
