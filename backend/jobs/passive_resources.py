"""Pure lexical resource candidates; never browser behavior or network authority."""
from html.parser import HTMLParser
from urllib.parse import urlsplit


METHOD = "passive-static-resource-references-v1"
MAX_BODY_BYTES = 128 * 1024
MAX_REFERENCES = 1000
SELECTED = {"script": "src", "iframe": "src", "img": "src", "link": "href"}
RESOURCE_RELS = {"stylesheet", "preload", "modulepreload"}
EXCLUDED = {"script", "style", "template", "noscript", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "svg", "math", "plaintext"}
COUNTS = ("inspected_attributes", "http_absolute", "https_absolute", "unclassified")


class _Unavailable(Exception):
    pass


def _category(value):
    if (type(value) is not str or not 1 <= len(value) <= 1024
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value)):
        return "unclassified"
    try:
        parts = urlsplit(value)
        if parts.scheme in {"http", "https"} and parts.netloc and parts.hostname and parts.port != 0:
            return parts.scheme + "_absolute"
    except ValueError:
        pass
    return "unclassified"


class _ResourceAttributes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.counts = dict.fromkeys(COUNTS, 0)

    def handle_starttag(self, tag, attrs):
        if not self.hidden and tag in SELECTED:
            attribute = SELECTED[tag]
            names = [name for name, _value in attrs]
            if names.count(attribute) > 1 or tag == "link" and names.count("rel") > 1:
                raise _Unavailable("ambiguous_markup")
            values = dict(attrs)
            resource = tag != "link" or bool(RESOURCE_RELS & set((values.get("rel") or "").lower().split()))
            if resource and attribute in values:
                if self.counts["inspected_attributes"] >= MAX_REFERENCES:
                    raise _Unavailable("reference_limit")
                self.counts["inspected_attributes"] += 1
                self.counts[_category(values[attribute])] += 1
        if tag in EXCLUDED:
            if len(self.hidden) >= 100:
                raise _Unavailable("ambiguous_markup")
            self.hidden.append(tag)

    def handle_endtag(self, tag):
        if tag in EXCLUDED:
            if not self.hidden or self.hidden[-1] != tag:
                raise _Unavailable("ambiguous_markup")
            self.hidden.pop()

    def handle_startendtag(self, tag, attrs):
        if tag in EXCLUDED:
            # A browser does not self-close HTML script/iframe/inert containers.
            raise _Unavailable("ambiguous_markup")
        self.handle_starttag(tag, attrs)


def observe_static_resource_references(body, *, body_complete):
    result = {"method_version": METHOD, "state": "unavailable", "reason": "body_unavailable",
        "coverage": "selected_literal_static_resource_attributes_only",
        "selected_attributes": ["script/src", "iframe/src", "img/src", "link[stylesheet|preload|modulepreload]/href"],
        "excluded": "navigation_css_srcset_javascript_dynamic_media_inert_rawtext_and_foreign_descendants",
        "interpretation": "literal_reference_candidates_not_browser_requests_mixed_content_policy_or_whole_page_security",
        "counts": dict.fromkeys(COUNTS)}
    if body_complete is not True:
        result["reason"] = "body_incomplete"
        return result
    if type(body) is not bytes:
        return result
    if len(body) > MAX_BODY_BYTES:
        result["reason"] = "body_limit"
        return result
    try:
        html = body.decode("utf-8-sig")
        if any(ord(char) < 32 and char not in "\t\r\n" or ord(char) == 127 for char in html):
            raise _Unavailable("invalid_body")
        parser = _ResourceAttributes()
        parser.feed(html)
        if parser.rawdata or parser.hidden:
            raise _Unavailable("ambiguous_markup")
        parser.close()
    except UnicodeError:
        result["reason"] = "invalid_utf8"
    except _Unavailable as error:
        result["reason"] = str(error)
    except (ValueError, AssertionError, RecursionError):
        result["reason"] = "ambiguous_markup"
    else:
        result.update(state="observed", reason="", counts=parser.counts)
    return result
