from pathlib import Path
import stat
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CheckEnvironmentTests(unittest.TestCase):
    def test_development_and_production_profiles_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles = {}
            for profile in ("development", "production"):
                path = Path(directory) / profile
                subprocess.run([
                    sys.executable, str(ROOT / "deploy/checks/create_check_env.py"), str(path),
                    "--profile", profile, "--project-name", "organicseoops-dev", "--proxy-port", "18000",
                ], capture_output=True, check=True)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                profiles[profile] = dict(line.split("=", 1) for line in path.read_text().splitlines()
                                         if line and not line.startswith("#"))
            dev, prod = profiles["development"], profiles["production"]
            self.assertEqual(dev["FRONTEND_ORIGIN"], "http://127.0.0.1:4200")
            self.assertEqual(dev["DJANGO_DEBUG"], "1")
            self.assertEqual(dev["POSTGRES_HOST"], "127.0.0.1")
            self.assertEqual(dev["POSTGRES_PORT"], "15432")
            self.assertEqual(dev["DJANGO_CACHE_URL"], "redis://127.0.0.1:16379/1")
            self.assertEqual(dev["EMAIL_BACKEND"], "django.core.mail.backends.console.EmailBackend")
            self.assertEqual(prod["DJANGO_DEBUG"], "0")
            self.assertEqual(prod["COMPOSE_PROJECT_NAME"], "organicseoops-prod")
            self.assertEqual(prod["ARTIFACT_STORAGE_BACKEND"], "s3")
            self.assertEqual(prod["EMAIL_BACKEND"], "")
            for key in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD"):
                self.assertTrue(dev[key])
                self.assertEqual(prod[key], "")

    def test_dev_wrapper_ignores_ambient_closure_and_identity_policy_values(self):
        keys = ("CUSTOMER_EXPORT_COPY_POLICY_REFERENCE", "CUSTOMER_EXPORT_COPY_LIFETIME_DAYS",
                "SELF_SERVICE_CLOSURE_ENABLED", "SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED",
                "PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE", "PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS",
                "PERSONAL_IDENTITY_RETENTION_KEY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (ROOT / "backend-dev.sh").read_text().split('case "${1:-up}" in', 1)[0]
            script = root / "backend-dev.sh"
            script.write_text(source + "compose ps\npreflight\n")
            stub = "#!/bin/sh\nfor key in " + " ".join(keys) + "; do\n"
            stub += '  if printenv "$key" > /dev/null; then exit 1; fi\ndone\necho isolated\n'
            for command in ("docker", "python3"):
                path = root / command
                path.write_text(stub)
                path.chmod(0o700)
            result = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True,
                env={"PATH": str(root) + os.pathsep + os.defpath,
                     **{key: "synthetic-ambient-value" for key in keys}})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["isolated"] * 3)

    def test_private_fresh_credentials_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "check.env"
            command = [sys.executable, str(ROOT / "deploy/checks/create_check_env.py"), str(path)]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            original = path.read_text()
            values = dict(line.split("=", 1) for line in original.splitlines()
                          if line and not line.startswith("#"))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(values["COMPOSE_PROJECT_NAME"], "organicseoops-ci")
            self.assertEqual(values["PROXY_PORT"], "18080")
            self.assertEqual(values["FRONTEND_ORIGIN"], "http://localhost:18080")
            self.assertEqual(values["POSTGRES_HOST"], "postgres")
            self.assertEqual(values["DJANGO_CACHE_URL"], "redis://redis:6379/1")
            self.assertNotEqual(values["DJANGO_SECRET_KEY"], values["POSTGRES_PASSWORD"])
            for key in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD"):
                self.assertGreaterEqual(len(values[key]), 50)
                self.assertNotIn(values[key], result.stdout + result.stderr)
            retry = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual(path.read_text(), original)
            self.assertNotIn(values["POSTGRES_PASSWORD"], retry.stdout + retry.stderr)

    def test_isolated_project_port_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "check.env"
            command = [sys.executable, str(ROOT / "deploy/checks/create_check_env.py"), str(path)]
            for extra in (["--project-name", "bad\nPOSTGRES_DB=other"], ["--proxy-port", "0"]):
                result = subprocess.run(command + extra, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(path.exists())
            subprocess.run(command + ["--project-name", "organicseoops-remediation", "--proxy-port", "18080"],
                           capture_output=True, text=True, check=True)
            values = dict(line.split("=", 1) for line in path.read_text().splitlines()
                          if line and not line.startswith("#"))
            self.assertEqual(values["COMPOSE_PROJECT_NAME"], "organicseoops-remediation")
            self.assertEqual(values["PROXY_PORT"], "18080")
            self.assertEqual(values["DJANGO_CSRF_TRUSTED_ORIGINS"], "http://localhost:18080,http://127.0.0.1:18080")
            self.assertEqual(values["FRONTEND_ORIGIN"], "http://localhost:18080")


if __name__ == "__main__":
    unittest.main()
