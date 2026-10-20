import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/frontend-deploy.yml").read_text())
STEPS = WORKFLOW["jobs"]["release"]["steps"]


class FrontendDeliveryTests(unittest.TestCase):
    def test_manual_oidc_release_and_scoped_policy(self):
        self.assertEqual(set(WORKFLOW[True]), {"push", "workflow_dispatch"})
        self.assertEqual(STEPS[0]["name"], "Check exact release branch and resources")
        self.assertEqual(WORKFLOW["jobs"]["release"]["if"],
                         "github.ref == format('refs/heads/{0}', vars.PRODUCTION_BRANCH)")
        self.assertIn("frontend/**", WORKFLOW[True]["push"]["paths"])
        self.assertEqual(WORKFLOW["jobs"]["release"]["permissions"],
                         {"contents": "read", "id-token": "write"})
        self.assertIn('test "$GITHUB_REF" = "refs/heads/$PRODUCTION_BRANCH"', STEPS[0]["run"])
        self.assertFalse(WORKFLOW["concurrency"]["cancel-in-progress"])
        self.assertTrue(any(step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
                            and step["with"]["role-to-assume"] == "${{ vars.FRONTEND_DEPLOY_ROLE_ARN }}"
                            for step in STEPS))
        self.assertTrue(any("npm run check" in step.get("run", "")
                            and "publication-guard.mjs" in step["run"]
                            and "provider_readiness.py" in step["run"] for step in STEPS))
        self.assertTrue(any("node checks/publication-guard.mjs" in step.get("run", "") for step in STEPS))
        actions = json.loads((ROOT / "deploy/iam-frontend-deploy-policy.json").read_text())["Statement"]
        self.assertEqual(actions[1]["Resource"], "arn:aws:s3:::${FRONTEND_BUCKET_NAME}/*")
        self.assertEqual(actions[2]["Resource"],
                         "arn:aws:cloudfront::${AWS_ACCOUNT_ID}:distribution/${FRONTEND_DISTRIBUTION_ID}")
        self.assertEqual(set(actions[2]["Action"]),
                         {"cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"})

    def test_upload_order_and_failed_upload_prevents_invalidation(self):
        upload_steps = [step for step in STEPS if step.get("name", "").startswith(("Upload", "Publish", "Invalidate"))]
        self.assertEqual([step["name"] for step in upload_steps], [
            "Upload hashed assets before HTML", "Upload other public files with revalidation",
            "Publish all HTML including nested prerenders and CSR", "Invalidate and await public HTML refresh",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            fake_aws = Path(tmp) / "aws"
            fake_aws.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                                "if [ \"$2\" = \"$FAIL_AWS\" ]; then exit 23; fi\n"
                                "if [ \"$2\" = create-invalidation ]; then printf 'fake-invalidation-id\\n'; fi\n")
            fake_aws.chmod(0o700)
            log = Path(tmp) / "calls"
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "CALL_LOG": str(log),
                   "FRONTEND_BUCKET_NAME": "example-static-bucket", "FRONTEND_DISTRIBUTION_ID": "EEXAMPLE"}
            for step in upload_steps:
                result = subprocess.run(["bash", "-e", "-c", step["run"]], env=env,
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, f"{step['name']}: {result.stderr}")
            calls = log.read_text().splitlines()
            self.assertEqual([call.split(" ", 2)[:2] for call in calls], [
                ["s3", "cp"], ["s3", "sync"], ["s3", "sync"],
                ["cloudfront", "create-invalidation"], ["cloudfront", "wait"],
            ])
            self.assertIn("--cache-control public,max-age=31536000,immutable", calls[0])
            self.assertIn("--include *.html --delete", calls[2])
            log.unlink()
            env["FAIL_AWS"] = "sync"
            for step in upload_steps:
                result = subprocess.run(["bash", "-e", "-c", step["run"]], env=env,
                                        capture_output=True, text=True, check=False)
                if result.returncode:
                    break
            self.assertEqual(result.returncode, 23)
            self.assertTrue(all(not call.startswith("cloudfront ") for call in log.read_text().splitlines()))


if __name__ == "__main__":
    unittest.main()
