"""Selected-source path and result boundaries for offline Python call-syntax observations."""
import json
import re

from django.core.exceptions import ValidationError
from integrations.repository_transport import RepositoryError

OPERATION = "selected_python_call_observations"
METHOD = "repository-python-call-syntax-v1"
RULES = ["eval_call_syntax", "exec_call_syntax", "subprocess_shell_true_syntax", "pickle_load_call_syntax"]
SCOPE = "selected_python_call_syntax_only_not_execution_alias_dataflow_exploitability_or_whole_repository"


def validate_path(path):
    if (type(path) is not str or not 1 <= len(path) <= 240 or not path.endswith(".py")
        or not 1 <= len(path.split("/")) <= 6
        or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}", part) for part in path.split("/"))):
        raise ValidationError("Select one bounded relative Python .py file, at most six path segments.")


def validate_result(value, *, nonce, files):
    keys = {"method", "nonce", "status", "manifests", "scope", "rules", "coverage", "observations"}
    if (type(value) is not dict or set(value) != keys or value["method"] != METHOD or value["nonce"] != nonce
        or value["status"] != "succeeded" or value["scope"] != SCOPE or value["rules"] != RULES
        or value["manifests"] != [{"name": row["name"], "sha256": row["sha256"]} for row in files]
        or type(value["coverage"]) is not dict or type(value["observations"]) is not list or len(value["observations"]) > 100):
        raise RepositoryError("code_result_unavailable")
    coverage = value["coverage"]
    counters = {"line_count", "node_count", "observed_patterns", "retained_observations", "omitted_observations"}
    if (set(coverage) != counters | {"parse_state"}
        or type(coverage["parse_state"]) is not str or coverage["parse_state"] not in {"parsed", "source_missing", "syntax_unavailable"}
        or any(type(coverage[key]) is not int or coverage[key] < 0 for key in counters)
        or coverage["line_count"] > 131073 or coverage["node_count"] > 50000
        or coverage["observed_patterns"] > coverage["node_count"]
        or coverage["retained_observations"] != len(value["observations"])
        or coverage["retained_observations"] != min(100, coverage["observed_patterns"])
        or coverage["retained_observations"] + coverage["omitted_observations"] != coverage["observed_patterns"]
        or not files and (coverage["parse_state"] != "source_missing" or any(coverage[key] for key in counters))
        or files and coverage["parse_state"] == "source_missing"
        or coverage["parse_state"] != "parsed" and any(coverage[key] for key in counters - {"line_count"})
        or coverage["parse_state"] == "parsed" and not coverage["node_count"]):
        raise RepositoryError("code_result_unavailable")
    seen = set()
    for row in value["observations"]:
        if (type(row) is not dict or set(row) != {"rule", "line", "column"}
            or type(row["rule"]) is not str or row["rule"] not in RULES
            or type(row["line"]) is not int or not 1 <= row["line"] <= coverage["line_count"]
            or type(row["column"]) is not int or not 1 <= row["column"] <= 131073):
            raise RepositoryError("code_result_unavailable")
        identity = (row["line"], row["column"], row["rule"])
        if identity in seen:
            raise RepositoryError("code_result_unavailable")
        seen.add(identity)
    result = {key: item for key, item in value.items() if key != "nonce"}
    if len(json.dumps(result).encode()) > 30000:
        raise RepositoryError("code_output_limit")
    return result
