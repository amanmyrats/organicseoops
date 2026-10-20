FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0

# Chromium rendering does not use the base image's vulnerable GStreamer bad plugins.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade \
        openssl=3.0.13-0ubuntu3.16 libssl3t64=3.0.13-0ubuntu3.16 \
    && apt-get purge -y gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m pip check \
    && python -m pip uninstall -y virtualenv distlib platformdirs python-discovery filelock pip \
    && python -c 'import shutil; from pathlib import Path; cache = Path("/root/.cache/virtualenv"); shutil.rmtree(cache); assert not cache.exists()' \
    && python -c 'from playwright.sync_api import sync_playwright; from importlib.util import find_spec; assert all(find_spec(name) is None for name in ("pip", "virtualenv", "distlib", "platformdirs", "python_discovery", "filelock"))' \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home app \
    && mkdir -p /app /var/lib/organicseoops/render-requests /var/lib/organicseoops/render-results \
    && chown -R app:app /app /var/lib/organicseoops

WORKDIR /app
COPY --chown=10001:10001 service.py ./service.py
USER 10001:10001
CMD ["python", "/app/service.py"]
