"""Fixed original same-URI supported references; never target or crawl authority."""
from .competitor_comparison import DESTINATIONS_INTERPRETATION as INTERPRETATION, DESTINATIONS_METHOD as METHOD, _compare_competitor_metadata


def compare_competitor_page_destinations(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id, destinations=True)
