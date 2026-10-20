"""Current literal differences between two original observations of one selected URI."""
from .competitor_comparison import (
    PAGE_INTERPRETATION as INTERPRETATION,
    PAGE_METHOD as METHOD,
    _compare_competitor_metadata,
)


def compare_competitor_pages(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id, page=True)
