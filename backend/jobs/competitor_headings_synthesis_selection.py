"""Fixed original heading-pair model preparation; no key, reservation or provider call."""
from . import competitor_headings_synthesis as source, competitor_synthesis_job as original


METHOD = "competitor-heading-synthesis-v1"


def selection_snapshot(project, actor, data):
    return original._selection_snapshot(project, actor, data, handler=source.HANDLER,
        source_reader=source.read_competitor_headings_synthesis_source, method=METHOD, source_method=source.METHOD,
        instructions=source.INSTRUCTIONS, output_schema=source.OUTPUT_SCHEMA)
