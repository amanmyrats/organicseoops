"""D150 offline publication-policy parser. This never grants request authority."""
from hashlib import sha256
import json
import os
import re
import stat

VERSION = "public-analytics-policy-v1"
MAX_BYTES = 16 * 1024
ERROR = "invalid_public_analytics_policy"


def load_public_analytics_policy():
    """Read trusted deployment configuration afresh, never browser-supplied authority."""
    from django.conf import settings
    path = getattr(settings, "PUBLIC_ANALYTICS_POLICY_FILE", "")
    pin = getattr(settings, "PUBLIC_ANALYTICS_POLICY_SHA256", "")
    if (getattr(settings, "PUBLIC_ANALYTICS_ENABLED", False) is not True
        or type(path) is not str or not path.startswith("/")
        or type(pin) is not str or not re.fullmatch(r"[0-9a-f]{64}", pin)):
        raise ValueError(ERROR)
    try:
        # Nonblocking/no-follow keeps a misconfigured FIFO or symlink from becoming an intake hang.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as artifact:
            metadata = os.fstat(artifact.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= MAX_BYTES:
                raise ValueError(ERROR)
            content = artifact.read(MAX_BYTES + 1)
        policy, digest = parse_public_analytics_policy(content)
        if digest != pin or policy["origin"] != settings.FRONTEND_ORIGIN:
            raise ValueError(ERROR)
        return content, digest
    except (OSError, ValueError):
        raise ValueError(ERROR) from None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(ERROR)
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError(ERROR)


def parse_public_analytics_policy(content):
    """Return normalized checked schema and SHA; caller must trust/pin the build artifact."""
    if type(content) is not bytes or not content or len(content) > MAX_BYTES:
        raise ValueError(ERROR)
    try:
        policy = json.loads(content.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite)
        if (type(policy) is not dict or set(policy) != {"version", "origin", "routes"}
            or policy["version"] != VERSION or type(policy["origin"]) is not str
            or len(policy["origin"]) > 253 or not re.fullmatch(
                r"https://[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)+", policy["origin"])
            or type(policy["routes"]) is not list or not 2 <= len(policy["routes"]) <= 64):
            raise ValueError(ERROR)
        rows, paths, identities, cta_owners = [], set(), set(), {}
        for row in policy["routes"]:
            if (type(row) is not dict or set(row) != {"path", "id", "locale", "cta_ids", "html_sha256"}
                or type(row["path"]) is not str or len(row["path"]) > 128
                or (row["path"] not in {"", "tr/"} and not re.fullmatch(r"[a-z0-9-]+(?:/[a-z0-9-]+)*", row["path"]))
                or re.match(r"(?:tr/)?(?:account|app|preview|404)(?:/|$)", row["path"])
                or row["path"] == "tr"
                or type(row["id"]) is not str or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", row["id"])
                or type(row["locale"]) is not str or row["locale"] not in {"en", "tr"}
                or (row["locale"] == "tr") != row["path"].startswith("tr/")
                or type(row["html_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", row["html_sha256"])
                or type(row["cta_ids"]) is not list or len(row["cta_ids"]) > 16
                or any(type(cta) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", cta) for cta in row["cta_ids"])):
                raise ValueError(ERROR)
            identity = (row["id"], row["locale"])
            if row["path"] in paths or identity in identities or len(set(row["cta_ids"])) != len(row["cta_ids"]):
                raise ValueError(ERROR)
            paths.add(row["path"])
            identities.add(identity)
            for cta in row["cta_ids"]:
                if cta in cta_owners and cta_owners[cta] != row["id"]:
                    raise ValueError(ERROR)
                cta_owners[cta] = row["id"]
            rows.append({**row, "cta_ids": sorted(row["cta_ids"])})
        for row in rows:
            equivalent = next((other for other in rows if other["id"] == row["id"] and other["locale"] != row["locale"]), None)
            if equivalent is None or equivalent["cta_ids"] != row["cta_ids"]:
                raise ValueError(ERROR)
        normalized = {"version": VERSION, "origin": policy["origin"], "routes": sorted(rows, key=lambda row: row["path"])}
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return normalized, sha256(encoded).hexdigest()
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise ValueError(ERROR) from None
