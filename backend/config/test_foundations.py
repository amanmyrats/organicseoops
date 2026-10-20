import json
import logging
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import storages
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .artifacts import (
    ArtifactNotFound,
    ArtifactStorageError,
    ArtifactValidationError,
    artifact_settings,
    read_private_artifact,
    save_private_artifact,
)
from .celery import configure_worker_logging
from .observability import JsonFormatter, RequestIdMiddleware, SafeRequestLogFilter
from .settings import load_local_env


TEST_STORAGES = {
    "artifacts": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class LoggingFoundationTests(SimpleTestCase):
    def test_application_and_framework_loggers_use_filtered_json_stdout(self):
        self.assertEqual(settings.LOGGING["handlers"]["console"]["stream"], "ext://sys.stdout")
        configure_worker_logging()
        for name in (
            "django", "django.server", "organicseoops", "celery", "celery.task",
            "multiprocessing", "gunicorn.error", "gunicorn.access",
        ):
            logger = logging.getLogger(name)
            self.assertFalse(logger.propagate, name)
            self.assertEqual(len(logger.handlers), 1, name)
            self.assertIs(logger.handlers[0].stream, sys.stdout, name)
            self.assertIsInstance(logger.handlers[0].formatter, JsonFormatter, name)
            self.assertTrue(any(isinstance(filter_, SafeRequestLogFilter) for filter_ in logger.handlers[0].filters), name)

    def test_request_id_is_validated_returned_and_correlated(self):
        middleware = RequestIdMiddleware(lambda request: HttpResponse(status=204))
        with self.assertLogs("organicseoops.request", "INFO") as logs:
            response = middleware(RequestFactory().get("/private?access_token=not-logged", HTTP_X_REQUEST_ID="valid-id_123"))
        self.assertEqual(response.headers["X-Request-ID"], "valid-id_123")
        self.assertIn("request.complete", logs.output[0])
        self.assertNotIn("not-logged", logs.output[0])

        with self.assertLogs("organicseoops.request", "INFO"):
            response = middleware(RequestFactory().get("/", HTTP_X_REQUEST_ID="bad\nvalue"))
        self.assertRegex(response.headers["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_json_logs_redact_headers_tokens_and_exception_messages(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("foundation.redaction")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        try:
            raise RuntimeError("provider access_token=exception-secret")
        except RuntimeError:
            logger.exception(
                "provider.failed Authorization: Bearer auth-secret\napi_key=key-secret",
                extra={"provider": "example", "provider_request_id": "safe-123"},
            )
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "provider.failed Authorization: [REDACTED]\napi_key=[REDACTED]")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertEqual(payload["provider_request_id"], "safe-123")
        self.assertNotIn("secret", stream.getvalue())

        stream.seek(0)
        stream.truncate()
        logger.error(
            "provider.body %s",
            '{"access_token":"json-secret","client_secret":"client-secret",'
            '"id_token":"id-secret","Cookie":"sessionid=cookie-secret"} '
            "https://example.invalid/?X-Amz-Signature=signed-secret&code=code-secret&"
            "state=state-secret&sig=sig-secret",
        )
        output = stream.getvalue()
        for secret in (
            "json-secret", "client-secret", "id-secret", "cookie-secret", "signed-secret",
            "code-secret", "state-secret", "sig-secret",
        ):
            self.assertNotIn(secret, output)

    def test_framework_request_logs_replace_sensitive_paths(self):
        request = RequestFactory().get("/reset/path-secret/?access_token=query-secret")
        request._organicseoops_request_id = "request-123"
        record = logging.LogRecord(
            "django.request", logging.WARNING, __file__, 1,
            "Not Found: %s", (request.get_full_path(),), None,
        )
        record.request = request
        self.assertTrue(SafeRequestLogFilter().filter(record))
        output = JsonFormatter().format(record)
        self.assertNotIn("path-secret", output)
        self.assertNotIn("query-secret", output)
        self.assertIn('"request_id":"request-123"', output)

        server_record = logging.LogRecord(
            "django.server", logging.INFO, __file__, 1,
            '"%s" %s %s', ("GET /reset/path-secret/?token=query-secret HTTP/1.1", "200", "12"), None,
        )
        server_record.request = object()
        self.assertTrue(SafeRequestLogFilter().filter(server_record))
        self.assertEqual(server_record.getMessage(), "GET [PATH]")

    def test_shared_report_link_is_redacted_without_django_request_context(self):
        token = "A" * 43
        for name, message, arguments in (
            ("gunicorn.access", '%s %s', ("GET", f"/api/reports/shared/{token}/?mode=download")),
            ("django.server", '"%s" %s', (f"GET /api/reports/shared/{token}/ HTTP/1.1", "200")),
        ):
            with self.subTest(logger=name):
                record = logging.LogRecord(name, logging.INFO, __file__, 1, message, arguments, None)
                self.assertTrue(SafeRequestLogFilter().filter(record))
                output = JsonFormatter().format(record)
                self.assertNotIn(token, output)
                self.assertIn("/api/reports/shared/[REDACTED]/", output)


class LocalEnvironmentTests(SimpleTestCase):
    def test_local_defaults_do_not_override_process_or_load_in_production(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# local only\nDJANGO_SECRET_KEY=local-value\nPOSTGRES_HOST=127.0.0.1\nPOSTGRES_PORT='15432'\n")
            with patch.dict(os.environ, {"POSTGRES_HOST": "explicit-host"}, clear=True):
                load_local_env(path)
                self.assertEqual(os.environ["POSTGRES_HOST"], "explicit-host")
                self.assertEqual(os.environ["POSTGRES_PORT"], "15432")
                self.assertEqual(os.environ["DJANGO_SECRET_KEY"], "local-value")
            with patch.dict(os.environ, {"DJANGO_ENV": "production"}, clear=True):
                load_local_env(path)
                self.assertNotIn("DJANGO_SECRET_KEY", os.environ)
            with patch.dict(os.environ, {"DJANGO_DEBUG": "0"}, clear=True):
                load_local_env(path)
                self.assertNotIn("DJANGO_SECRET_KEY", os.environ)

    def test_production_rejects_non_delivery_email_backends(self):
        environment = {
            "DJANGO_ENV": "production",
            "DJANGO_SECRET_KEY": "settings-test-secret",
            "DJANGO_DEBUG": "0",
            "DJANGO_ALLOWED_HOSTS": "app.example.com",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.com",
            "FRONTEND_ORIGIN": "https://app.example.com",
            "MFA_ENCRYPTION_KEYS": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            "POSTGRES_DB": "unused",
            "POSTGRES_USER": "unused",
            "POSTGRES_HOST": "unused",
            "ARTIFACT_STORAGE_BACKEND": "filesystem",
            "ARTIFACT_LOCAL_ROOT": "/tmp/organicseoops-settings-test",
        }
        backend = Path(__file__).resolve().parents[1]
        for email_backend in (
            "",
            "django.core.mail.backends.console.EmailBackend",
            "django.core.mail.backends.locmem.EmailBackend",
            "django.core.mail.backends.dummy.EmailBackend",
            "django.core.mail.backends.filebased.EmailBackend",
        ):
            with self.subTest(email_backend=email_backend):
                result = subprocess.run(
                    [sys.executable, "-c", "import config.settings"],
                    cwd=backend,
                    env={**environment, "EMAIL_BACKEND": email_backend},
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must use a delivery backend", result.stderr)
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            cwd=backend,
            env={**environment, "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend"},
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Configure a valid SMTP port and sender", result.stderr)
        smtp = {
            **environment,
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "email-smtp.eu-west-1.amazonaws.com",
            "AWS_REGION": "eu-west-1",
            "EMAIL_PORT": "587",
            "EMAIL_HOST_USER": "fixture-user",
            "EMAIL_HOST_PASSWORD": "fixture-password",
            "DEFAULT_FROM_EMAIL": "notices@example.invalid",
        }
        for invalid in ({"EMAIL_PORT": "0"}, {"EMAIL_HOST": "localhost"},
                        {"EMAIL_HOST": "smtp.example.invalid"},
                        {"EMAIL_HOST": "email-smtp.us-east-1.amazonaws.com"},
                        {"EMAIL_PORT": "465"}, {"EMAIL_HOST_PASSWORD": ""},
                        {"DEFAULT_FROM_EMAIL": "not-an-email"}):
            result = subprocess.run(
                [sys.executable, "-c", "import config.settings"],
                cwd=backend, env={**smtp, **invalid}, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0, invalid)
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings as s; assert s.EMAIL_USE_TLS and s.EMAIL_TIMEOUT == 10"],
            cwd=backend, env=smtp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        queue = "https://sqs.eu-west-1.amazonaws.com/123456789012/organicseoops-mail-feedback"
        topic = "arn:aws:sns:eu-west-1:123456789012:organicseoops-mail-feedback"
        for setting, allowed in (({"SES_FEEDBACK_QUEUE_URL": queue, "SES_FEEDBACK_TOPIC_ARN": topic,
                                   "AWS_REGION": "eu-west-1"}, True),
                                 ({"SES_FEEDBACK_QUEUE_URL": queue, "SES_FEEDBACK_TOPIC_ARN": topic,
                                   "AWS_REGION": "us-east-1"}, False),
                                 ({"SES_FEEDBACK_QUEUE_URL": "https://evil.invalid/queue",
                                   "SES_FEEDBACK_TOPIC_ARN": topic, "AWS_REGION": "eu-west-1"}, False),
                                 ({"SES_FEEDBACK_QUEUE_URL": queue, "AWS_REGION": "eu-west-1"}, False)):
            result = subprocess.run(
                [sys.executable, "-c", "import config.settings"], cwd=backend,
                env={**smtp, **setting}, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode == 0, allowed, result.stderr)
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings as s; assert not s.EMAIL_DELIVERY_ENABLED"],
            cwd=backend, env={**environment, "EMAIL_DELIVERY_ENABLED": "0",
                              "EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend"},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings"], cwd=backend,
            env={**environment, "EMAIL_DELIVERY_ENABLED": "0",
                 "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend"},
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_feedback_worker_requires_private_tls_sources_and_s3_without_calling_aws(self):
        from_email = "notices@example.invalid"
        ca = "/run/organicseoops/redis-ca.pem"
        redis_url = f"rediss://worker:fixture-password@10.0.0.4:6379/0?ssl_cert_reqs=required&ssl_ca_certs={ca}"
        environment = {
            "DJANGO_ENV": "production", "DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "fixture-settings-secret",
            "DJANGO_ALLOWED_HOSTS": "app.example.invalid,api.example.invalid",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.invalid",
            "FRONTEND_ORIGIN": "https://app.example.invalid", "API_ORIGIN": "https://api.example.invalid",
            "MFA_ENCRYPTION_KEYS": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            "POSTGRES_DB": "fixture", "POSTGRES_USER": "fixture", "POSTGRES_HOST": "10.0.0.3",
            "POSTGRES_SSLMODE": "verify-full", "POSTGRES_SSLROOTCERT": "/run/organicseoops/postgres-ca.pem",
            "CELERY_BROKER_URL": redis_url, "DJANGO_CACHE_URL": redis_url.replace("/0?", "/1?"),
            "REDIS_TLS_CA_FILE": ca, "ARTIFACT_STORAGE_BACKEND": "s3",
            "ARTIFACT_S3_BUCKET": "fixture-private-artifacts", "AWS_REGION": "eu-west-1",
            "FEEDBACK_WORKER_HOST": "1", "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "email-smtp.eu-west-1.amazonaws.com", "EMAIL_PORT": "587",
            "EMAIL_HOST_USER": "fixture-user", "EMAIL_HOST_PASSWORD": "fixture-password",
            "DEFAULT_FROM_EMAIL": from_email,
            "SES_FEEDBACK_QUEUE_URL": "https://sqs.eu-west-1.amazonaws.com/123456789012/feedback",
            "SES_FEEDBACK_TOPIC_ARN": "arn:aws:sns:eu-west-1:123456789012:feedback",
        }
        backend = Path(__file__).resolve().parents[1]

        def probe(values):
            return subprocess.run(
                [sys.executable, "-c", "import config.settings as s; assert s.FEEDBACK_WORKER_HOST; "
                 "assert s.DATABASES['default']['OPTIONS']['sslmode']=='verify-full'; "
                 "assert s.CELERY_BROKER_USE_SSL['ssl_ca_certs']=='/run/organicseoops/redis-ca.pem'"],
                cwd=backend, env=values, capture_output=True, text=True,
            )

        self.assertEqual(probe(environment).returncode, 0)
        for change in ({"DJANGO_ALLOWED_HOSTS": "*"}, {"API_ORIGIN": ""},
                       {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://*.example.invalid"},
                       {"POSTGRES_HOST": "8.8.8.8"}, {"POSTGRES_SSLMODE": ""},
                       {"CELERY_BROKER_URL": redis_url.replace("rediss://", "redis://")},
                       {"DJANGO_CACHE_URL": redis_url.replace("ssl_cert_reqs=required", "ssl_cert_reqs=none")},
                       {"ARTIFACT_STORAGE_BACKEND": "filesystem"}, {"SES_FEEDBACK_TOPIC_ARN": ""}):
            with self.subTest(change=change):
                self.assertNotEqual(probe({**environment, **change}).returncode, 0)

    def test_production_app_host_requires_docker_local_tls_and_disallows_feedback_queue(self):
        ca = "/run/organicseoops/redis-ca.pem"
        private_redis = f"rediss://app:fixture-password@redis:6379/0?ssl_cert_reqs=required&ssl_ca_certs={ca}"
        environment = {
            "DJANGO_ENV": "production", "DJANGO_DEBUG": "0", "PRODUCTION_APP_HOST": "1",
            "DJANGO_SECRET_KEY": "fixture-settings-secret", "DJANGO_ALLOWED_HOSTS": "app.example.invalid,api.example.invalid",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.invalid",
            "FRONTEND_ORIGIN": "https://app.example.invalid", "API_ORIGIN": "https://api.example.invalid",
            "MFA_ENCRYPTION_KEYS": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            "POSTGRES_DB": "fixture", "POSTGRES_USER": "fixture", "POSTGRES_HOST": "postgres",
            "POSTGRES_SSLMODE": "verify-full", "POSTGRES_SSLROOTCERT": "/run/organicseoops/postgres-ca.pem",
            "CELERY_BROKER_URL": private_redis, "DJANGO_CACHE_URL": private_redis.replace("/0?", "/1?"),
            "REDIS_TLS_CA_FILE": ca, "ARTIFACT_STORAGE_BACKEND": "s3",
            "ARTIFACT_S3_BUCKET": "fixture-private-artifacts", "AWS_REGION": "eu-west-1",
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": "email-smtp.eu-west-1.amazonaws.com", "EMAIL_PORT": "587",
            "EMAIL_HOST_USER": "fixture", "EMAIL_HOST_PASSWORD": "fixture",
            "DEFAULT_FROM_EMAIL": "notices@example.invalid",
        }
        backend = Path(__file__).resolve().parents[1]

        def check(values):
            return subprocess.run([sys.executable, "-c",
                "import config.settings as s; assert s.PRODUCTION_APP_HOST; "
                "assert s.DATABASES['default']['OPTIONS']['sslmode']=='verify-full'; "
                "assert s.CELERY_BROKER_USE_SSL['ssl_ca_certs']=='/run/organicseoops/redis-ca.pem'"],
                cwd=backend, env=values, capture_output=True, text=True)

        self.assertEqual(check(environment).returncode, 0)
        for change in ({"POSTGRES_SSLMODE": ""}, {"POSTGRES_HOST": "10.0.0.3"},
                       {"DJANGO_ALLOWED_HOSTS": "*"},
                       {"DJANGO_ALLOWED_HOSTS": "app.example.invalid,api.example.invalid,extra.example.invalid"},
                       {"DJANGO_ALLOWED_HOSTS": ".example.invalid,api.example.invalid"},
                       {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://*.example.invalid"},
                       {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.invalid,https://extra.example.invalid"},
                       {"FRONTEND_ORIGIN": "https://other.example.invalid"},
                       {"API_ORIGIN": "https://*.example.invalid"}, {"API_ORIGIN": "https://app.example.invalid"},
                       {"API_ORIGIN": "http://api.example.invalid"}, {"API_ORIGIN": ""},
                       {"CELERY_BROKER_URL": private_redis.replace("rediss://", "redis://")},
                       {"DJANGO_CACHE_URL": private_redis.replace("ssl_cert_reqs=required", "ssl_cert_reqs=none")},
                       {"ARTIFACT_STORAGE_BACKEND": "filesystem"},
                       {"SES_FEEDBACK_QUEUE_URL": "https://sqs.eu-west-1.amazonaws.com/123456789012/feedback",
                        "SES_FEEDBACK_TOPIC_ARN": "arn:aws:sns:eu-west-1:123456789012:feedback"},
                       {"FEEDBACK_WORKER_HOST": "1"}):
            with self.subTest(change=change):
                self.assertNotEqual(check({**environment, **change}).returncode, 0)


@override_settings(
    STORAGES=TEST_STORAGES,
    ARTIFACT_MAX_BYTES=4,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/plain"}),
)
class ArtifactFoundationTests(SimpleTestCase):
    def test_private_artifact_round_trip_is_bounded_and_opaque(self):
        key = save_private_artifact(scope="projects/123", content=b"{}", content_type="application/json")
        self.assertRegex(key, r"^projects/123/[0-9a-f]{32}\.json$")
        self.assertEqual(read_private_artifact(key), b"{}")
        with self.assertRaises(ArtifactNotFound):
            read_private_artifact("projects/123/" + "0" * 32 + ".json")

    def test_invalid_type_size_and_scope_fail_before_storage(self):
        for kwargs in (
            {"scope": "projects/123", "content": b"{}", "content_type": "text/html"},
            {"scope": "projects/123", "content": b"12345", "content_type": "text/plain"},
            {"scope": "../other", "content": b"ok", "content_type": "text/plain"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ArtifactValidationError):
                save_private_artifact(**kwargs)

    def test_storage_errors_are_generic(self):
        storage = storages["artifacts"]
        with patch.object(storage, "save", side_effect=OSError("access_token=storage-secret")):
            with self.assertLogs("organicseoops.artifacts", "ERROR") as logs:
                with self.assertRaisesRegex(ArtifactStorageError, "^Artifact storage is unavailable$"):
                    save_private_artifact(scope="projects/123", content=b"ok", content_type="text/plain")
        self.assertNotIn("storage-secret", " ".join(logs.output))

    @override_settings(STORAGES={
        **TEST_STORAGES,
        "artifacts": {"BACKEND": "missing.secret_backend.Storage"},
    })
    def test_storage_initialization_errors_are_generic(self):
        valid_key = "projects/123/" + "0" * 32 + ".json"
        for operation in (
            lambda: save_private_artifact(scope="projects/123", content=b"ok", content_type="text/plain"),
            lambda: read_private_artifact(valid_key),
        ):
            with self.assertLogs("organicseoops.artifacts", "ERROR") as logs:
                with self.assertRaisesRegex(ArtifactStorageError, "^Artifact storage is unavailable$"):
                    operation()
            self.assertNotIn("secret_backend", " ".join(logs.output))

    def test_download_rejects_unsupported_keys_and_oversized_objects_before_open(self):
        storage = storages["artifacts"]
        with patch.object(storage, "exists") as exists:
            with self.assertRaises(ArtifactValidationError):
                read_private_artifact("projects/123/payload.html")
        exists.assert_not_called()

        key = "projects/123/" + "a" * 32 + ".json"
        with (
            patch.object(storage, "exists", return_value=True),
            patch.object(storage, "size", return_value=5),
            patch.object(storage, "open") as open_file,
            self.assertRaisesRegex(ArtifactStorageError, "exceeds"),
        ):
            read_private_artifact(key)
        open_file.assert_not_called()

    def test_storage_configuration_is_private_and_iam_compatible(self):
        config, max_bytes, types = artifact_settings({
            "ARTIFACT_STORAGE_BACKEND": "s3",
            "ARTIFACT_S3_BUCKET": "private-artifacts",
            "ARTIFACT_S3_PREFIX": "environment/artifacts",
            "AWS_REGION": "eu-west-1",
        }, default_local_root=Path("/unused"))
        options = config["OPTIONS"]
        self.assertEqual(config["BACKEND"], "storages.backends.s3.S3Storage")
        self.assertIsNone(options["default_acl"])
        self.assertTrue(options["querystring_auth"])
        self.assertFalse(options["file_overwrite"])
        self.assertEqual(options["max_memory_size"], 8 * 1024 * 1024)
        self.assertEqual(options["object_parameters"]["CacheControl"], "private, no-store")
        self.assertEqual(options["client_config"].connect_timeout, 1)
        self.assertEqual(options["client_config"].read_timeout, 2)
        self.assertEqual(options["client_config"].retries["total_max_attempts"], 1)
        self.assertNotIn("access_key", options)
        self.assertEqual(max_bytes, 10 * 1024 * 1024)
        self.assertEqual(types, {"application/json", "application/zip", "text/csv", "text/html", "text/plain"})
        with self.assertRaises(ImproperlyConfigured):
            artifact_settings({"ARTIFACT_STORAGE_BACKEND": "s3"}, default_local_root=Path("/unused"))
        with TemporaryDirectory() as directory:
            local, _, _ = artifact_settings({}, default_local_root=Path(directory))
            self.assertEqual(local["OPTIONS"]["file_permissions_mode"], 0o600)
