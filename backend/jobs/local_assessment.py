"""Review customer-supplied local facts without claiming listing/profile verification."""
from hashlib import sha256

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .models import LocalBusinessAssessment


def require_local_business_authority(*, project, actor, assessment_id, configuration_revision, origin):
    """Current independent manual business/site authority; no GBP API identity or eligibility inference."""
    from django.utils import timezone
    from integrations.oauth import _verified
    from tenancy.services import require_passive_security_scope
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None or not _verified(actor):
        raise PermissionDenied
    verification = require_passive_security_scope(project=project, user=actor, origin=origin)
    config = ProjectConfiguration.objects.filter(project=project).first()
    assessment = LocalBusinessAssessment.objects.filter(project=project, pk=assessment_id).first()
    if (not config or not assessment or configuration_revision != config.revision
        or assessment.configuration_revision != config.revision or verification.verified_at > timezone.now()
        or verification.origin != origin or not assessment.services or not assessment.business_name.strip()
        or assessment.location_label not in config.business_locations and not (not assessment.location_label and config.service_areas)
        or not set(assessment.service_areas) <= set(config.service_areas)
        or assessment.profile_url and assessment.profile_url not in config.profile_urls
        or LocalBusinessAssessment.objects.filter(project=project, location_digest=assessment.location_digest,
                                                  revision__gt=assessment.revision).exists()):
        raise PermissionDenied
    return assessment, verification


def review_local_business(*, project, actor, request_key, expected_config_revision,
                          location_label, business_name, address_display, phone, hours, services,
                          service_areas, profile_url, eligibility, review_theme, evidence_note,
                          suggested_action, expected_revision=None):
    if (type(request_key) is not str or not 8 <= len(request_key) <= 64
        or not request_key[0].isascii() or not request_key[0].isalnum()
        or any(not char.isascii() or not (char.isalnum() or char in "_-") for char in request_key)
        or type(expected_config_revision) is not int or expected_config_revision < 0
        or type(location_label) is not str or len(location_label) > 240
        or type(business_name) is not str or not 1 <= len(business_name.strip()) <= 160
        or any(type(value) is not str or len(value) > limit for value, limit in (
            (address_display, 512), (phone, 64), (hours, 500), (profile_url, 512),
            (review_theme, 240), (suggested_action, 500)))
        or type(evidence_note) is not str or not 1 <= len(evidence_note.strip()) <= 500
        or type(services) is not list or not 1 <= len(services) <= 20
        or any(type(item) is not str or not 1 <= len(item.strip()) <= 120 or item != item.strip()
               for item in services) or len(set(services)) != len(services)
        or type(service_areas) is not list or len(service_areas) > 20
        or any(type(item) is not str or not 1 <= len(item.strip()) <= 240 for item in service_areas)
        or eligibility not in LocalBusinessAssessment.Eligibility.values
        or type(expected_revision) is not int and expected_revision is not None
        or expected_revision is not None and not 1 <= expected_revision < 65535):
        raise ValidationError("Review current project facts without inventing locations, reviews or eligibility.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        config = ProjectConfiguration.objects.select_for_update().filter(project=project).first()
        if (config is None or config.revision != expected_config_revision
            or location_label not in config.business_locations and not (not location_label and config.service_areas)
            or not set(service_areas) <= set(config.service_areas)
            or profile_url and profile_url not in config.profile_urls
            or hours and config.business_hours and hours != config.business_hours
            or eligibility == LocalBusinessAssessment.Eligibility.USER_ATTESTED
               and (not profile_url or not config.local_eligibility_notes.strip())
            or review_theme and not profile_url):
            raise ValidationError("Current project location, profile and eligibility evidence is required.")
        location_digest = sha256(location_label.encode()).hexdigest()
        existing = LocalBusinessAssessment.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest = LocalBusinessAssessment.objects.filter(project=project, location_digest=location_digest).aggregate(
                value=Max("revision"))["value"]
            if (existing.actor_id != actor.pk or existing.location_digest != location_digest
                or existing.revision != latest
                or existing.revision != (expected_revision + 1 if expected_revision else 1)
                or (existing.configuration_revision, existing.business_name, existing.address_display,
                    existing.phone, existing.hours, existing.services, existing.service_areas,
                    existing.profile_url, existing.eligibility, existing.review_theme,
                    existing.evidence_note, existing.suggested_action)
                != (expected_config_revision, business_name.strip(), address_display.strip(), phone.strip(),
                    hours.strip(), services, service_areas, profile_url, eligibility, review_theme.strip(),
                    evidence_note.strip(), suggested_action.strip())):
                raise ValidationError("Local review key belongs to a different or stale decision.")
            return existing
        latest = LocalBusinessAssessment.objects.filter(project=project, location_digest=location_digest).aggregate(
            value=Max("revision"))["value"] or 0
        if expected_revision != (latest or None):
            raise ValidationError("Local assessment changed; reload before correcting it.")
        return LocalBusinessAssessment.objects.create(project=project, actor=actor,
            request_key=request_key, location_digest=location_digest, revision=latest + 1,
            configuration_revision=config.revision, location_label=location_label,
            business_name=business_name.strip(), address_display=address_display.strip(), phone=phone.strip(),
            hours=hours.strip(), services=services, service_areas=service_areas, profile_url=profile_url,
            eligibility=eligibility, review_theme=review_theme.strip(), evidence_note=evidence_note.strip(),
            suggested_action=suggested_action.strip())
