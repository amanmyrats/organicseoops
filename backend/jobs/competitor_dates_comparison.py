"""Original literal date declarations; no validated dates or collection authority."""
from .competitor_comparison import DATES_INTERPRETATION as INTERPRETATION, DATES_METHOD as METHOD, _compare_competitor_metadata


def compare_competitor_page_dates(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id, dates=True)
