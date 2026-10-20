"""Pure minimized header observations; callers supply separately authorized transport evidence."""
import re
from http.cookies import CookieError, SimpleCookie

from django.core.exceptions import ValidationError


METHOD = "passive-response-headers-v1"
MAX_FIELDS = 100
MAX_BYTES = 32 * 1024
SELECTED_HEADERS = ("strict-transport-security", "content-security-policy", "content-security-policy-report-only",
    "x-frame-options", "x-content-type-options", "referrer-policy", "server", "x-powered-by")
TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
COOKIE_VALUE = re.compile(r'([\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]*|"[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]*")')


def _cookie_flags(value):
    parts = value.split(";")
    name, separator, raw_value = parts[0].strip().partition("=")
    if not separator or not TOKEN.fullmatch(name) or not COOKIE_VALUE.fullmatch(raw_value): return None
    attributes = set()
    for part in parts[1:]:
        if not part.strip(): continue
        key, equals, _ = part.strip().partition("=")
        key = key.lower()
        if not TOKEN.fullmatch(key) or key in attributes or key in {"secure", "httponly", "partitioned"} and equals:
            return None
        attributes.add(key)
    # ponytail: unsupported cookie syntax stays unclassified; extend only with an evidenced syntax contract.
    parsed = SimpleCookie()
    try: parsed.load(value)
    except CookieError: return None
    if len(parsed) != 1 or name not in parsed: return None
    cookie = parsed[name]
    return {"without_secure": not bool(cookie["secure"]), "without_httponly": not bool(cookie["httponly"]),
            "without_recognized_samesite": cookie["samesite"].lower() not in {"lax", "strict", "none"}}


def observe_response_headers(fields):
    """Never accept a collapsed dict or turn unavailable metadata into absence/zero."""
    result = {"method_version": METHOD, "coverage": "one_complete_original_response_header_sequence_only",
        "interpretation": "header_presence_and_explicit_cookie_flags_not_policy_effectiveness_browser_acceptance_or_exploitability",
        "state": "unavailable" if fields is None else "observed", "headers": None, "cookies": None}
    if fields is None: return result
    if type(fields) not in {list, tuple} or len(fields) > MAX_FIELDS:
        raise ValidationError("Complete bounded response header fields are required.")
    selected = {key: [] for key in SELECTED_HEADERS}
    cookies = {"observed_fields": 0, "parsed_fields": 0, "unclassified_fields": 0,
               "without_secure": 0, "without_httponly": 0, "without_recognized_samesite": 0}
    size = 0
    for field in fields:
        if (type(field) not in {list, tuple} or len(field) != 2 or any(type(value) is not str for value in field)
            or len(field[0]) > 200 or len(field[1]) > 8192 or not TOKEN.fullmatch(field[0])
            or any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in field[1])):
            raise ValidationError("Original response header syntax is unavailable.")
        name, value = field[0].lower(), field[1].strip(" \t")
        try: size += len(field[0].encode("ascii")) + len(field[1].encode("latin-1")) + 4
        except UnicodeError: raise ValidationError("Original response header encoding is unavailable.") from None
        if size > MAX_BYTES: raise ValidationError("Original response header size is unavailable.")
        if name in selected: selected[name].append(bool(value))
        if name == "set-cookie":
            cookies["observed_fields"] += 1
            flags = _cookie_flags(value)
            if flags is None: cookies["unclassified_fields"] += 1
            else:
                cookies["parsed_fields"] += 1
                for key, missing in flags.items(): cookies[key] += int(missing)
    result["headers"] = {key: "absent" if not values else "multiple_fields" if len(values) > 1
        else "present_nonempty" if values[0] else "present_empty" for key, values in selected.items()}
    result["cookies"] = cookies
    return result
