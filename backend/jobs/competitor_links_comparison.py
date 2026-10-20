"""Fixed read-only original root href categories; no destinations or collection authority."""
from .competitor_comparison import LINKS_INTERPRETATION as INTERPRETATION, LINKS_METHOD as METHOD, _compare_competitor_metadata


def compare_competitor_links_roots(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id, links=True)
