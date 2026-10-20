"""Original lexical content-element pairs; no rendered format or collection authority."""
from .competitor_comparison import FORMATS_INTERPRETATION as INTERPRETATION, FORMATS_METHOD as METHOD, _compare_competitor_metadata


def compare_competitor_page_formats(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id, formats=True)
