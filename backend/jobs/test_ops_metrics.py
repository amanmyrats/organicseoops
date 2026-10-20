from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from tenancy.services import create_organization, create_project
from tenancy.models import Organization, OrganizationDeletionRun
from providers.models import AIModel, AIProvider, AIProviderAccount

from .management.commands.publish_ops_metrics import _metrics
from .models import AIUsageRecord, JobRun, JobStatus, JobStep
from .services import create_job, transition


@override_settings(DEBUG=True, PRODUCTION_APP_HOST=True, SES_FEEDBACK_REGION="eu-west-1")
class OperationsMetricsTests(TestCase):
    def test_aggregate_job_failure_and_known_duration_without_provider_inference(self):
        user = get_user_model().objects.create_user("ops@example.invalid", "Strong passphrase 99!")
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        organization = create_organization(user=user, name="Synthetic ops")
        project = create_project(organization=organization, user=user, name="Synthetic site",
                                 canonical_origin="https://ops.example.invalid")
        jobs = []
        for _ in range(2):
            job = create_job(project=project, actor=user, handler="diagnostic_probe",
                             input_snapshot={"sample": "synthetic", "simulate_partial": False})
            transition(job, JobStatus.RUNNING)
            transition(job, JobStatus.FAILED)
            jobs.append(job)
        JobRun.objects.filter(pk=jobs[1].pk).update(updated_at=timezone.now() - timedelta(minutes=8))
        metrics = {item["MetricName"]: item for item in _metrics(timezone.now())}
        self.assertEqual(metrics["FailedJobs"]["Value"], 1)
        self.assertEqual(metrics["ProviderFailedOrUnknown"]["Value"], 0)
        self.assertEqual(metrics["OverdueCustomerDeletionRuns"]["Value"], 0)
        self.assertEqual(metrics["ClosedTenantsMissingDeletionRun"]["Value"], 0)
        self.assertGreaterEqual(metrics["MaxJobLifecycleMs"]["Value"], 0)
        self.assertNotIn("MaxMeasuredProviderDurationMs", metrics)
        self.assertTrue(all(item["Dimensions"] == [{"Name": "Environment", "Value": "production"}]
                            for item in metrics.values()))
        provider = AIProvider.objects.create(key="synthetic", name="Synthetic provider", kind="openai",
                                             egress_policy="official_openai")
        model = AIModel.objects.create(provider=provider, identifier="synthetic-model", name="Synthetic model",
                                       capabilities=["text_generation"])
        account = AIProviderAccount.objects.create(provider=provider, organization=organization, label="Synthetic account")
        attempted = JobRun.objects.create(organization=organization, project=project, actor=user,
                                          handler="ai_text", method_version="ai-text-v2",
                                          input_snapshot={"synthetic": True})
        step = JobStep.objects.create(job=attempted, sequence=1, name="Synthetic attempt", status="failed")
        AIUsageRecord.objects.create(job=attempted, step=step, organization=organization, project=project,
                                     provider=provider, model=model, account=account,
                                     operation_version="ai-text-v2", status=AIUsageRecord.Status.FAILED,
                                     finished_at=timezone.now(), duration_ms=375)
        metrics = {item["MetricName"]: item for item in _metrics(timezone.now())}
        self.assertEqual(metrics["ProviderFailedOrUnknown"]["Value"], 1)
        self.assertEqual(metrics["MaxMeasuredProviderDurationMs"]["Value"], 375)
        deadline = timezone.now() - timedelta(days=31)
        Organization.objects.filter(pk=organization.pk).update(is_suspended=True, closed_at=deadline)
        self.assertEqual({row["MetricName"]: row["Value"] for row in _metrics(timezone.now())}[
            "ClosedTenantsMissingDeletionRun"], 1)
        run = OrganizationDeletionRun.objects.create(organization=organization,
            source=OrganizationDeletionRun.Source.OWNER_CLOSED,
            eligible_at=deadline, due_at=deadline + timedelta(days=30), project_ids=[project.pk])
        metrics = {row["MetricName"]: row["Value"] for row in _metrics(timezone.now())}
        self.assertEqual((metrics["ClosedTenantsMissingDeletionRun"], metrics["OverdueCustomerDeletionRuns"]), (0, 1))
        OrganizationDeletionRun.objects.filter(pk=run.pk).update(state=run.State.COMPLETE, completed_at=timezone.now())
        self.assertEqual({row["MetricName"]: row["Value"] for row in _metrics(timezone.now())}[
            "OverdueCustomerDeletionRuns"], 0)
        with patch("jobs.management.commands.publish_ops_metrics.boto3.client") as client:
            call_command("publish_ops_metrics")
            client.assert_called_once_with("cloudwatch", region_name="eu-west-1")
            self.assertEqual(client.return_value.put_metric_data.call_args.kwargs["Namespace"],
                             "OrganicSEOOps/Jobs")
        with override_settings(PRODUCTION_APP_HOST=False):
            with patch("jobs.management.commands.publish_ops_metrics.boto3.client") as client:
                with self.assertRaises(CommandError):
                    call_command("publish_ops_metrics")
                client.assert_not_called()
