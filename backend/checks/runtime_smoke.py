"""Exercise the installed WSGI server locally; requires env/DB and collectstatic."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BACKEND = Path(__file__).resolve().parents[1]


def main():
    env = {**os.environ, "DJANGO_DEBUG": "0"}
    with socket.socket() as listener, tempfile.TemporaryFile(mode="w+") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", f"--bind=fd://{listener.fileno()}",
             "--workers=1", "config.wsgi:application"],
            cwd=BACKEND, env=env, pass_fds=(listener.fileno(),),
            start_new_session=True, stdout=log, stderr=subprocess.STDOUT,
        )
        listener.close()
        try:
            # Gunicorn trusts its loopback proxy by default. This exercises
            # DEBUG=False static serving, not real TLS termination.
            def get(path):
                return urlopen(Request(origin + path, headers={"X-Forwarded-Proto": "https"}), timeout=3)

            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError("Gunicorn exited during startup")
                try:
                    with get("/api/health/") as response:
                        assert json.load(response) == {"status": "ok"}
                    break
                except URLError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Gunicorn health check did not become ready")
            with get("/admin/login/") as response:
                assert response.status == 200
                assert b"csrfmiddlewaretoken" in response.read()
            manifest = json.loads((BACKEND / "staticfiles/staticfiles.json").read_text())
            with get("/static/" + manifest["paths"]["admin/css/base.css"]) as response:
                assert response.status == 200 and response.read()
                assert "immutable" in response.headers["Cache-Control"]
            try:
                get("/static/not-present.css")
            except HTTPError as error:
                assert error.code == 404
                error.close()
            else:
                raise AssertionError("Missing static asset did not return 404")
            print("PASS: local Gunicorn health/admin/hashed static/404 with DEBUG=False")
        except Exception:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    main()
