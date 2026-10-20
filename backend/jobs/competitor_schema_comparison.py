"""Fixed read-only original root lexical schema labels; no validity or collection authority."""
from .competitor_comparison import SCHEMA_INTERPRETATION as INTERPRETATION, SCHEMA_METHOD as METHOD, _compare_competitor_metadata


def compare_competitor_schema_roots(*, project, actor, previous_job_id, current_job_id):
    return _compare_competitor_metadata(project=project, actor=actor,
        previous_job_id=previous_job_id, current_job_id=current_job_id, schema=True)
