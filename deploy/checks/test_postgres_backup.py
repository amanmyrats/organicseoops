import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PostgresBackupTests(unittest.TestCase):
    def test_backup_validates_archive_before_upload_and_failure_emits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "staging"
            staging.mkdir()
            mountpoint = Path(tmp) / "mountpoint"
            mountpoint.write_text("#!/bin/sh\nexit 0\n")
            mountpoint.chmod(0o700)
            docker = Path(tmp) / "docker"
            docker.write_text("#!/bin/sh\n"
                              "printf 'docker %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                              "if [ \"$1\" = ps ]; then printf 'abcdef123456\\n'; fi\n"
                              "if [ \"$1\" = inspect ]; then printf 'healthy\\n'; fi\n"
                              "if [ \"$1\" = exec ] && [ \"$3\" = sh ]; then\n"
                              "  case \" $* \" in *pg_database_size*) printf '1024\\n'; exit 0 ;; esac\n"
                              "  if [ \"$FAIL_DUMP\" = 1 ]; then exit 23; fi\n"
                              "  printf 'synthetic-pg-archive\\n'\n"
                              "fi\n"
                              "if [ \"$1\" = exec ] && [ \"$2\" = -i ]; then\n"
                              "  read -r archive; [ \"$archive\" = synthetic-pg-archive ]\n"
                              "fi\n")
            docker.chmod(0o700)
            df = Path(tmp) / "df"
            df.write_text("#!/bin/sh\nprintf 'Avail\\n%s\\n' \"${DISK_AVAILABLE:-4000000000}\"\n")
            df.chmod(0o700)
            aws = Path(tmp) / "aws"
            aws.write_text("#!/bin/sh\nprintf 'aws %s\\n' \"$*\" >> \"$CALL_LOG\"\n")
            aws.chmod(0o700)
            log = Path(tmp) / "calls"
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "CALL_LOG": str(log),
                   "BACKUP_BUCKET": "private-backups", "AWS_REGION": "eu-west-1",
                   "BACKUP_EBS_MOUNT": tmp, "BACKUP_STAGING_DIR": str(staging)}

            def run():
                return subprocess.run(["bash", "deploy/postgres-backup.sh"], cwd=ROOT, env=env,
                                      capture_output=True, text=True, check=False)

            self.assertEqual(run().returncode, 0)
            lines = log.read_text().splitlines()
            self.assertLess(next(i for i, line in enumerate(lines) if "pg_restore --list" in line),
                            next(i for i, line in enumerate(lines) if "s3api put-object" in line))
            self.assertIn("--checksum-algorithm SHA256 --if-none-match *", " ".join(lines))
            self.assertIn('"Value":1', lines[-1])
            self.assertFalse(list(staging.glob("backup.*.pgcustom")))

            log.unlink()
            env["DISK_AVAILABLE"] = "1024"
            self.assertEqual(run().returncode, 2)
            self.assertFalse(any("s3api put-object" in line for line in log.read_text().splitlines()))
            env.pop("DISK_AVAILABLE")

            log.unlink()
            env["FAIL_DUMP"] = "1"
            self.assertEqual(run().returncode, 23)
            lines = log.read_text().splitlines()
            self.assertFalse(any("s3api put-object" in line for line in lines))
            self.assertIn('"Value":0', lines[-1])
            self.assertFalse(list(staging.glob("backup.*.pgcustom")))

            log.unlink()
            stale = staging / "backup.known-unknown.pgcustom"
            stale.write_bytes(b"synthetic only")
            self.assertEqual(run().returncode, 2)
            self.assertFalse(any("docker" in line or "s3api" in line for line in log.read_text().splitlines()))
            stale.unlink()

            log.unlink()
            env["BACKUP_STAGING_DIR"] = str(Path(tmp) / "missing")
            self.assertEqual(run().returncode, 2)
            self.assertFalse(log.exists(), "No Docker or AWS call before mount preflight")


if __name__ == "__main__":
    unittest.main()
