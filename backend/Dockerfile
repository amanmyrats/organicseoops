FROM python:3.13.15-alpine3.24@sha256:1a63a53928ce53d2b0baf08092a703f4840ac5dfbd61fd48802dbf48e08c801e AS builder

# pip validates the target environment without becoming a runtime dependency.
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir pip==26.2.1 \
    && python -m venv --without-pip /opt/venv \
    && python -m pip --python /opt/venv install --no-cache-dir -r /tmp/requirements.txt \
    && python -m pip --python /opt/venv check

FROM python:3.13.15-alpine3.24@sha256:1a63a53928ce53d2b0baf08092a703f4840ac5dfbd61fd48802dbf48e08c801e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Remove unused installer/bootstrap code, not just its vulnerability metadata.
RUN /usr/local/bin/python -m pip uninstall --yes pip \
    && /usr/local/bin/python -c "import pathlib, shutil, sysconfig; shutil.rmtree(pathlib.Path(sysconfig.get_path('stdlib')) / 'ensurepip')"
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY requirements.txt ./

COPY manage.py ./
COPY config/ ./config/
COPY accounts/ ./accounts/
COPY tenancy/ ./tenancy/
COPY jobs/ ./jobs/
COPY providers/ ./providers/
COPY integrations/ ./integrations/
# Static collection needs settings, not a database or a runtime secret.
# These environment values exist only for this build command.
RUN DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" \
    MFA_ENCRYPTION_KEYS="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
    DJANGO_DEBUG=1 EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend \
    POSTGRES_HOST=unused POSTGRES_DB=unused POSTGRES_USER=unused \
    python manage.py collectstatic --noinput

RUN addgroup -S -g 10001 app \
    && adduser -S -D -H -u 10001 -G app app \
    && mkdir -p /var/lib/celery /var/lib/organicseoops/artifacts \
        /var/lib/organicseoops/render-requests /var/lib/organicseoops/render-results \
    && chown -R app:app /var/lib/celery /var/lib/organicseoops \
    && chmod 700 /var/lib/organicseoops/artifacts /var/lib/organicseoops/render-requests \
        /var/lib/organicseoops/render-results
USER 10001:10001

EXPOSE 8000
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "config.wsgi:application"]
