"""Fixed protected selected-page content-element producer; not a registered job."""
import time

from .competitor_fetch import _collect
from .competitor_formats import observe_static_formats


METHOD = "competitor-page-elements-collect-v1"


def collect_competitor_page_formats(*, project, actor, binding, before_request, fetcher=None, clock=time.monotonic, sleep=time.sleep):
    return _collect(project=project, actor=actor, binding=binding, before_request=before_request,
        fetcher=fetcher, clock=clock, sleep=sleep, method=METHOD, observer=observe_static_formats, page=True)
