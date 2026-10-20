"""Shared strict bounded robots policy for the two explicit static source producers."""
from urllib.parse import unquote
from urllib.robotparser import RobotFileParser

from .crawling import FetchDenied, FetchError, USER_AGENT
from .local_feedback import _text


MAX_BODY_BYTES = 128 * 1024


def strict_robots_policy(response):
    if response.status in {404, 410}:
        robots = RobotFileParser()
        robots.parse(["User-agent: *", "Disallow:"])
        return robots, "missing_http_404_or_410", 1
    if response.status != 200: raise FetchDenied("static_source_robots_denied")
    kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind != "text/plain" or type(response.body) is not bytes or not 1 <= len(response.body) <= MAX_BODY_BYTES:
        raise FetchError("static_source_robots_unknown")
    text = response.body.decode("utf-8-sig")
    _text(text, MAX_BODY_BYTES, required=True)
    directives = [(key.strip().lower(), sep, value) for key, sep, value in
        (line.split("#", 1)[0].strip().partition(":") for line in text.splitlines())]
    if (not any(key.lower() == "user-agent" and sep and value.strip() for key, sep, value in directives)
        or not any(key.lower() in {"allow", "disallow"} and sep for key, sep, value in directives)
        or any(key.strip().lower() in {"allow", "disallow"} and any(char in unquote(value) for char in "*$")
               for key, sep, value in directives)
        or any(key.lower() == "request-rate" or key.lower() == "crawl-delay" and
               (not value.strip().isdigit() or int(value.strip()) > 10) for key, sep, value in directives)):
        raise FetchError("static_source_robots_unknown")
    robots = RobotFileParser(response.url)
    robots.parse(text.splitlines())
    return robots, "available", max(1, robots.crawl_delay(USER_AGENT) or robots.crawl_delay("*") or 0)
