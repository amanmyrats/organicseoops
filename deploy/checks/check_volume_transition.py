"""Read-only guard before Compose startup; refuse unresolved legacy PG volumes."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def assert_safe_transition(expected, mounts, other_volumes):
    database_mounts = [mount for mount in mounts if mount["Destination"] == "/var/lib/postgresql"]
    if database_mounts:
        if len(database_mounts) != 1 or database_mounts[0].get("Name") != expected:
            raise RuntimeError("Existing PostgreSQL uses a different data volume; follow deploy/postgres/README.md before startup")
    elif mounts or other_volumes:
        raise RuntimeError("Legacy PostgreSQL state needs reconciliation; follow deploy/postgres/README.md before startup")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ROOT / "backend/.env"))
    parser.add_argument("--project-name")
    parser.add_argument("--compose-file", action="append", default=[])
    args = parser.parse_args()
    compose = ["docker", "compose"]
    if args.project_name:
        compose += ["--project-name", args.project_name]
    if args.env_file:
        compose += ["--env-file", args.env_file]
    for path in args.compose_file:
        compose += ["-f", path]

    def output(command):
        return subprocess.check_output(command, cwd=ROOT, text=True, timeout=30).strip()

    # Resolved credentials stay in memory and are never printed.
    config = json.loads(output(compose + ["config", "--format", "json"]))
    expected = config["volumes"]["postgres-data"]["name"]
    containers = output(compose + ["ps", "-a", "-q", "postgres"]).split()
    if len(containers) > 1:
        raise RuntimeError("Multiple PostgreSQL containers require reconciliation")
    mounts = json.loads(output(["docker", "inspect", "--format", "{{json .Mounts}}", containers[0]])) if containers else []
    if containers and not mounts:
        raise RuntimeError("Existing PostgreSQL has no identifiable persistent mount")
    volumes = output(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={config['name']}",
                      "--filter", "label=com.docker.compose.volume=postgres-data"]).split()
    volumes += output(["docker", "volume", "ls", "-q", "--filter", f"name=^{config['name']}_postgres-data$"]).split()
    assert_safe_transition(expected, mounts, [name for name in volumes if name != expected])
    print("PASS: no unresolved legacy PostgreSQL volume switch")


if __name__ == "__main__":
    main()
