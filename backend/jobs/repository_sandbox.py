"""Rootless Engine control; no host mount or platform access credential is injected into the sandbox."""
from io import BytesIO
import http.client
import json
import os
import re
import socket
import stat
import tarfile
import time

from django.conf import settings
from integrations.repository_transport import RepositoryError
from integrations.search_console_transport import _reject_constant, _unique_object

MEMORY = 268435456
TMPFS = "rw,noexec,nosuid,nodev,size=67108864"
LABEL = "organicseoops.repository-job"


class CleanupPending(RepositoryError):
    def __init__(self):
        super().__init__("sandbox_cleanup_pending")


class Engine:
    def __init__(self, *, image, controller_id):
        if (not settings.REPOSITORY_CONTROLLER_HOST or settings.PRODUCTION_APP_HOST or settings.FEEDBACK_WORKER_HOST
            or controller_id != settings.REPOSITORY_CONTROLLER_ID
            or not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", image)):
            raise RepositoryError("isolated_controller_unavailable")
        self.path = settings.REPOSITORY_DOCKER_SOCKET
        metadata = os.stat(self.path, follow_symlinks=False)
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o007:
            raise RepositoryError("rootless_socket_unavailable")
        self.image = image
        version = self.json("GET", "/version", unversioned=True)
        try:
            supported = lambda value: tuple(int(part) for part in value.split("."))
            if not supported(version["MinAPIVersion"]) <= (1, 47) <= supported(version["ApiVersion"]):
                raise ValueError
        except (TypeError, ValueError, KeyError):
            raise RepositoryError("engine_version_unavailable") from None
        info = self.json("GET", "/info")
        if ("name=rootless" not in info.get("SecurityOptions", []) or info.get("CgroupVersion") != "2"
            or not all(info.get(key) is True for key in ("MemoryLimit", "PidsLimit", "CpuCfsQuota"))):
            raise RepositoryError("rootless_limits_unavailable")

    def call(self, method, path, *, payload=None, raw=None, statuses=(200,), limit=131072, unversioned=False):
        connection = http.client.HTTPConnection("localhost", timeout=3)
        descriptor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        descriptor.settimeout(3)
        connection.sock = descriptor
        try:
            descriptor.connect(self.path)
            body = raw if raw is not None else json.dumps(payload, allow_nan=False).encode() if payload is not None else None
            connection.request(method, ("" if unversioned else "/v1.47") + path, body=body,
                headers={"Content-Type": "application/x-tar" if raw is not None else "application/json", "Connection": "close"})
            response = connection.getresponse()
            content = response.read(limit + 1)
            if response.status not in statuses or len(content) > limit:
                raise RepositoryError("sandbox_engine_unavailable")
            return response.status, content
        except (OSError, TimeoutError, http.client.HTTPException):
            raise RepositoryError("sandbox_engine_unavailable") from None
        finally:
            connection.close()

    def json(self, method, path, *, payload=None, statuses=(200,), unversioned=False):
        _status, raw = self.call(method, path, payload=payload, statuses=statuses, unversioned=unversioned)
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(value) is not dict:
                raise ValueError
            return value
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise RepositoryError("sandbox_engine_unavailable") from None

    def inspect(self, name, label):
        if not re.fullmatch(r"seoops-repo-[1-9][0-9]*-[0-9a-f]{32}", name):
            raise RepositoryError("sandbox_identity_unavailable")
        status, raw = self.call("GET", f"/containers/{name}/json", statuses=(200, 404))
        if status == 404:
            return None
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if value["Config"]["Labels"].get(LABEL) != label or value["Config"]["Image"] != self.image:
                raise ValueError
            return value
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            raise RepositoryError("sandbox_identity_unavailable") from None

    def remove(self, name, label):
        try:
            if self.inspect(name, label) is None:
                return
            self.call("DELETE", f"/containers/{name}?force=1&v=1", statuses=(204, 404))
            if self.inspect(name, label) is not None:
                raise CleanupPending()
        except RepositoryError:
            raise CleanupPending() from None

    def run(self, *, name, label, request, checkpoint):
        checkpoint()
        # Never adopt an existing container as a fresh attempt, including after an uncertain create response.
        if self.inspect(name, label) is not None:
            raise RepositoryError("sandbox_attempt_already_exists")
        host = {"NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"], "PidsLimit": 32, "Memory": MEMORY, "MemorySwap": MEMORY,
            "NanoCpus": 1000000000, "Tmpfs": {"/tmp": TMPFS}, "AutoRemove": False,
            "LogConfig": {"Type": "local", "Config": {"max-size": "64k", "max-file": "1"}},
            "Ulimits": [{"Name": key, "Soft": value, "Hard": value} for key, value in (("nofile", 64), ("nproc", 32), ("fsize", 65536), ("core", 0))]}
        payload = {"Image": self.image, "User": "10001:10001", "WorkingDir": "/tmp", "NetworkDisabled": True,
            "Cmd": ["python", "-I", "/app/analyze.py"], "Entrypoint": [], "Labels": {LABEL: label},
            "Env": ["PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1", "HOME=/tmp"],
            "HostConfig": host}
        encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode()
        input_limit = 750000 if request.get("method") == "repository-root-npm-lock-v1" else 600000
        if not 1 <= len(encoded) <= input_limit:
            raise RepositoryError("sandbox_input_limit")
        try:
            checkpoint()
            self.json("POST", f"/containers/create?name={name}", payload=payload, statuses=(201,))
            observed = self.inspect(name, label)
            if observed is None:
                raise RepositoryError("sandbox_create_unconfirmed")
            config, actual = observed["Config"], observed["HostConfig"]
            if (config.get("User") != "10001:10001" or config.get("Cmd") != payload["Cmd"]
                or config.get("NetworkDisabled") is not True or config.get("WorkingDir") != "/tmp"
                or any(actual.get(key) != host[key] for key in ("NetworkMode", "ReadonlyRootfs", "CapDrop", "PidsLimit", "Memory", "MemorySwap", "NanoCpus", "Tmpfs"))
                or sorted(actual.get("Ulimits") or [], key=lambda row: row["Name"]) != sorted(host["Ulimits"], key=lambda row: row["Name"])
                or not any(value in {"no-new-privileges", "no-new-privileges:true"} for value in actual.get("SecurityOpt", []))
                or any(mount.get("Type") != "tmpfs" or mount.get("Destination") != "/tmp" for mount in observed.get("Mounts", []))
                or actual.get("Privileged") or actual.get("Binds") or actual.get("Devices")):
                raise RepositoryError("sandbox_limits_changed")
            checkpoint()
            self.call("POST", f"/containers/{name}/start", statuses=(204,))
            archive = BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as bundle:
                item = tarfile.TarInfo("request.json")
                item.size, item.mode, item.uid, item.gid = len(encoded), 0o400, 10001, 10001
                bundle.addfile(item, BytesIO(encoded))
                ready = tarfile.TarInfo("request.ready")
                ready.size, ready.mode, ready.uid, ready.gid = 0, 0o400, 10001, 10001
                bundle.addfile(ready, BytesIO())
            checkpoint()
            self.call("PUT", f"/containers/{name}/archive?path=/tmp&noOverwriteDirNonDir=1", raw=archive.getvalue(), statuses=(200,))
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                checkpoint()
                current = self.inspect(name, label)
                if current is None:
                    raise RepositoryError("sandbox_result_unavailable")
                state = current["State"]
                if not state.get("Running"):
                    if state.get("ExitCode") != 0 or state.get("OOMKilled"):
                        raise RepositoryError("sandbox_analysis_failed")
                    break
                time.sleep(.25)
            else:
                raise RepositoryError("sandbox_deadline")
            _status, logs = self.call("GET", f"/containers/{name}/logs?stdout=1&stderr=0&timestamps=0", limit=65536)
            frames, position = [], 0
            while position < len(logs):
                header = logs[position:position + 8]
                if len(header) != 8 or header[:4] != b"\x01\x00\x00\x00":
                    raise RepositoryError("sandbox_result_unavailable")
                size = int.from_bytes(header[4:], "big")
                position += 8
                if position + size > len(logs):
                    raise RepositoryError("sandbox_result_unavailable")
                frames.append(logs[position:position + size])
                position += size
            raw = b"".join(frames)
            if len(raw) > 32768:
                raise RepositoryError("sandbox_output_limit")
            try:
                result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise RepositoryError("sandbox_result_unavailable") from None
            checkpoint()
            return result
        finally:
            self.remove(name, label)
