"""Fixed, offline manifest inventory. Repository content is data and is never imported or executed."""
import base64
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import sys
import time
import tomllib

METHOD = "repository-root-manifests-v1"
LOCK_METHOD = "repository-root-npm-lock-v1"
CODE_METHOD = "repository-python-call-syntax-v1"
CODE_RULES = ["eval_call_syntax", "exec_call_syntax", "subprocess_shell_true_syntax", "pickle_load_call_syntax"]
FILES = {"package.json", "pyproject.toml", "requirements.txt"}
NAME = re.compile(r"(?:@[a-z0-9._-]{1,60}/)?[a-z0-9][a-z0-9._-]{0,99}\Z")
VERSION = re.compile(r"[0-9a-zA-Z.*~^<>=!|+, -]{1,80}\Z")
SECRET = re.compile(r"(?i)(?:gh[pousr]_|github_pat_|sk[-_]|akia|asia|bearer|password|secret|token|://|@.*:)")
PIN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?\Z")
PACKAGE = r"(?:@[a-z0-9._-]{1,60}/)?[a-z0-9][a-z0-9._-]{0,99}"
LOCATION = re.compile(r"node_modules/" + PACKAGE + r"(?:/node_modules/" + PACKAGE + r")*\Z")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError


def code_observations(data):
    if (set(data) != {"method", "nonce", "files"} or type(data["nonce"]) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", data["nonce"]) or type(data["files"]) is not list or len(data["files"]) > 1):
        raise ValueError
    manifests, observations, lines, nodes = [], [], 0, 0
    state = "source_missing"
    if data["files"]:
        item = data["files"][0]
        if (type(item) is not dict or set(item) != {"name", "content_b64", "sha256"} or type(item["name"]) is not str
            or len(item["name"]) > 240 or not item["name"].endswith(".py") or not 1 <= len(item["name"].split("/")) <= 6
            or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}", part) for part in item["name"].split("/"))
            or type(item["content_b64"]) is not str or len(item["content_b64"]) > 180000):
            raise ValueError
        raw = base64.b64decode(item["content_b64"], validate=True)
        if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError
        source = raw.decode("utf-8-sig", errors="strict").replace("\r\n", "\n").replace("\r", "\n")
        lines = source.count("\n") + 1 if source else 0
        manifests.append({"name": item["name"], "sha256": item["sha256"]})
        try:
            tree = ast.parse(source, filename="selected-source.py", mode="exec")
            state = "parsed"
        except (SyntaxError, ValueError, RecursionError):
            state = "syntax_unavailable"
        if state == "parsed":
            for node in ast.walk(tree):
                nodes += 1
                if nodes > 50000:
                    raise ValueError
                if not isinstance(node, ast.Call):
                    continue
                rule = None
                if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                    rule = node.func.id + "_call_syntax"
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    module, function = node.func.value.id, node.func.attr
                    if module == "subprocess" and function in {"run", "call", "check_call", "check_output", "Popen"} and any(
                        arg.arg == "shell" and isinstance(arg.value, ast.Constant) and arg.value.value is True for arg in node.keywords):
                        rule = "subprocess_shell_true_syntax"
                    elif module == "pickle" and function in {"load", "loads"}:
                        rule = "pickle_load_call_syntax"
                if rule:
                    observations.append({"rule": rule, "line": node.lineno, "column": node.col_offset + 1})
    observations.sort(key=lambda row: (row["line"], row["column"], row["rule"]))
    return {"method": CODE_METHOD, "nonce": data["nonce"], "status": "succeeded", "manifests": manifests,
        "scope": "selected_python_call_syntax_only_not_execution_alias_dataflow_exploitability_or_whole_repository", "rules": CODE_RULES,
        "coverage": {"parse_state": state, "line_count": lines, "node_count": nodes, "observed_patterns": len(observations),
            "retained_observations": min(100, len(observations)), "omitted_observations": max(0, len(observations) - 100)},
        "observations": observations[:100]}


def lock_inventory(data):
    if (set(data) != {"method", "nonce", "files"} or type(data["nonce"]) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", data["nonce"]) or type(data["files"]) is not list or len(data["files"]) > 1):
        raise ValueError
    manifests, packages, excluded, entries, version = [], set(), 0, 0, None
    supported_entries = 0
    if data["files"]:
        item = data["files"][0]
        if (type(item) is not dict or set(item) != {"name", "content_b64", "sha256"} or item["name"] != "package-lock.json"
            or type(item["content_b64"]) is not str or len(item["content_b64"]) > 700000):
            raise ValueError
        raw = base64.b64decode(item["content_b64"], validate=True)
        if len(raw) > 524288 or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_object, parse_constant=reject_constant)
        if (type(value) is not dict or type(value.get("lockfileVersion")) is not int or value["lockfileVersion"] not in {2, 3}
            or type(value.get("packages")) is not dict or len(value["packages"]) > 5001):
            raise ValueError
        version = value["lockfileVersion"]
        for location, entry in value["packages"].items():
            if location == "":
                if type(entry) is not dict:
                    raise ValueError
                continue
            entries += 1
            if entries > 5000:
                raise ValueError
            if (len(location) > 1024 or not LOCATION.fullmatch(location) or SECRET.search(location) or type(entry) is not dict):
                excluded += 1
                continue
            name = location.rsplit("/node_modules/", 1)[-1]
            if name.startswith("node_modules/"):
                name = name[len("node_modules/"):]
            pin = entry.get("version")
            # Ambiguous aliases/private/git/workspace/bundled records are gaps, never guessed public package identities.
            if (entry.get("link", False) is not False or entry.get("inBundle", False) is not False
                or entry.get("name", name) != name or type(pin) is not str or len(pin) > 80
                or not PIN.fullmatch(pin) or SECRET.search(pin)
                or entry.get("resolved") != f"https://registry.npmjs.org/{name}/-/{name.rsplit('/', 1)[-1]}-{pin}.tgz"):
                excluded += 1
                continue
            supported_entries += 1
            packages.add((name, pin))
        manifests.append({"name": item["name"], "sha256": item["sha256"]})
    retained = sorted(packages)[:50]
    omitted = len(packages) - len(retained)
    return {"method": LOCK_METHOD, "nonce": data["nonce"], "status": "succeeded", "manifests": manifests,
        "dependencies": [{"manifest": "package-lock.json", "ecosystem": "npm", "group": "lockfile.packages", "name": name, "constraint": pin} for name, pin in retained],
        "excluded_or_unsupported": excluded + omitted + int(not manifests),
        "scope": "root_npm_lockfile_reported_packages_not_installed_manifest_consistency_or_whole_repository",
        "lockfile": {"status": "missing" if not manifests else "partial" if excluded or omitted else "parsed",
            "version": version, "package_entries": entries, "supported_entries": supported_entries,
            "retained_unique_packages": len(retained), "excluded_entries": excluded, "omitted_unique_packages": omitted}}


def inventory(data):
    if type(data) is dict and data.get("method") == CODE_METHOD:
        return code_observations(data)
    if type(data) is dict and data.get("method") == LOCK_METHOD:
        return lock_inventory(data)
    if (type(data) is not dict or set(data) != {"method", "nonce", "files"} or data["method"] != METHOD
        or type(data["nonce"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", data["nonce"])
        or type(data["files"]) is not list or len(data["files"]) > 3):
        raise ValueError
    manifests, rows, excluded, seen = [], [], 0, set()
    for item in data["files"]:
        if (type(item) is not dict or set(item) != {"name", "content_b64", "sha256"} or item["name"] not in FILES
            or item["name"] in seen or type(item["content_b64"]) is not str or len(item["content_b64"]) > 180000):
            raise ValueError
        seen.add(item["name"])
        raw = base64.b64decode(item["content_b64"], validate=True)
        if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError
        source = raw.decode("utf-8", errors="strict")
        candidates = []
        if item["name"] == "package.json":
            value = json.loads(source, object_pairs_hook=unique_object, parse_constant=reject_constant)
            if type(value) is not dict:
                raise ValueError
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                group = value.get(key, {})
                if type(group) is not dict or len(group) > 500:
                    raise ValueError
                candidates.extend(("npm", key, name, version) for name, version in group.items())
        elif item["name"] == "pyproject.toml":
            value = tomllib.loads(source)
            project = value.get("project", {})
            if type(project) is not dict:
                raise ValueError
            dependencies = project.get("dependencies", [])
            if "project" not in value or "dependencies" in project.get("dynamic", []):
                excluded += 1
            if type(project) is not dict or type(dependencies) is not list or len(dependencies) > 500:
                raise ValueError
            candidates.extend(("pypi", "project.dependencies", None, line) for line in dependencies)
        else:
            lines = source.splitlines()
            if len(lines) > 1000:
                raise ValueError
            candidates.extend(("pypi", "requirements", None, line.strip()) for line in lines if line.strip() and not line.lstrip().startswith("#"))
        for ecosystem, group, name, version in candidates:
            if name is None and type(version) is str:
                match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]{0,99})\s*([<>=!~][0-9A-Za-z.*<>=!~, -]+)?", version)
                if match:
                    name, version = match[1].lower(), match[2] or "unspecified"
            if (type(name) is not str or type(version) is not str or not NAME.fullmatch(name)
                or not VERSION.fullmatch(version) or SECRET.search(name) or SECRET.search(version)):
                excluded += 1
                continue
            if len(rows) >= 100:
                raise ValueError  # Reject overflow rather than silently implying a complete inventory.
            rows.append({"manifest": item["name"], "ecosystem": ecosystem, "group": group, "name": name, "constraint": version})
        manifests.append({"name": item["name"], "sha256": item["sha256"]})
    return {"method": METHOD, "nonce": data["nonce"], "status": "succeeded", "manifests": manifests,
        "dependencies": rows, "excluded_or_unsupported": excluded,
        "scope": "root_declared_dependencies_only_not_installed_versions_vulnerabilities_or_whole_repository"}


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    signal.alarm(20)
    path, deadline = Path("/tmp/request.json"), time.monotonic() + 10
    ready = Path("/tmp/request.ready")
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(.05)
    marker = os.stat(ready, follow_symlinks=False)
    if not stat.S_ISREG(marker.st_mode) or marker.st_size != 0:
        raise ValueError
    ready.unlink()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= 750000:
            raise ValueError
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            raw = source.read(750001)
        path.unlink()
        result = inventory(json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant))
        encoded = json.dumps(result, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > 32768:
            raise ValueError
        print(encoded, flush=True)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"status":"failed","error_category":"manifest_input_unavailable"}', flush=True)
        sys.exit(1)
