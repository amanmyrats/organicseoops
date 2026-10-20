"""Original literal element counts in two saved pages; no site or format inference."""
from .competitor_reference_structure import FORMATS_METHOD as METHOD, FORMATS_INTERPRETATION as INTERPRETATION, MAX_RESULT_BYTES, _read_two_page_structure


def read_competitor_formats_structure(*, project, actor, first_job_id, second_job_id):
    return _read_two_page_structure(project=project, actor=actor, first_job_id=first_job_id, second_job_id=second_job_id, formats=True)
