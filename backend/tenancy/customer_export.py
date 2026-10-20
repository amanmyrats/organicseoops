"""Owner-only, capped rows of currently retained customer models; no platform secrets."""
from hashlib import sha256
from io import BytesIO
from itertools import islice
import json
import re
from zipfile import ZIP_STORED, ZipFile

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from config.observability import redact

from .customer_inventory import CUSTOMER, require_complete_ownership_map
from config.artifacts import ArtifactStorageError, ArtifactValidationError

from .artifacts import (iter_project_artifact_keys, project_artifact_page, project_artifact_scope,
                        read_project_artifact)
from .models import AuditEvent, AuditEventType, Organization, OrganizationMembership, Project
from .services import Action, require_organization_action


# Current reviewed schemas. Any newly added field needs an explicit export review,
# not automatic serialization of a possibly encrypted or bearer-bearing column.
SCHEMAS = {
    "jobs.ContentLifecycleReview": "0bf4de99c42441c8",
    "jobs.AuthorityLinkReview": "4d4752d2e8d9cde5",
    "jobs.AuthorityProspectReview": "d7001aee057f83e4",
    "jobs.AIVisibilityManualObservation": "8516d7dc1eccc900",
    "jobs.AIVisibilityAnswerReview": "b2a2c8d26db52d51",
    "jobs.AIVisibilityPromptSet": "b4272f72a07d97ca",
    "jobs.TopicReview": "22fb85de0ec43417",
    "jobs.ContentItem": "ffa3717405f19430",
    "jobs.ContentRevision": "3d087bdd87afebda",
    "jobs.ContentBriefSnapshot": "92b7bf4635ed3eff",
    "integrations.GA4LandingPageSnapshot": "b762ab5a4da71750",
    "integrations.GA4MeasurementReview": "45bcc3e518edb5de",
    "integrations.ImportExecutionState": "e380f1a1704252fc",
    "integrations.ImportRowError": "1da820f7eccf71db",
    "integrations.ImportRun": "f7a9c074f7bc261f",
    "integrations.IntegrationConnection": "8270be31486935fe",
    "integrations.PendingArtifactCleanup": "e3ae2c2df0c821bc",
    "integrations.QueryBrandReview": "935e76d651a18920",
    "integrations.SearchAnalyticsPageSnapshot": "04abbb55c403f735",
    "integrations.SearchAnalyticsQueryPageSnapshot": "c4f213e4042b25f0",
    "integrations.SearchConsoleBackfill": "1a50d2997fc64c07",
    "integrations.SearchConsoleCoverageObservation": "e999f4518686004c",
    "integrations.SearchMetricObservation": "39fcaa89c32b6079",
    "integrations.SyncCursor": "0d8dc9e438620120",
    "jobs.ActionOutcomeSnapshot": "109a753927b55afa",
    "jobs.ActionReview": "bdf70a347ab57c60",
    "jobs.ActionTechnicalOutcomeSnapshot": "6a8095a6dda786b2",
    "jobs.Artifact": "a0ef95c59e05c622",
    "jobs.CrawlPageSnapshot": "dac4a871936c8a8f",
    "jobs.CrawlRun": "f36023a6a203dab8",
    "jobs.FirstBoundedAuditCompletion": "c6facc7181b2472c",
    "jobs.FirstAuditValueAcknowledgment": "2eaa51ac0c2e10e9",
    "jobs.Finding": "de812cf6d8cba217",
    "jobs.IndexationEvidenceSnapshot": "a7ce6e45982c9442",
    "jobs.IntentClusterReview": "36e1180365284120",
    "jobs.JobCancellation": "c31a0556e7529fa6",
    "jobs.JobRun": "ecfaa4ec702b61d6",
    "jobs.JobSchedule": "32c55f566c34cdfa",
    "jobs.JobStep": "f8737f4b7ce93f69",
    "jobs.LocalBusinessAssessment": "65fd91fc184eb36f",
    "jobs.LocalFeedbackReview": "afb4153287925145",
    "jobs.LocalVisibilityObservation": "171bdaba2294cc97",
    "jobs.Opportunity": "83684981e91f4056",
    "jobs.PerformanceObservationSnapshot": "95ffc3ce8aafb14d",
    "jobs.ProjectReportShare": "7758ab1c407d0723",
    "jobs.ProjectReportSnapshot": "0a89b7facb61be29",
    "jobs.ProjectSummaryPreference": "b747a00d2268b908",
    "jobs.ProjectAlertPreference": "881d6da70e1941bc",
    "jobs.ProjectCruxAlertPreference": "b747a00d2268b908",
    "jobs.ProjectCruxAlertDelivery": "60152aa63f40fd29",
    "jobs.ProjectCruxEpisodeClaim": "f52ceea43ec92a82",
    "jobs.ProjectSummaryDelivery": "60330f56973bf950",
    "jobs.ProjectAlertDelivery": "60152aa63f40fd29",
    "jobs.ProjectAlertEpisodeClaim": "f52ceea43ec92a82",
    "jobs.Recommendation": "c3d15040317622c3",
    "jobs.RenderAttempt": "bd4b9f0580bea874",
    "jobs.RenderedPageSnapshot": "b17e1a7d8147270c",
    "jobs.SourceCitation": "db540cfa696f9fa2",
    "jobs.TechnicalDiagnosticsSnapshot": "ce4003e5decb8104",
    "jobs.TopicCandidateSnapshot": "8360bb14389ad5d3",
    "providers.AIProviderAccount": "ec704dab2b094ccd",
    "providers.AIRoutingPolicy": "be9df13dfe59d34a",
    "tenancy.DomainAlias": "d298a2324b047516",
    "tenancy.InvitationProject": "6a271e8338fc8a8a",
    "tenancy.Organization": "0c98ebb1dd1be681",
    "tenancy.OrganizationInvitation": "7038aed1666ad03e",
    "tenancy.OrganizationMembership": "068c72ed0662d78e",
    "tenancy.OwnershipTransfer": "8aac81774e5b0198",
    "tenancy.Project": "a827e6bfeae21419",
    "tenancy.ProjectConfiguration": "f05aca2d3dd83d7a",
    "tenancy.ProjectMembership": "6a0afb82840aa7e9",
    "tenancy.ProjectOriginVerification": "3d1ac26363ce1ea4",
    "tenancy.SupportRequest": "6be02856484a6b2b",
    "tenancy.SupportRequestUpdate": "95da4a98b063a507",
}
FIELD_TYPES = "93a611a578be2a84"

PRIVATE_FIELDS = frozenset({"artifact_key", "key", "credential_reference", "secret_reference", "request_key",
                            "idempotency_key", "token_digest", "challenge_digest", "state_digest",
                            "session_digest", "token_hash", "request_hash"})
PRIVATE_NESTED_KEY = re.compile(r"(?i)(secret|token|password|api[_-]?key|authorization|cookie|credential|signature|csrf)")
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_RECORDS = 5000


def _safe(value):
    if type(value) is dict:
        return {str(key): "[REDACTED]" if PRIVATE_NESTED_KEY.search(str(key)) else _safe(item)
                for key, item in value.items()}
    if type(value) in (tuple, list):
        return [_safe(item) for item in value]
    return redact(value) if type(value) is str else value


def _reviewed_fields(model_label):
    require_complete_ownership_map()
    model = apps.get_model(model_label)
    fields = model._meta.concrete_fields
    digest = sha256(",".join(field.attname for field in fields).encode()).hexdigest()[:16]
    types = sha256("|".join(f"{label}:{field.attname}:{field.get_internal_type()}"
                            for label in sorted(CUSTOMER)
                            for field in apps.get_model(label)._meta.concrete_fields).encode()).hexdigest()[:16]
    if SCHEMAS.get(model_label) != digest or set(SCHEMAS) != set(CUSTOMER) or types != FIELD_TYPES:
        raise RuntimeError("Customer export schema requires a reviewed field assignment.")
    return model, fields


def _row(record, fields):
    row = {field.attname: _safe(getattr(record, field.attname)) for field in fields
           if field.attname not in PRIVATE_FIELDS}
    if record._meta.label in {"jobs.JobRun", "jobs.JobStep"}:
        job = record if record._meta.label == "jobs.JobRun" else record.job
        if job.handler == "analyze_repository":
            from jobs.repository_analysis import SANDBOX, source_current
            row["source_current"] = source_current(job)
            row["scope"] = "historical_bounded_root_declared_dependencies_not_source_code_installed_versions_or_vulnerability_findings"
            if job.input_snapshot["operation"] == "root_pinned_dependency_advisories":
                row["scope"] = "historical_osv_supported_exact_declared_root_pin_advisories_not_installed_transitive_exploitability_or_complete_security_assessment"
            if job.input_snapshot["operation"] == "root_npm_lockfile_advisories":
                row["scope"] = "historical_root_npm_lockfile_reported_public_registry_packages_osv_matches_not_installed_manifest_consistency_or_complete_security_assessment"
            if job.input_snapshot["operation"] == "selected_python_call_observations":
                row["scope"] = "historical_selected_python_call_syntax_locations_not_execution_alias_dataflow_or_exploitability_proof"
            if record._meta.label == "jobs.JobStep" and record.name == SANDBOX:
                row["output"] = {"cleanup_confirmed": record.output.get("cleanup_confirmed") is True}
            if record._meta.label == "jobs.JobRun":
                source = {key: job.config_snapshot[key] for key in ("provider", "repository", "repository_id", "commit_sha", "permissions", "method")}
                row["config_snapshot"] = source
                if row.get("output"):
                    row["output"] = {**row["output"], "source": source}
            if not row["source_current"] and "output" in row:
                row["output"] = {"state": "repository_source_authority_unavailable"}
        if job.handler == "collect_serp":
            from .services import project_has_origin
            row["source_current"] = project_has_origin(job.project, job.input_snapshot["origin"])
            row["scope"] = "historical_provider_top10_organic_observation_by_exact_dimensions_not_webmaster_average_or_universal_rank"
            if not row["source_current"] and "output" in row:
                row["output"] = {"state": "original_origin_unavailable"}
        if job.handler == "classify_competitor_heading_topics":
            row["scope"] = "historical_original_single_heading_facts_and_unverified_topic_hypotheses_not_current_use_semantic_truth_page_topics_gaps_intent_freshness_rankings_whole_site_or_human_approval"
        if job.handler == "synthesize_competitor_headings_pair":
            row["scope"] = "historical_original_heading_facts_and_unverified_ai_notes_not_current_use_page_topics_content_gaps_freshness_or_human_approval"
        if job.handler == "synthesize_competitor_pair":
            row["scope"] = "historical_original_static_facts_and_unverified_ai_notes_not_current_use_or_human_approval"
        if job.handler == "collect_competitor_root":
            row["scope"] = "historical_selected_static_root_not_current_use_permission_or_whole_site_comparison"
        if job.handler == "collect_competitor_lighthouse":
            row["scope"] = "historical_selected_uri_device_provider_reported_lab_sample_not_current_use_field_p75_whole_site_rankings_causality_or_live_provider_proof"
        if job.handler == "collect_competitor_page_formats":
            row["scope"] = "historical_selected_static_content_element_counts_not_current_use_rendered_formats_page_types_loaded_media_search_features_or_whole_site"
        if job.handler == "collect_competitor_page_dates":
            row["scope"] = "historical_selected_static_article_date_declarations_not_validated_publication_change_age_freshness_or_current_use_permission"
        if job.handler == "collect_competitor_page_destinations":
            row["scope"] = "historical_selected_static_nonroot_same_origin_references_not_current_use_unique_pages_link_health_crawl_authority_or_whole_site"
        if job.handler == "collect_competitor_page_headings":
            row["scope"] = "historical_selected_static_nonroot_headings_not_current_use_browser_outline_topics_page_identity_freshness_or_whole_site"
        if job.handler == "collect_competitor_page":
            row["scope"] = "historical_selected_static_nonroot_uri_not_current_use_page_identity_freshness_or_whole_site"
        if job.handler == "collect_competitor_links_root":
            row["scope"] = "historical_selected_static_link_categories_not_current_use_unique_pages_link_health_inbound_links_or_whole_site"
        if job.handler == "collect_competitor_schema_root":
            row["scope"] = "historical_selected_static_schema_labels_not_current_use_schema_validity_rich_results_or_whole_site"
        if job.handler == "collect_passive_http_redirects":
            row["scope"] = "historical_plaintext_http_location_syntax_not_current_use_authenticated_identity_observed_https_or_followed_upgrade"
        if job.handler == "collect_passive_redirect_chain":
            row["scope"] = "historical_exact_selected_chain_responses_not_current_use_availability_authenticated_http_identity_browser_behavior_or_security_verdict"
        if job.handler == "import_bot_logs":
            from jobs.bot_log_import import source_current
            row["source_current"] = source_current(job)
            if not row["source_current"]:
                for field in ("input_snapshot", "config_snapshot", "output"):
                    if field in row:
                        row[field] = {"state": "source_authority_unavailable"}
        if job.handler == "sync_yandex_webmaster":
            from integrations.yandex_sync import source_current
            row["source_current"] = source_current(job)
            row["scope"] = "historical_yandex_site_history_source_offsets_not_google_metrics_or_complete_final_coverage"
            if not row["source_current"]:
                for field in ("input_snapshot", "config_snapshot", "output"):
                    if field in row:
                        row[field] = {"state": "source_authority_unavailable"}
        if job.handler == "import_yandex_webmaster_csv":
            from integrations.yandex_webmaster import source_current
            row["source_current"] = source_current(job)
            row["scope"] = "historical_partial_customer_supplied_yandex_query_url_region_export_not_live_provider_or_indexing_proof"
            if not row["source_current"]:
                for field in ("input_snapshot", "config_snapshot", "output"):
                    if field in row:
                        row[field] = {"state": "source_authority_unavailable"}
    if isinstance(record, OrganizationMembership):
        row["member_email"] = redact(record.user.email)  # Owner already sees the scoped team roster.
    if record._meta.label == "jobs.LocalFeedbackReview":
        from jobs.local_feedback import feedback_source_current
        row["source_current_at_capture"] = feedback_source_current(record)
        row["scope"] = "historical_customer_record_not_current_manual_use_authorization"
        row["execution_state"] = "customer_reported_not_verified" if record.executed_at else "not_reported"
    if record._meta.label == "jobs.AuthorityProspectReview":
        from jobs.authority import prospect_source_current
        row["source_current_at_capture"] = prospect_source_current(record)
        row["scope"] = "historical_human_prospect_not_link_proof_or_current_use_permission"
        row["execution_state"] = "customer_reported_not_verified" if record.executed_at else "not_reported"
    if record._meta.label == "jobs.AuthorityLinkReview":
        from jobs.authority_links import link_review_source_current
        row["source_current_at_capture"] = link_review_source_current(record)
        row["scope"] = "historical_human_link_report_not_external_verification_or_current_use_permission"
        row["execution_state"] = "manual_activity_report_not_site_or_link_verification" if record.executed_at else "not_reported"
    if record._meta.label == "jobs.ContentLifecycleReview":
        from jobs.content_lifecycle import lifecycle_source_current
        row["source_current_at_capture"] = lifecycle_source_current(record)
        row["scope"] = "historical_human_content_judgment_not_live_quality_or_current_use_authorization"
        row["execution_state"] = "manual_handoff_not_site_implementation_or_outcome" if record.executed_at else "not_reported"
    if record._meta.label == "jobs.LocalVisibilityObservation":
        from jobs.local_visibility import visibility_source_current
        row["source_current_at_capture"] = visibility_source_current(record)
        row["scope"] = "historical_customer_report_not_verified_or_universal_rank"
    if record._meta.label == "integrations.SearchAnalyticsQueryPageSnapshot":
        from integrations.search_console_analytics import validate_query_page_snapshot
        validate_query_page_snapshot(record, current=False)
        row["scope"] = "historical_bounded_paired_observations_not_complete_coverage_or_current_use_authorization"
    if record._meta.label == "jobs.Finding" and record.source_passive_header_id:
        row["scope"] = "historical_response_fact_not_current_passive_use_authorization_or_risk_severity"
    if record._meta.label == "jobs.Finding" and record.source_passive_resource_id:
        row["scope"] = "historical_literal_resource_fact_not_current_passive_use_authorization_browser_behavior_or_risk_severity"
    if record._meta.label == "jobs.Finding" and record.source_passive_tls_id:
        row["scope"] = "historical_literal_tls_fact_not_current_passive_use_authorization_supported_configuration_or_risk_severity"
    if record._meta.label == "jobs.Finding" and record.source_passive_redirect_id:
        row["scope"] = "historical_literal_location_fact_not_current_passive_use_authorization_followed_redirect_or_risk_severity"
    if record._meta.label == "jobs.Finding" and record.source_passive_redirect_chain_id:
        row["scope"] = "historical_literal_chain_fact_not_current_passive_use_authorization_availability_authenticated_http_browser_behavior_or_risk_severity"
    if record._meta.label == "jobs.Opportunity" and record.passive_source_sha256:
        row["scope"] = "historical_human_passive_priority_not_current_use_risk_severity_approval_or_page_action"
    if record._meta.label == "jobs.AIVisibilityManualObservation":
        from jobs.visibility_manual import manual_source_current
        row["source_current_at_capture"] = manual_source_current(record)
        row["scope"] = "historical_human_report_not_consumer_verification_or_current_use_permission"
    return row


def project_customer_rows(*, organization, actor, model_label, after_id, through_id):
    if (type(model_label) is not str or model_label not in CUSTOMER or type(after_id) is not int or after_id < 0
        or type(through_id) is not int or through_id <= after_id):
        raise ValidationError("Select an exact customer record window.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        model, fields = _reviewed_fields(model_label)
        queryset = model.objects.filter(**{CUSTOMER[model_label]: organization.pk},
            pk__gt=after_id, pk__lte=through_id).order_by("pk")
        if model_label == "tenancy.OrganizationMembership":
            queryset = queryset.select_related("user")
        records = list(queryset[:51])
        rows = []
        payload = {"version": "organization-export-rows-v1", "organization_id": organization.pk,
                   "scope": "one_model_page_not_a_complete_organization_export", "model": model_label,
                   "rows": rows, "has_more": True, "next_after_id": after_id,
                   "through_id": through_id}
        for record in records[:50]:
            rows.append(_row(record, fields))
            payload["next_after_id"] = record.pk
            try:
                # Match JsonResponse's default ASCII escaping, including the
                # longer `has_more: true` spelling used by a partial page.
                size = len(json.dumps(payload, cls=DjangoJSONEncoder).encode())
            except (ValueError, TypeError, RecursionError):
                raise ValidationError("Customer records cannot be safely serialized.") from None
            if size > 512 * 1024:
                rows.pop()
                if not rows:
                    raise ValidationError("A customer record exceeds the bounded export size.")
                payload["next_after_id"] = records[len(rows) - 1].pk
                break
        payload["has_more"] = len(records) > len(rows)
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
            details={"kind": "records", "model": model_label, "after_id": after_id,
                     "through_id": through_id, "returned": len(rows)})
        return payload


def complete_bounded_customer_archive(*, organization, actor, output=None):
    """One immutable response containing every current customer model and visible artifact, or fail."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        # ponytail: one org lock and 32MiB in-memory ceiling; use durable async
        # chunked snapshots if a real tenant exceeds this bounded first release.
        private_output = output is not None
        output = output if private_output else BytesIO()
        started_at = timezone.now().isoformat()
        manifest = {"version": "customer-content-archive-v1", "organization_id": organization.pk,
            "captured_at": started_at,
            "scope": "all_current_customer_models_and_visible_artifacts_only",
            "consistency": "sequential_observations_not_a_transactional_snapshot",
            "excluded": ["restricted_billing_and_audit", "platform_and_oauth_credentials", "backup_versions"],
            "tables": [], "artifacts": []}
        remaining = MAX_ARCHIVE_RECORDS
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            for label, lookup in sorted(CUSTOMER.items()):
                model, fields = _reviewed_fields(label)
                queryset = model.objects.filter(**{lookup: organization.pk}).order_by("pk")
                if label == "tenancy.OrganizationMembership":
                    queryset = queryset.select_related("user")
                filename = f"records/{label.replace('.', '/')}.json"
                digest = sha256()
                count = 0
                with archive.open(filename, "w") as entry:
                    entry.write(b"[")
                    digest.update(b"[")
                    for record in queryset.iterator(chunk_size=50):
                        if remaining == 0:
                            raise ValidationError("Organization customer archive exceeds its bounded record ceiling.")
                        data = json.dumps(_row(record, fields), cls=DjangoJSONEncoder,
                            ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
                        if len(data) + output.tell() > MAX_ARCHIVE_BYTES:
                            raise ValidationError("Organization customer archive exceeds its bounded byte ceiling.")
                        if count:
                            entry.write(b",")
                            digest.update(b",")
                        entry.write(data)
                        digest.update(data)
                        count += 1
                        remaining -= 1
                    entry.write(b"]")
                    digest.update(b"]")
                manifest["tables"].append({"model": label, "count": count, "filename": filename,
                    "observation_completed_at": timezone.now().isoformat(),
                    "schema": SCHEMAS[label], "sha256": digest.hexdigest()})
                if output.tell() > MAX_ARCHIVE_BYTES:
                    raise ValidationError("Organization customer archive exceeds its bounded byte ceiling.")
            for project in Project.objects.filter(organization=organization).order_by("pk"):
                keys = list(islice(iter_project_artifact_keys(project=project), 1001))
                if len(keys) > 1000:
                    raise ValidationError("Organization customer archive exceeds its bounded artifact ceiling.")
                for index, key in enumerate(keys):
                    if not key.startswith(project_artifact_scope(project) + "/"):
                        raise ArtifactStorageError("Private export artifact is unavailable.")
                    try:
                        storage = storages["artifacts"]
                        size = storage.size(key)
                    except Exception:
                        raise ArtifactStorageError("Private export artifact is unavailable.") from None
                    if type(size) is not int or size <= 0 or size > settings.ARTIFACT_MAX_BYTES:
                        raise ArtifactStorageError("Private export artifact has an invalid size.")
                    if output.tell() + size > MAX_ARCHIVE_BYTES:
                        raise ValidationError("Organization customer archive exceeds its bounded byte ceiling.")
                    filename = f"project-{project.pk}/artifact-{index}.{key.rsplit('.', 1)[-1]}"
                    digest = sha256()
                    counted = 0
                    try:
                        with storage.open(key, "rb") as source, archive.open(filename, "w") as entry:
                            while block := source.read(1024 * 1024):
                                if not isinstance(block, bytes) or counted + len(block) > size:
                                    raise ArtifactStorageError("Private export artifact changed during capture.")
                                entry.write(block)
                                digest.update(block)
                                counted += len(block)
                    except Exception:
                        raise ArtifactStorageError("Private export artifact is unavailable.") from None
                    if counted != size:
                        raise ArtifactStorageError("Private export artifact changed during capture.")
                    manifest["artifacts"].append({"project_id": project.pk, "index": index,
                        "observation_completed_at": timezone.now().isoformat(),
                        "filename": filename, "size_bytes": counted, "sha256": digest.hexdigest()})
                    if output.tell() > MAX_ARCHIVE_BYTES:
                        raise ValidationError("Organization customer archive exceeds its bounded byte ceiling.")
            manifest["capture_window"] = {"started_at": started_at, "completed_at": timezone.now().isoformat()}
            archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        size = output.tell()
        if size > MAX_ARCHIVE_BYTES:
            raise ValidationError("Organization customer archive exceeds its bounded byte ceiling.")
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
            details={"kind": "bounded_archive", "tables": len(manifest["tables"]),
                     "artifacts": len(manifest["artifacts"]), "size_bytes": size})
        if private_output:
            output.seek(0)
            return output
        return output.getvalue()


def project_customer_artifact(*, organization, actor, project_id, artifact_index):
    if type(project_id) is not int or project_id < 1 or type(artifact_index) is not int or artifact_index < 0:
        raise ValidationError("Choose one current private project artifact.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        project = Project.objects.filter(pk=project_id, organization=organization).first()
        if project is None:
            raise ValidationError("Artifact project is unavailable.")
        keys, _more = project_artifact_page(project=project, offset=artifact_index, limit=1)
        if not keys:
            raise ValidationError("Artifact selection is unavailable.")
        key = keys[0]
        try:
            size = storages["artifacts"].size(key)
            if not 1 <= size <= settings.ARTIFACT_MAX_BYTES:
                raise ArtifactValidationError("Private export artifact exceeds the configured size.")
            if size > 10 * 1024 * 1024:
                data = storages["artifacts"].open(key, "rb")
                # ponytail: hash while holding the org lock; move to a durable
                # export job if large multi-file snapshots become common.
                try:
                    digest = sha256()
                    counted = 0
                    while block := data.read(1024 * 1024):
                        counted += len(block)
                        if counted > size:
                            raise ArtifactValidationError("Private artifact changed during export.")
                        digest.update(block)
                    if counted != size:
                        raise ArtifactValidationError("Private artifact changed during export.")
                    data.seek(0)
                    checksum = digest.hexdigest()
                except Exception:
                    data.close()
                    raise
            else:
                data = read_project_artifact(project=project, key=key)
                if len(data) != size:
                    raise ArtifactValidationError("Private artifact changed during export.")
                checksum = sha256(data).hexdigest()
        except Exception:
            raise ArtifactStorageError("Private export artifact is unavailable.") from None
        try:
            AuditEvent.objects.create(organization=organization, project=project, actor=actor,
                event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
                details={"kind": "artifact", "index": artifact_index, "size_bytes": size})
        except Exception:
            if not isinstance(data, bytes):
                data.close()
            raise
        return data, key.rsplit(".", 1)[-1], checksum
