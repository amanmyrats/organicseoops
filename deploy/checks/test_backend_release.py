import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMAGE = "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-backend@sha256:" + "a" * 64
RENDERER_IMAGE = "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-renderer@sha256:" + "b" * 64
POSTGRES_IMAGE = "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-postgres@sha256:" + "c" * 64
PROXY_IMAGE = "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-proxy@sha256:" + "d" * 64


class BackendReleaseTests(unittest.TestCase):
    def test_role_separation_migration_order_and_failure_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "host.env"
            env_file.write_text("synthetic only\n")
            data_dir = Path(tmp) / "ebs/postgres"
            data_dir.mkdir(parents=True)
            docker = Path(tmp) / "docker"
            docker.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                              "if [ \"$FAIL_MIGRATION\" = 1 ]; then\n"
                              "  case \" $* \" in *' migrate --noinput '*) exit 23 ;; esac\nfi\n")
            docker.chmod(0o700)
            mountpoint = Path(tmp) / "mountpoint"
            mountpoint.write_text("#!/bin/sh\nexit 0\n")
            mountpoint.chmod(0o700)
            stat = Path(tmp) / "stat"
            stat.write_text("#!/bin/sh\nprintf '70\\n'\n")
            stat.chmod(0o700)
            log = Path(tmp) / "calls"
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "CALL_LOG": str(log),
                   "BACKEND_IMAGE": IMAGE, "RENDERER_IMAGE": RENDERER_IMAGE,
                   "POSTGRES_IMAGE": POSTGRES_IMAGE, "PROXY_IMAGE": PROXY_IMAGE, "ENV_FILE": str(env_file),
                   "PRIVATE_POSTGRES_EBS_MOUNT": str(data_dir.parent),
                   "PRIVATE_POSTGRES_DATA_DIR": str(data_dir)}

            def release(role, mode="release"):
                return subprocess.run(["bash", "deploy/backend-release.sh", role, mode], cwd=ROOT,
                                      env=env, capture_output=True, text=True, check=False)

            self.assertEqual(release("app").returncode, 2)
            self.assertFalse(log.exists(), "No Compose command before backup/drain preflight")
            env.update(BACKUP_VERIFIED="1", ORIGIN_DRAINED="1")
            env["BACKEND_IMAGE"] = "organicseoops-backend:latest"
            self.assertEqual(release("app").returncode, 2)
            self.assertFalse(log.exists(), "Mutable images must be rejected before Compose")
            env["BACKEND_IMAGE"] = IMAGE

            for value in ("", "organicseoops-proxy:latest"):
                env["PROXY_IMAGE"] = value
                self.assertNotEqual(release("app").returncode, 0)
                self.assertFalse(log.exists(), "Invalid proxy digest must stop before Compose")
            env["PROXY_IMAGE"] = PROXY_IMAGE

            env["PRIVATE_POSTGRES_DATA_DIR"] = str(Path(tmp) / "not-mounted")
            self.assertEqual(release("app").returncode, 2)
            self.assertFalse(log.exists(), "Missing EBS data directory must prevent release")
            env["PRIVATE_POSTGRES_DATA_DIR"] = str(data_dir)

            self.assertEqual(release("app").returncode, 0)
            commands = log.read_text().splitlines()
            self.assertEqual([command.split(" ")[-1] for command in commands[:3]],
                             ["--quiet", "postgres", "proxy"])
            self.assertIn("run --rm --no-deps api python manage.py migrate --noinput", commands[3])
            self.assertIn("up -d --no-build --wait", commands[4])
            self.assertIn("compose.production-private.yaml", commands[0])
            self.assertNotIn("worker-default", commands[4])
            self.assertIn("renderer", commands[4])

            log.unlink()
            env["FAIL_MIGRATION"] = "1"
            self.assertEqual(release("app").returncode, 23)
            self.assertEqual(len(log.read_text().splitlines()), 4, "Failed migration must stop before up")

            log.unlink()
            env.pop("FAIL_MIGRATION")
            env.pop("PROXY_IMAGE")
            self.assertEqual(release("feedback").returncode, 0)
            commands = log.read_text().splitlines()
            self.assertEqual(len(commands), 3)
            self.assertIn("compose.feedback-worker.yaml", commands[0])
            self.assertNotIn("compose.production-private.yaml", commands[0])
            self.assertIn("up -d --no-deps --no-build --wait", commands[2])
            self.assertTrue(commands[2].endswith("worker-default"))

            log.unlink()
            env.pop("SCHEMA_COMPATIBLE", None)
            self.assertEqual(release("app", "rollback").returncode, 2)
            self.assertFalse(log.exists())
            env["SCHEMA_COMPATIBLE"] = "1"
            env["PROXY_IMAGE"] = PROXY_IMAGE
            self.assertEqual(release("app", "rollback").returncode, 0)
            commands = log.read_text().splitlines()
            self.assertEqual(len(commands), 3, "Compatible rollback must never rerun migrations")
            self.assertNotIn("migrate", " ".join(commands))
            self.assertTrue(commands[1].endswith("beat renderer proxy"), "Rollback explicitly pulls proxy")
            self.assertIn("up -d --no-deps --no-build --wait", commands[-1])
            self.assertNotIn("pull postgres", " ".join(commands))
            self.assertNotIn(" postgres redis ", commands[-1])
            self.assertIn("--no-deps", commands[-1])


if __name__ == "__main__":
    unittest.main()
