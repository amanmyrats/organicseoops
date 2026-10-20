"""Read-only acceptance checks for the already-started local Compose stack."""
import argparse
import json
from pathlib import Path
import subprocess
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ROOT / "backend/.env"), help="Private backend environment file; values are never printed")
    args = parser.parse_args()
    compose = ["docker", "compose"]
    if args.env_file:
        compose += ["--env-file", args.env_file]

    def run(command):
        return subprocess.check_output(command, cwd=ROOT, text=True, timeout=60)

    ids = run(compose + ["ps", "-q"]).split()
    assert len(ids) == 10, "Expected ten running services"
    containers = json.loads(run(["docker", "inspect", *ids]))
    services = {c["Config"]["Labels"]["com.docker.compose.service"]: c for c in containers}
    assert set(services) == {"api", "proxy", "postgres", "redis", "beat",
                             "worker-default", "worker-ai", "worker-crawl", "worker-audit", "renderer"}
    backend_image = services["api"]["Image"]
    for name, container in services.items():
        assert container["State"]["Running"], name
        if name != "beat":
            assert container["State"]["Health"]["Status"] == "healthy", name
        ports = container["HostConfig"].get("PortBindings") or {}
        if name == "proxy":
            assert set(ports) == {"80/tcp"} and len(ports["80/tcp"]) == 1
            binding = ports["80/tcp"][0]
            assert binding["HostIp"] == "127.0.0.1"
            proxy_port = int(binding["HostPort"])
            assert 1 <= proxy_port <= 65535
        else:
            assert not ports, f"Unexpected host port: {name}"
        if name not in {"proxy", "postgres", "redis", "renderer"}:
            assert container["Image"] == backend_image, name
            assert container["Config"]["User"] == "10001:10001", name
            assert container["HostConfig"]["ReadonlyRootfs"], name
            artifact_mounts = [mount for mount in container["Mounts"]
                               if mount["Destination"] == "/var/lib/organicseoops/artifacts"]
            assert len(artifact_mounts) == 1 and artifact_mounts[0]["Type"] == "volume", name
    renderer = services["renderer"]
    assert renderer["Config"]["User"] == "10001:10001"
    assert renderer["HostConfig"]["NetworkMode"] == "none"
    assert renderer["HostConfig"]["ReadonlyRootfs"]
    renderer_env = {item.split("=", 1)[0] for item in renderer["Config"]["Env"]}
    assert renderer_env.isdisjoint({"DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "CELERY_BROKER_URL",
                                    "ARTIFACT_S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"})
    renderer_mounts = {mount["Destination"] for mount in renderer["Mounts"]}
    assert renderer_mounts == {"/var/lib/organicseoops/render-requests", "/var/lib/organicseoops/render-results"}
    for name in ("postgres", "redis"):
        networks = services[name]["NetworkSettings"]["Networks"]
        assert len(networks) == 1, name
        network = json.loads(run(["docker", "network", "inspect", next(iter(networks))]))[0]
        assert network["Internal"], name
        assert any(mount["Type"] == "volume" for mount in services[name]["Mounts"]), name
    assert "beat" in services["beat"]["Config"]["Cmd"]
    assert services["postgres"]["Config"]["User"] == "70:70"
    for name in ("worker-default", "worker-ai", "worker-crawl", "worker-audit"):
        command = services[name]["Config"]["Cmd"]
        assert "worker" in command and "--queues=" + name.removeprefix("worker-") in command
        assert "-B" not in command and "beat" not in command

    image = json.loads(run(["docker", "image", "inspect", backend_image]))[0]
    baked_env = dict(item.split("=", 1) for item in image["Config"]["Env"])
    assert "DJANGO_SECRET_KEY" not in baked_env and "POSTGRES_PASSWORD" not in baked_env
    history = run(["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", backend_image])
    runtime_env = dict(item.split("=", 1) for item in services["api"]["Config"]["Env"])
    for key in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD"):
        assert runtime_env[key] not in history, "Runtime secret found in image history"

    runtime = json.loads(run(compose + ["exec", "-T", "api", "python", "-c", """
import json, os, platform
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from packaging.requirements import Requirement
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.files.storage import storages
from django.conf import settings
from django.db import connection
from redis import Redis
from config.celery import app
assert os.getuid() == 10001
assert not Path('/app/.env').exists() and not Path('/app/.venv').exists()
assert not list(Path('/app').rglob('.env*'))
assert platform.python_version() == '3.13.15'
assert find_spec('pip') is None and find_spec('ensurepip') is None
for line in Path('/app/requirements.txt').read_text().splitlines():
    if line and not line.startswith('#'):
        requirement = Requirement(line)
        assert version(requirement.name) in requirement.specifier, requirement.name
assert connection.pg_version == 180006
artifact_storage = storages['artifacts']
assert artifact_storage.__class__.__name__ == 'FileSystemStorage'
assert Path(artifact_storage.location).stat().st_uid == 10001
assert Path(artifact_storage.location).stat().st_mode & 0o777 == 0o700
assert settings.ARTIFACT_MAX_BYTES == 10485760
with connection.cursor() as cursor:
    cursor.execute("SELECT datlocprovider, datlocale, pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database()")
    assert cursor.fetchone() == ('b', 'C.UTF-8', 'UTF8')
redis = Redis.from_url(os.environ['CELERY_BROKER_URL'], socket_timeout=5, socket_connect_timeout=5)
assert redis.ping()
assert redis.info('server')['redis_version'] == '8.10.2'
assert redis.config_get('appendonly')['appendonly'] == 'yes'
assert redis.config_get('maxmemory-policy')['maxmemory-policy'] == 'noeviction'
inspector = app.control.inspect(timeout=5)
replies = inspector.ping()
assert replies and len(replies) == 4 and all(reply == {'ok': 'pong'} for reply in replies.values())
queues = inspector.active_queues()
assert queues and len(queues) == 4 and all(len(value) == 1 for value in queues.values())
assert {value[0]['name'] for value in queues.values()} == {'default', 'ai', 'crawl', 'audit'}
print(json.dumps({'python': platform.python_version(), 'postgres': connection.pg_version, 'debug': settings.DEBUG,
    'redis': redis.info('server')['redis_version'], 'workers': len(replies), 'login_url': settings.LOGIN_URL,
    'static_url': staticfiles_storage.url('admin/css/base.css', force=True)}))
"""]))
    artifact_key = run(compose + ["exec", "-T", "api", "python", "-c", """
from config.artifacts import save_private_artifact
print(save_private_artifact(scope='checks', content=b'{\"ok\":true}', content_type='application/json'))
"""]).strip()
    assert artifact_key.startswith("checks/") and artifact_key.endswith(".json")
    run(compose + ["exec", "-T", "worker-default", "python", "-c", f"""
from config.artifacts import read_private_artifact
assert read_private_artifact({artifact_key!r}) == b'{{\"ok\":true}}'
"""])
    run(compose + ["exec", "-T", "api", "python", "-c", f"""
import config
from django.core.files.storage import storages
storages['artifacts'].delete({artifact_key!r})
assert not storages['artifacts'].exists({artifact_key!r})
"""])
    run(compose + ["exec", "-T", "beat", "python", "-c", """
import os
from pathlib import Path
assert os.getuid() == 10001
directory = Path('/var/lib/celery')
assert directory.stat().st_uid == 10001 and os.access(directory, os.W_OK)
assert list(directory.glob('celerybeat-schedule*'))
"""])
    run(compose + ["exec", "-T", "proxy", "nginx", "-t"])
    run(compose + ["exec", "-T", "postgres", "sh", "-ec", 'test "$(id -u)" = 70; test ! -e /usr/local/bin/gosu'])
    origin = f"http://127.0.0.1:{proxy_port}"
    request_id = "smoke-request-123"
    with urlopen(Request(origin + "/api/health/", headers={"X-Request-ID": request_id}), timeout=10) as response:
        assert json.load(response) == {"status": "ok"}
        assert "no-store" in response.headers["Cache-Control"]
        assert response.headers["X-Request-ID"] == request_id
    secret_marker = "P0106_RUNTIME_LOG_SECRET"
    secret_request_id = "smoke-secret-request"
    secret_request = Request(
        origin + f"/{secret_marker}/?access_token={secret_marker}&X-Amz-Signature={secret_marker}",
        headers={"Cookie": f"sessionid={secret_marker}", "X-Request-ID": secret_request_id},
    )
    try:
        urlopen(secret_request, timeout=10)
    except HTTPError as error:
        assert error.code == 404
        error.close()
    else:
        raise AssertionError("Private log probe path must not exist")
    log_lines = subprocess.check_output(
        ["docker", "logs", services["api"]["Id"]], text=True, stderr=subprocess.STDOUT, timeout=60,
    ).splitlines()
    assert secret_marker not in "\n".join(log_lines)
    proxy_logs = subprocess.check_output(
        ["docker", "logs", services["proxy"]["Id"]], text=True, stderr=subprocess.STDOUT, timeout=60,
    )
    assert secret_marker not in proxy_logs
    request_logs = [json.loads(line) for line in log_lines if line.startswith("{")]
    assert any(item.get("request_id") == request_id and item.get("event") == "request.complete"
               and "path" not in item for item in request_logs)
    secret_logs = [line for line in log_lines if secret_request_id in line]
    assert secret_logs and all(line.startswith("{") for line in secret_logs)
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, request, file_pointer, code, message, headers, new_url):
            return None

    try:
        build_opener(NoRedirect).open(origin + "/admin/login/", timeout=10)
    except HTTPError as error:
        location = error.headers["Location"]
        assert error.code == 302 and location.startswith(runtime["login_url"] + "?")
        assert parse_qs(urlsplit(location).query) == {"next": ["/admin/login/"]}
        error.close()
    else:
        raise AssertionError("Admin login must redirect to the configured frontend login")
    with urlopen(origin + runtime["static_url"], timeout=10) as response:
        assert response.status == 200 and response.read()
        expected_cache = "max-age=0" if runtime["debug"] else "immutable"
        assert expected_cache in response.headers["Cache-Control"]
    try:
        urlopen(origin + "/static/not-present.css", timeout=10)
    except HTTPError as error:
        assert error.code == 404
        error.close()
    else:
        raise AssertionError("Missing asset must return 404")
    print("PASS: ten services; isolated renderer; private DB/Redis/artifacts; nonroot shared image; no baked credentials;")
    print("      JSON request correlation; four worker queues; singleton Beat; proxy health/admin redirect/static/404")
    print(f"Runtimes: Python {runtime['python']}; PostgreSQL {runtime['postgres']}; Redis {runtime['redis']}")


if __name__ == "__main__":
    main()
