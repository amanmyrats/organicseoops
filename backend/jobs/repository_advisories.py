"""Explicit OSV lookup of filtered exact declared pins; no repository source or credential is sent."""
from hashlib import sha256
import http.client
import json
import re
import ssl
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from integrations.repository_transport import RepositoryError
from integrations.search_console_transport import _reject_constant, _unique_object
from .crawling import (FetchDenied, FetchError, FetchLimitExceeded, _connection_factory, _read_body,
    _remaining, _resolve_public_addresses, _set_socket_timeout, _system_resolver)

OPERATION = "root_pinned_dependency_advisories"
LOCK_OPERATION = "root_npm_lockfile_advisories"
OPERATIONS = {OPERATION, LOCK_OPERATION}
METHOD = "osv-declared-root-pins-v1"
LOCK_METHOD = "osv-root-npm-lock-v1"
ATTEMPT = "OSV declared dependency advisory request"
MAX_QUERIES = 50
MAX_IDS = 100
NPM_PIN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?\Z")
PYPI_PIN = re.compile(r"==([0-9]+(?:\.[0-9]+){1,3}(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?)\Z")


def configuration(*, lockfile=False):
    reference = settings.REPOSITORY_ADVISORY_REVIEW_REFERENCE
    if not settings.REPOSITORY_ADVISORIES_ENABLED or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", reference):
        raise ValidationError("Reviewed OSV capability and package-disclosure policy must be configured.")
    return {"advisory_provider": "osv", "advisory_method": LOCK_METHOD if lockfile else METHOD, "advisory_review_reference": reference}


def selected_pins(dependencies):
    from .repository_analysis import NAME, SECRET
    packages, excluded = {}, 0
    for index, row in enumerate(dependencies):
        ecosystem, name, constraint = row["ecosystem"], row["name"], row["constraint"].strip()
        if not NAME.fullmatch(name) or SECRET.search(name) or SECRET.search(constraint):
            raise RepositoryError("advisory_selection_unavailable")
        match = PYPI_PIN.fullmatch(constraint) if ecosystem == "pypi" else None
        if ecosystem == "npm" and NPM_PIN.fullmatch(constraint):
            ecosystem, version = "npm", constraint
        elif ecosystem == "pypi" and match:
            ecosystem, name, version = "PyPI", re.sub(r"[-_.]+", "-", name).lower(), match[1]
        else:
            excluded += 1
            continue
        if len(version) > 80:
            excluded += 1
            continue
        packages.setdefault((ecosystem, name, version), []).append(index)
    selected = [{"ecosystem": key[0], "name": key[1], "version": key[2], "dependency_indices": indices}
        for key, indices in sorted(packages.items())]
    # shortcut: only supported exact declared pins or filtered root npm lock records; other lock formats stay unavailable.
    return selected[:MAX_QUERIES], excluded, max(0, len(selected) - MAX_QUERIES)


def _batch(queries, *, checkpoint, before_send):
    host, connection, deadline = "api.osv.dev", None, time.monotonic() + 15
    body = json.dumps({"queries": queries}, separators=(",", ":"), allow_nan=False).encode()
    if not 1 <= len(queries) <= MAX_QUERIES or len(body) > 32768:
        raise RepositoryError("advisory_input_limit")
    try:
        checkpoint()
        addresses = _resolve_public_addresses(host, 443, resolver=_system_resolver, timeout=_remaining(deadline, time.monotonic))
        checkpoint()
        connection = _connection_factory("https", addresses[0], host, 443, deadline, time.monotonic)
        connection.connect()
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        checkpoint()
        before_send()
        connection.request("POST", "/v1/querybatch", body=body, headers={"Host": host,
            "Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity",
            "Connection": "close", "User-Agent": "OrganicSEOOps-explicit-dependency-advisories"})
        _set_socket_timeout(connection, _remaining(deadline, time.monotonic))
        response = connection.getresponse()
        if response.status != 200:
            raise RepositoryError("advisory_quota_limited" if response.status == 429 else "advisory_provider_unavailable")
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise RepositoryError("advisory_response_unavailable")
        raw = _read_body(response, headers, max_bytes=524288, deadline=deadline, clock=time.monotonic, connection=connection)
        checkpoint()
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        return value, sha256(raw).hexdigest()
    except RepositoryError:
        raise
    except FetchDenied:
        raise RepositoryError("advisory_egress_denied") from None
    except (FetchError, FetchLimitExceeded, TimeoutError, OSError, ssl.SSLError, http.client.HTTPException):
        raise RepositoryError("advisory_request_unconfirmed") from None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RepositoryError("advisory_response_unavailable") from None
    finally:
        if connection is not None:
            connection.close()


def lookup(analysis, *, checkpoint, before_send):
    selected, excluded, skipped = selected_pins(analysis["dependencies"])
    rows, source_hash, remaining = [], None, MAX_IDS
    checkpoint()
    if selected:
        queries = [{"package": {"ecosystem": row["ecosystem"], "name": row["name"]}, "version": row["version"]} for row in selected]
        value, source_hash = _batch(queries, checkpoint=checkpoint, before_send=before_send)
        try:
            if type(value) is not dict or set(value) != {"results"} or type(value["results"]) is not list or len(value["results"]) != len(selected):
                raise ValueError
            for package, result in zip(selected, value["results"], strict=True):
                if type(result) is not dict or set(result) - {"vulns", "next_page_token"}:
                    raise ValueError
                vulns, token = result.get("vulns", []), result.get("next_page_token", "")
                if type(vulns) is not list or len(vulns) > 3000 or type(token) is not str or len(token) > 4096:
                    raise ValueError
                identifiers, seen = [], set()
                for advisory in vulns:
                    if (type(advisory) is not dict or set(advisory) != {"id", "modified"}
                        or type(advisory["id"]) is not str or not re.fullmatch(r"[A-Z][A-Za-z0-9._:-]{1,99}", advisory["id"])
                        or advisory["id"] in seen or type(advisory["modified"]) is not str or len(advisory["modified"]) > 40):
                        raise ValueError
                    modified = parse_datetime(advisory["modified"])
                    if modified is None or timezone.is_naive(modified):
                        raise ValueError
                    seen.add(advisory["id"])
                    if len(identifiers) < 10 and remaining:
                        identifiers.append({"id": advisory["id"], "modified": modified.isoformat()})
                        remaining -= 1
                rows.append({**package, "advisories": identifiers, "returned_count": len(vulns),
                    "complete": not token and len(identifiers) == len(vulns)})
        except (ValueError, TypeError, KeyError, OverflowError):
            raise RepositoryError("advisory_response_unavailable") from None
    incomplete = skipped > 0 or excluded > 0 or analysis["excluded_or_unsupported"] > 0 or any(not row["complete"] for row in rows)
    lockfile = analysis["method"] == "repository-root-npm-lock-v1"
    output = {"method": LOCK_METHOD if lockfile else METHOD, "provider": "osv", "queried_at": timezone.now().isoformat(), "source_sha256": source_hash,
        "state": "no_exact_pins" if not selected else "partial" if incomplete else "complete_for_queried_pins",
        "queried_packages": len(selected), "excluded_declarations": excluded, "skipped_unique_pins": skipped,
        "scope": "supported_root_npm_lock_reported_versions_not_installed_manifest_consistency_or_complete_security_assessment" if lockfile else
            "supported_exact_declared_root_pins_only_not_installed_transitive_exploitability_or_complete_security_assessment",
        "rows": rows}
    if len(json.dumps(output).encode()) > 30000:
        raise RepositoryError("advisory_output_limit")
    checkpoint()
    return output
