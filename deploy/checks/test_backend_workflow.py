import os
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/backend-release.yml").read_text())
CHECKS = yaml.safe_load((ROOT / ".github/workflows/backend-checks.yml").read_text())
STEPS = WORKFLOW["jobs"]["release"]["steps"]


class BackendWorkflowTests(unittest.TestCase):
    def test_release_gate_and_package_inventory(self):
        self.assertEqual(set(WORKFLOW[True]), {"push", "workflow_dispatch"})
        self.assertEqual(WORKFLOW["jobs"]["release"]["if"],
                         "github.ref == format('refs/heads/{0}', vars.PRODUCTION_BRANCH)")
        self.assertEqual(WORKFLOW["concurrency"], {"group": "backend-production-release", "cancel-in-progress": False})
        self.assertIn("AWS_REGION", WORKFLOW["env"])
        self.assertEqual(WORKFLOW["jobs"]["release"]["permissions"]["id-token"], "write")
        preflight = STEPS[0]["run"]
        self.assertIn("$APP_INSTANCE_ID\" != \"$FEEDBACK_INSTANCE_ID", preflight)
        self.assertIn("inputs.backup_verified", preflight)
        self.assertIn("inputs.origin_drained", preflight)
        self.assertIn("$PROXY_REPOSITORY_URI", preflight)
        self.assertIn("deploy/proxy/**", WORKFLOW[True]["push"]["paths"])
        images = next(step for step in STEPS if step.get("id") == "images")["run"]
        for phrase in ("docker tag organicseoops-proxy:local", 'docker push "$PROXY_REPOSITORY_URI:$GITHUB_SHA"',
                       "--repository-name organicseoops-proxy", '"$proxy_digest" =~ ^sha256:',
                       'proxy=$PROXY_REPOSITORY_URI@$proxy_digest'):
            self.assertIn(phrase, images)
        ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        for caller in (WORKFLOW["jobs"]["validation"], ci["jobs"]["backend"]):
            self.assertEqual(caller["uses"], "./.github/workflows/backend-checks.yml")
        scripts = "\n".join(step.get("run", "") for step in CHECKS["jobs"]["build"]["steps"])
        self.assertIn("build api postgres renderer proxy", scripts)
        self.assertTrue(any(step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
                            for step in STEPS))
        package = next(step for step in STEPS if step.get("id") == "bundle")["run"]
        for file in ("compose.yaml", "deploy/compose.production-private.yaml", "deploy/compose.production-app.yaml",
                     "deploy/compose.feedback-worker.yaml", "deploy/compose.release.yaml", "deploy/backend-release.sh",
                     "deploy/nginx.production.conf", "deploy/redis.production.conf", "deploy/postgres/pg_hba.production.conf",
                     "renderer/seccomp_profile.json", "deploy/postgres-backup.sh",
                      "deploy/organicseoops-backup.service", "deploy/organicseoops-backup.timer",
                      "deploy/customer-deletion.sh", "deploy/organicseoops-customer-deletion.service",
                      "deploy/organicseoops-customer-deletion.timer",
                     "deploy/host-service-check.sh", "deploy/organicseoops-service-check@.service",
                     "deploy/organicseoops-service-check@.timer", "deploy/cloudwatch-agent.json"):
            self.assertIn(file, package)
        self.assertIn("gzip -n", package)
        policy = (ROOT / "deploy/iam-backend-deploy-policy.json").read_text()
        self.assertNotIn("iam:PassRole", policy)
        self.assertIn("${APP_INSTANCE_ID}", policy)
        self.assertIn("${FEEDBACK_INSTANCE_ID}", policy)
        self.assertIn("${PROXY_ECR_REPOSITORY_ARN}", policy)

    def test_all_isolated_groups_and_exact_image_validation_precede_oidc(self):
        jobs = WORKFLOW["jobs"]
        self.assertEqual(jobs["validation"]["needs"], "preflight")
        self.assertEqual(jobs["release"]["needs"], "validation")
        for name in ("preflight", "validation"):
            self.assertEqual(jobs[name]["if"], jobs["release"]["if"])
        self.assertEqual(jobs["preflight"]["steps"][0]["run"], STEPS[0]["run"])
        for path in ("deploy/checks/**", ".github/workflows/backend-checks.yml"):
            self.assertIn(path, WORKFLOW[True]["push"]["paths"])
        tests = CHECKS["jobs"]["tests"]
        self.assertEqual(tests["needs"], "build")
        self.assertEqual(tests["strategy"], {"fail-fast": False, "matrix": {"shard": [0, 1]}})
        self.assertEqual(tests["timeout-minutes"], 360)
        run = next(step["run"] for step in tests["steps"] if step.get("name", "").startswith("Discover all"))
        self.assertIn("accounts config tenancy jobs providers integrations --noinput", run)
        self.assertIn("--testrunner config.sharded_test_runner.ShardedDiscoverRunner", run)
        self.assertIn('--shard "$BACKEND_CHECK_SHARD"', run)
        self.assertIn("--no-build", run)
        for workflow in (CHECKS, WORKFLOW):
            for job in workflow["jobs"].values():
                self.assertNotIn("continue-on-error", job)
                for step in job.get("steps", []):
                    self.assertNotIn("continue-on-error", step)
        self.assertEqual(CHECKS["permissions"], {"contents": "read"})
        self.assertNotIn("permissions", jobs["validation"])
        self.assertNotIn("permissions", jobs["preflight"])
        load = next(i for i, step in enumerate(STEPS) if step.get("name") == "Verify and load exact checked images")
        oidc = next(i for i, step in enumerate(STEPS) if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@"))
        self.assertLess(load, oidc)
        self.assertFalse(any("build api" in step.get("run", "") for step in STEPS))
        for consumers, dependency in ((tests["steps"], "build"), (STEPS, "validation")):
            download = next(step for step in consumers if step.get("uses", "").startswith("actions/download-artifact@"))
            self.assertEqual(download["with"]["artifact-ids"], "${{ needs." + dependency + ".outputs.artifact-id }}")
            self.assertEqual(download["with"]["digest-mismatch"], "error")
            self.assertNotIn("name", download["with"])
            self.assertNotIn("run-id", download["with"])
        upload = next(step for step in CHECKS["jobs"]["build"]["steps"] if step.get("id") == "upload")
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/backend-images.tar")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

    def test_archive_corruption_and_loaded_identity_fail_before_publish(self):
        load_steps = [next(step for step in steps if step.get("name") == "Verify and load exact checked images")
                      for steps in (CHECKS["jobs"]["tests"]["steps"], STEPS)]
        self.assertEqual(load_steps[0]["run"], load_steps[1]["run"])
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "backend-images" / "backend-images.tar"
            archive.parent.mkdir()
            archive.write_bytes(b"synthetic checked image archive")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            fake_docker = Path(tmp) / "docker"
            fake_docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                'if [ "$1 $2" = "image load" ]; then exit "$LOAD_EXIT"; fi\n'
                'if [ "$1 $2" = "image inspect" ]; then printf "%s\\n" "$OBSERVED_IMAGE_IDS"; fi\n')
            fake_docker.chmod(0o700)
            log = Path(tmp) / "calls"
            ids = "\n".join("sha256:" + digit * 64 for digit in "abcd")
            for sha, observed, load_exit, expected in (("", ids, "0", 1), ("0" * 64, ids, "0", 1),
                    (digest, ids, "23", 23), (digest, "sha256:" + "f" * 64, "0", 1), (digest, ids, "0", 0)):
                with self.subTest(sha=sha, load_exit=load_exit, expected=expected):
                    env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "RUNNER_TEMP": tmp,
                        "CALL_LOG": str(log), "EXPECTED_ARCHIVE_SHA256": sha, "EXPECTED_IMAGE_IDS": ids,
                        "OBSERVED_IMAGE_IDS": observed, "LOAD_EXIT": load_exit}
                    result = subprocess.run(["bash", "-e", "-c", load_steps[0]["run"]], env=env,
                                            capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    calls = log.read_text().splitlines() if log.exists() else []
                    if sha != digest: self.assertEqual(calls, [])
                    else:
                        self.assertTrue(calls[0].startswith("image load "))
                        self.assertEqual(len(calls), 1 if load_exit == "23" else 2)
                    if log.exists(): log.unlink()

    def test_failed_app_ssm_wait_prevents_feedback_command(self):
        app, feedback = (next(step for step in STEPS if step.get("name", "").startswith(label))
                         for label in ("Release application", "Release separate feedback"))
        self.assertEqual(app["if"], feedback["if"])
        self.assertIn("aws ssm wait command-executed", app["run"])
        with tempfile.TemporaryDirectory() as tmp:
            fake_aws = Path(tmp) / "aws"
            fake_aws.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                                "if [ \"$2\" = send-command ]; then printf 'example-command-id\\n'; fi\n"
                                "if [ \"$2\" = wait ] && [ \"$FAIL_APP\" = 1 ]; then exit 23; fi\n")
            fake_aws.chmod(0o700)
            log = Path(tmp) / "calls"
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "CALL_LOG": str(log),
                   "RUNNER_TEMP": tmp, "AWS_REGION": "eu-west-1", "AWS_ACCOUNT_ID": "123456789012",
                   "RELEASE_BUCKET_NAME": "private-release-bucket", "GITHUB_SHA": "a" * 40,
                   "BUNDLE_SHA256": "b" * 64,
                   "BACKEND_IMAGE": "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-backend@sha256:" + "c" * 64,
                   "RENDERER_IMAGE": "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-renderer@sha256:" + "d" * 64,
                   "POSTGRES_IMAGE": "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-postgres@sha256:" + "e" * 64,
                   "PROXY_IMAGE": "123456789012.dkr.ecr.eu-west-1.amazonaws.com/organicseoops-proxy@sha256:" + "f" * 64,
                   "APP_INSTANCE_ID": "i-1234567890abcdef0", "FEEDBACK_INSTANCE_ID": "i-abcdef01234567890"}
            scripts = [step["run"] for step in (app, feedback)]
            env["FAIL_APP"] = "1"
            result = subprocess.run(["bash", "-e", "-c", scripts[0]], cwd=ROOT, env=env,
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(sum("send-command" in line for line in log.read_text().splitlines()), 1)
            log.unlink()
            env["FAIL_APP"] = "0"
            for script in scripts:
                result = subprocess.run(["bash", "-e", "-c", script], cwd=ROOT, env=env,
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            self.assertEqual(sum("send-command" in line for line in calls), 2)
            self.assertLess(next(i for i, line in enumerate(calls) if "--instance-ids i-1234567890abcdef0" in line),
                            next(i for i, line in enumerate(calls) if "--instance-ids i-abcdef01234567890" in line))

    def test_rollback_is_manual_branch_bound_and_checks_schema_before_ssm(self):
        rollback = yaml.safe_load((ROOT / ".github/workflows/backend-rollback.yml").read_text())
        self.assertEqual(set(rollback[True]), {"workflow_dispatch"})
        self.assertEqual(rollback["concurrency"]["group"], WORKFLOW["concurrency"]["group"])
        steps = rollback["jobs"]["rollback"]["steps"]
        self.assertIn('test "$SCHEMA_COMPATIBLE" = true', steps[0]["run"])
        self.assertIn("--mode rollback --role app", steps[2]["run"])
        self.assertTrue(rollback[True]["workflow_dispatch"]["inputs"]["proxy_image"]["required"])
        self.assertEqual(rollback["jobs"]["rollback"]["env"]["PROXY_IMAGE"], "${{ inputs.proxy_image }}")
        self.assertIn('--proxy-image "$PROXY_IMAGE"', steps[2]["run"])
        self.assertIn("--mode rollback --role feedback", steps[2]["run"])
        self.assertNotIn("migrate", " ".join(step.get("run", "") for step in steps))
        self.assertIn("$APP_INSTANCE_ID", steps[-2]["run"])
        self.assertIn("$FEEDBACK_INSTANCE_ID", steps[-1]["run"])
        self.assertTrue(any(step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
                            for step in steps))


if __name__ == "__main__":
    unittest.main()
