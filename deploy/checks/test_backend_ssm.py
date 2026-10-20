import importlib.util
import json
import unittest
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "backend-ssm-command.py"
SPEC = importlib.util.spec_from_file_location("backend_ssm_command", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BackendSsmTests(unittest.TestCase):
    def test_app_then_worker_use_exact_bundle_and_separate_services(self):
        inputs = dict(region="eu-west-1", account="123456789012", bucket="private-release-bundle",
                      commit="a" * 40, bundle_sha256="b" * 64,
                      backend_image="123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-backend@sha256:" + "c" * 64,
                      renderer_image="123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-renderer@sha256:" + "d" * 64,
                      postgres_image="123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-postgres@sha256:" + "e" * 64,
                      proxy_image="123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-proxy@sha256:" + "f" * 64)
        app = MODULE.command(role="app", **inputs)
        worker = MODULE.command(role="feedback", **{key: value for key, value in inputs.items()
                                                    if key not in {"renderer_image", "postgres_image", "proxy_image"}})
        self.assertEqual(app["executionTimeout"], ["3600"])
        for params in (app, worker):
            commands = params["commands"]
            self.assertEqual(commands[:2], ["set -eu", "umask 077"])
            self.assertLess(next(i for i, cmd in enumerate(commands) if "get-object" in cmd),
                            next(i for i, cmd in enumerate(commands) if "sha256sum --check" in cmd))
            self.assertLess(next(i for i, cmd in enumerate(commands) if "sha256sum --check" in cmd),
                            next(i for i, cmd in enumerate(commands) if "tar -xzf" in cmd))
            self.assertEqual(json.loads(json.dumps(params)), params)
            self.assertNotIn("POSTGRES_PASSWORD", str(params))
        self.assertIn("RENDERER_IMAGE=", app["commands"][-2])
        self.assertIn("POSTGRES_IMAGE=", app["commands"][-2])
        self.assertIn("PROXY_IMAGE=" + inputs["proxy_image"], app["commands"][-2])
        self.assertIn("ENV_FILE=/opt/organicseoops/releases/", app["commands"][-2])
        self.assertIn("/backend/.env.prod", app["commands"][-2])
        self.assertIn("BACKUP_VERIFIED=1 ORIGIN_DRAINED=1", app["commands"][-2])
        self.assertIn("/opt/organicseoops/current", app["commands"][-1])
        self.assertNotIn("RENDERER_IMAGE=", worker["commands"][-2])
        self.assertNotIn("POSTGRES_IMAGE=", worker["commands"][-2])
        self.assertNotIn("PROXY_IMAGE=", worker["commands"][-2])
        self.assertNotIn("ORIGIN_DRAINED", worker["commands"][-2])
        self.assertIn("/backend/.env.feedback.prod", worker["commands"][-2])
        self.assertIn("/opt/organicseoops/current", worker["commands"][-1])
        rollback = MODULE.command(role="app", mode="rollback", **inputs)
        self.assertIn("SCHEMA_COMPATIBLE=1", rollback["commands"][-2])
        self.assertIn("PROXY_IMAGE=" + inputs["proxy_image"], rollback["commands"][-2])
        self.assertTrue(rollback["commands"][-2].endswith("backend-release.sh app rollback"))

        for override in (
            {"backend_image": "organicseoops-backend:latest"},
            {"backend_image": inputs["backend_image"].replace("123456789012", "000000000000")},
            {"renderer_image": ""},
            {"proxy_image": ""},
            {"proxy_image": "organicseoops-proxy:latest"},
            {"proxy_image": inputs["proxy_image"].replace("123456789012", "000000000000")},
            {"proxy_image": inputs["proxy_image"].replace("eu-west-1", "eu-west-2")},
            {"commit": "../wrong"},
            {"bucket": "private-release-bundle;whoami"},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                MODULE.command(role="app", **{**inputs, **override})


if __name__ == "__main__":
    unittest.main()
