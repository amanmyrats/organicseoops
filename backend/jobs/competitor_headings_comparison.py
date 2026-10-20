"""Fixed original same-URI literal heading text/order, never semantic or collection authority."""
from .competitor_comparison import HEADINGS_INTERPRETATION as INTERPRETATION, HEADINGS_METHOD as METHOD, _compare_competitor_metadata


def compare_competitor_page_headings(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id, headings=True)
