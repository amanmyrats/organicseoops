"""Fixed original two-page heading-level counts; no semantic outline or AI authority."""
from .competitor_reference_structure import HEADINGS_INTERPRETATION as INTERPRETATION, HEADINGS_METHOD as METHOD, MAX_RESULT_BYTES, _read_two_page_structure


def read_competitor_headings_structure(*, project, actor, first_job_id, second_job_id):
    return _read_two_page_structure(project=project, actor=actor, first_job_id=first_job_id, second_job_id=second_job_id, headings=True)
