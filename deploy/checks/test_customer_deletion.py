import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CustomerDeletionHostTests(unittest.TestCase):
    def test_app_only_script_requires_retained_mount_and_healthy_exact_api(self):
        script = ROOT / "deploy/customer-deletion.sh"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            calls = folder / "calls"
            mount = folder / "mountpoint"
            mount.write_text("#!/bin/sh\n[ \"$ALLOW_MOUNT\" = 1 ]\n")
            mount.chmod(0o700)
            docker = folder / "docker"
            docker.write_text("#!/bin/sh\ncase \"$1\" in\n"
                              "ps) printf 'abcdef123456\\n' ;;\n"
                              "inspect) printf '%s\\n' \"$API_HEALTH\" ;;\n"
                              "exec) printf '%s\\n' \"$*\" >> \"$CALL_LOG\" ;;\n"
                              "*) exit 2 ;;\nesac\n")
            docker.chmod(0o700)
            env = {**os.environ, "PATH": f"{folder}:{os.environ['PATH']}",
                   "CALL_LOG": str(calls), "ALLOW_MOUNT": "0", "API_HEALTH": "healthy"}
            self.assertNotEqual(subprocess.run(["bash", str(script)], env=env, capture_output=True).returncode, 0)
            self.assertFalse(calls.exists())
            env["ALLOW_MOUNT"] = "1"
            env["API_HEALTH"] = "unhealthy"
            self.assertNotEqual(subprocess.run(["bash", str(script)], env=env, capture_output=True).returncode, 0)
            self.assertFalse(calls.exists())
            env["API_HEALTH"] = "healthy"
            self.assertEqual(subprocess.run(["bash", str(script)], env=env, capture_output=True).returncode, 0)
            self.assertEqual(calls.read_text().strip(),
                "exec abcdef123456 python manage.py process_customer_deletions --execute --limit 10")
        timer = (ROOT / "deploy/organicseoops-customer-deletion.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 03:30:00 UTC", timer)
        self.assertIn("Persistent=true", timer)
