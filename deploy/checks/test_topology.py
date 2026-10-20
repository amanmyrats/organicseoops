"""Source contracts only: YAML parsing does not validate or execute Compose."""
from pathlib import Path
import json
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class TopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load((ROOT / "compose.yaml").read_text())
        cls.services = cls.config["services"]
        cls.development = yaml.safe_load((ROOT / "compose.development.yaml").read_text())

    def test_service_boundaries_and_private_persistent_data(self):
        self.assertEqual(set(self.services), {
            "proxy", "api", "worker-default", "worker-ai", "worker-crawl",
            "worker-audit", "beat", "renderer", "postgres", "redis",
        })
        self.assertTrue(self.config["networks"]["data"]["internal"])
        for name, service in self.services.items():
            if name != "renderer":
                self.assertNotIn("network_mode", service)
            self.assertNotIn("privileged", service)
            if name != "proxy":
                self.assertFalse(service.get("ports"), name)
            else:
                self.assertTrue(all(port.startswith("127.0.0.1:") for port in service["ports"]))
        for name in ("postgres", "redis"):
            self.assertEqual(self.services[name]["networks"], ["data"])
            self.assertIn("healthcheck", self.services[name])
            self.assertTrue(self.services[name]["volumes"])
        self.assertEqual(self.services["postgres"]["volumes"], ["postgres-data:/var/lib/postgresql"])
        self.assertEqual(self.config["volumes"]["postgres-data"]["name"], "${COMPOSE_PROJECT_NAME:-organicseoops}_postgres-alpine-data")
        self.assertIn("--locale-provider=builtin", self.services["postgres"]["environment"]["POSTGRES_INITDB_ARGS"])
        self.assertIn("--appendonly", self.services["redis"]["command"])
        self.assertIn("noeviction", self.services["redis"]["command"])
        for name in ("api", "worker-default", "worker-ai", "worker-crawl", "worker-audit", "beat"):
            self.assertIn("artifact-data:/var/lib/organicseoops/artifacts", self.services[name]["volumes"])
        self.assertEqual(self.services["renderer"]["network_mode"], "none")
        self.assertNotIn("environment", self.services["renderer"])
        self.assertTrue(self.services["renderer"]["read_only"])
        self.assertEqual(self.services["renderer"]["cap_drop"], ["ALL"])
        self.assertIn("seccomp=./renderer/seccomp_profile.json", self.services["renderer"]["security_opt"])
        spool = {
            "render-requests:/var/lib/organicseoops/render-requests",
            "render-results:/var/lib/organicseoops/render-results",
        }
        self.assertEqual(set(self.services["renderer"]["volumes"]), spool)
        self.assertTrue(spool < set(self.services["worker-crawl"]["volumes"]))
        for name, service in self.services.items():
            if name not in {"renderer", "worker-crawl"}:
                self.assertTrue(spool.isdisjoint(service.get("volumes", [])), name)
        self.assertIn("artifact-data", self.config["volumes"])

    def test_backend_image_reuse_distinct_commands_and_single_scheduler(self):
        api = self.services["api"]
        self.assertEqual(api["command"][0], "gunicorn")
        for name in ("api", "worker-default", "worker-ai", "worker-crawl", "worker-audit", "beat"):
            service = self.services[name]
            self.assertEqual(service["image"], api["image"])
            self.assertEqual(service["build"], api["build"])
            self.assertTrue(service["read_only"])
            self.assertNotIn("migrate", service["command"])
            self.assertNotIn("sh", service["command"])
            self.assertNotIn("-B", service["command"])
            if name.startswith("worker-"):
                self.assertIn("worker", service["command"])
                self.assertIn("--queues=" + name.removeprefix("worker-"), service["command"])
                self.assertNotIn("beat", service["command"])
        self.assertEqual(sum("beat" in service.get("command", []) for service in self.services.values()), 1)
        self.assertTrue(self.services["beat"]["container_name"])
        self.assertIn("beat-data:/var/lib/celery", self.services["beat"]["volumes"])

    def test_runtime_secrets_are_not_build_inputs(self):
        example = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text().splitlines()
                       if line and not line.startswith("#"))
        for key in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD"):
            self.assertEqual(example[key], "")
            self.assertIn(":?", self.services["api"]["environment"][key])
        for key in ("ARTIFACT_S3_BUCKET", "AWS_REGION"):
            self.assertEqual(example[key], "")
        self.assertEqual(example["API_ORIGIN"], "")
        self.assertEqual(self.services["api"]["environment"]["API_ORIGIN"], "${API_ORIGIN:-}")
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            self.assertNotIn(key, example)
            self.assertNotIn(key, self.services["api"]["environment"])
        self.assertEqual(self.services["api"]["environment"]["ARTIFACT_LOCAL_ROOT"], "/var/lib/organicseoops/artifacts")
        self.assertEqual(self.services["api"]["environment"]["ARTIFACT_STORAGE_BACKEND"], "${ARTIFACT_STORAGE_BACKEND:-filesystem}")
        self.assertEqual(self.services["api"]["environment"]["SELF_SERVICE_CLOSURE_ENABLED"],
                         "${SELF_SERVICE_CLOSURE_ENABLED:-0}")
        self.assertEqual(self.services["api"]["environment"]["SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED"],
                         "${SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED:-0}")
        self.assertNotIn("SELF_SERVICE_CLOSURE_ENABLED", self.services["worker-default"]["environment"])
        self.assertNotIn("SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED", self.services["worker-default"]["environment"])
        for key in ("PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE", "PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS",
                    "PERSONAL_IDENTITY_RETENTION_KEY"):
            self.assertEqual(example[key], "")
            self.assertEqual(self.services["api"]["environment"][key], "${" + key + ":-}")
            for service in ("worker-default", "worker-ai", "worker-crawl", "worker-audit", "beat"):
                self.assertNotIn(key, self.services[service]["environment"])
        for key in ("CUSTOMER_EXPORT_COPY_POLICY_REFERENCE", "CUSTOMER_EXPORT_COPY_LIFETIME_DAYS"):
            self.assertEqual(example[key], "")
            for service in ("api", "worker-audit"):
                self.assertEqual(self.services[service]["environment"][key], "${" + key + ":-}")
            for service in ("worker-default", "worker-ai", "worker-crawl", "beat"):
                self.assertNotIn(key, self.services[service]["environment"])
        self.assertEqual(example["WEEKLY_SUMMARY_DELIVERY_ENABLED"], "0")
        self.assertEqual(self.services["worker-default"]["environment"]["WEEKLY_SUMMARY_DELIVERY_ENABLED"],
                         "${WEEKLY_SUMMARY_DELIVERY_ENABLED:-0}")
        self.assertEqual(self.services["api"]["environment"]["WEEKLY_SUMMARY_DELIVERY_ENABLED"],
                         self.services["worker-default"]["environment"]["WEEKLY_SUMMARY_DELIVERY_ENABLED"])
        for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
            self.assertNotIn("WEEKLY_SUMMARY_DELIVERY_ENABLED", self.services[service]["environment"])
        self.assertEqual(example["ALERT_DIGEST_DELIVERY_ENABLED"], "0")
        self.assertEqual(self.services["worker-default"]["environment"]["ALERT_DIGEST_DELIVERY_ENABLED"],
                         "${ALERT_DIGEST_DELIVERY_ENABLED:-0}")
        self.assertEqual(self.services["api"]["environment"]["ALERT_DIGEST_DELIVERY_ENABLED"],
                         self.services["worker-default"]["environment"]["ALERT_DIGEST_DELIVERY_ENABLED"])
        for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
            self.assertNotIn("ALERT_DIGEST_DELIVERY_ENABLED", self.services[service]["environment"])
        self.assertEqual(example["CRUX_ALERT_DELIVERY_ENABLED"], "0")
        self.assertEqual(self.services["worker-default"]["environment"]["CRUX_ALERT_DELIVERY_ENABLED"],
                         "${CRUX_ALERT_DELIVERY_ENABLED:-0}")
        self.assertEqual(self.services["api"]["environment"]["CRUX_ALERT_DELIVERY_ENABLED"],
                         self.services["worker-default"]["environment"]["CRUX_ALERT_DELIVERY_ENABLED"])
        for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
            self.assertNotIn("CRUX_ALERT_DELIVERY_ENABLED", self.services[service]["environment"])
        self.assertEqual(self.services["api"]["environment"]["EMAIL_BACKEND"], "${EMAIL_BACKEND:-}")
        for service in ("api", "worker-default"):
            self.assertEqual(self.services[service]["environment"]["EMAIL_DELIVERY_ENABLED"], "1")
        for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
            self.assertEqual(self.services[service]["environment"]["EMAIL_DELIVERY_ENABLED"], "0")
            self.assertEqual(self.services[service]["environment"]["EMAIL_BACKEND"],
                             "django.core.mail.backends.dummy.EmailBackend")
        for key in ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL"):
            self.assertEqual(example[key], "")
            for service in ("api", "worker-default"):
                self.assertEqual(self.services[service]["environment"][key], "${" + key + ":-}")
            for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
                self.assertNotIn(key, self.services[service]["environment"])
        self.assertEqual(example["EMAIL_PORT"], "")
        self.assertEqual(self.services["api"]["environment"]["EMAIL_PORT"], "${EMAIL_PORT:-0}")
        self.assertEqual(self.services["worker-default"]["environment"]["EMAIL_PORT"], "${EMAIL_PORT:-0}")
        for key in ("SES_FEEDBACK_QUEUE_URL", "SES_FEEDBACK_TOPIC_ARN"):
            self.assertEqual(example[key], "")
            for service in ("api", "worker-default", "worker-ai", "worker-crawl", "worker-audit", "beat"):
                self.assertNotIn(key, self.services[service]["environment"])
        feedback_overlay = yaml.safe_load((ROOT / "deploy/compose.feedback-worker.yaml").read_text())["services"]
        self.assertEqual(set(feedback_overlay), {"worker-default"})
        for key in ("SES_FEEDBACK_QUEUE_URL", "SES_FEEDBACK_TOPIC_ARN"):
            self.assertIn(":?", feedback_overlay["worker-default"]["environment"][key])
        self.assertEqual(feedback_overlay["worker-default"]["networks"], ["outbound"])
        self.assertEqual(feedback_overlay["worker-default"]["environment"]["FEEDBACK_WORKER_HOST"], "1")
        self.assertEqual(feedback_overlay["worker-default"]["environment"]["POSTGRES_SSLMODE"], "verify-full")
        self.assertEqual(feedback_overlay["worker-default"]["environment"]["ARTIFACT_STORAGE_BACKEND"], "s3")
        self.assertIn(":?", feedback_overlay["worker-default"]["environment"]["ARTIFACT_S3_BUCKET"])
        self.assertEqual(len(feedback_overlay["worker-default"]["volumes"]), 2)
        self.assertTrue(all(mount.endswith(":ro") for mount in feedback_overlay["worker-default"]["volumes"]))
        for key in ("POSTGRES_HOST", "CELERY_BROKER_URL", "DJANGO_CACHE_URL"):
            self.assertIn(":?", feedback_overlay["worker-default"]["environment"][key])
        queue_policy = json.loads((ROOT / "deploy/ses-feedback-queue-policy.json").read_text())
        publisher = queue_policy["Statement"][0]
        self.assertEqual(publisher["Principal"], {"Service": "sns.amazonaws.com"})
        self.assertEqual(publisher["Action"], "sqs:SendMessage")
        self.assertEqual(publisher["Condition"]["ArnEquals"]["aws:SourceArn"], "${SES_FEEDBACK_TOPIC_ARN}")
        self.assertEqual(publisher["Condition"]["StringEquals"]["aws:SourceAccount"], "${AWS_ACCOUNT_ID}")
        self.assertEqual(queue_policy["Statement"][1]["Condition"]["ArnNotEquals"]["aws:SourceArn"],
                         "${SES_FEEDBACK_TOPIC_ARN}")
        worker_policy = json.loads((ROOT / "deploy/ses-feedback-worker-policy.json").read_text())
        self.assertEqual(set(worker_policy["Statement"][0]["Action"]),
                         {"sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"})
        self.assertEqual(publisher["Resource"], worker_policy["Statement"][0]["Resource"])
        app_deny = json.loads((ROOT / "deploy/iam-app-host-deny-feedback.json").read_text())["Statement"][0]
        self.assertEqual(app_deny["Effect"], "Deny")
        self.assertEqual(set(app_deny["Action"]), set(worker_policy["Statement"][0]["Action"]))
        self.assertEqual(app_deny["Resource"], worker_policy["Statement"][0]["Resource"])
        trust = json.loads((ROOT / "deploy/iam-feedback-worker-trust.json").read_text())["Statement"][0]
        self.assertEqual(trust["Principal"], {"Service": "ec2.amazonaws.com"})
        self.assertEqual(trust["Action"], "sts:AssumeRole")
        artifacts = json.loads((ROOT / "deploy/iam-backend-artifacts-policy.json").read_text())["Statement"]
        self.assertEqual(artifacts[0]["Resource"], "arn:aws:s3:::${PRIVATE_ARTIFACT_BUCKET}")
        self.assertEqual(artifacts[0]["Condition"]["StringLike"]["s3:prefix"],
                         ["${ARTIFACT_PREFIX}", "${ARTIFACT_PREFIX}/*"])
        self.assertEqual(artifacts[1]["Resource"],
                         "arn:aws:s3:::${PRIVATE_ARTIFACT_BUCKET}/${ARTIFACT_PREFIX}/*")
        image_pull = json.loads((ROOT / "deploy/iam-backend-image-pull-policy.json").read_text())["Statement"]
        self.assertEqual(image_pull[0], {"Sid": "EcrAuthenticationOnly", "Effect": "Allow",
                                         "Action": "ecr:GetAuthorizationToken", "Resource": "*"})
        self.assertEqual(image_pull[1]["Resource"], "${BACKEND_ECR_REPOSITORY_ARN}")
        storage = json.loads((ROOT / "deploy/private-storage-stack.json").read_text())["Resources"]
        self.assertEqual(set(storage), {"ArtifactBucket", "BackupBucket", "ReleaseBucket"})
        for name in storage:
            bucket = storage[name]
            self.assertEqual(bucket["DeletionPolicy"], "Retain")
            self.assertTrue(all(bucket["Properties"]["PublicAccessBlockConfiguration"].values()))
            self.assertEqual(bucket["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
                             ["ServerSideEncryptionByDefault"]["SSEAlgorithm"], "AES256")
        backup_lifecycle = storage["BackupBucket"]["Properties"]["LifecycleConfiguration"]["Rules"][0]
        self.assertEqual(backup_lifecycle["ExpirationInDays"], 30)
        self.assertEqual(backup_lifecycle["NoncurrentVersionExpiration"]["NoncurrentDays"], 1)
        self.assertEqual(storage["ReleaseBucket"]["Properties"]["VersioningConfiguration"]["Status"], "Enabled")
        artifact_lifecycle = storage["ArtifactBucket"]["Properties"]["LifecycleConfiguration"]["Rules"][0]
        self.assertEqual(artifact_lifecycle["NoncurrentVersionExpiration"]["NoncurrentDays"], 1)
        self.assertNotIn("ExpirationInDays", artifact_lifecycle)  # Current customer data does not age out while active.
        roles = json.loads((ROOT / "deploy/backend-host-roles-stack.json").read_text())["Resources"]
        app = roles["AppHostRole"]["Properties"]
        feedback = roles["FeedbackWorkerRole"]["Properties"]
        app_queue = app["Policies"][0]["PolicyDocument"]["Statement"][0]
        worker_queue = feedback["Policies"][0]["PolicyDocument"]["Statement"][0]
        self.assertEqual(app_queue["Effect"], "Deny")
        self.assertEqual(worker_queue["Effect"], "Allow")
        self.assertEqual(app_queue["Resource"], worker_queue["Resource"])
        self.assertEqual(worker_queue["Resource"], {"Ref": "FeedbackQueueArn"})
        self.assertEqual(set(app_queue["Action"]), set(worker_queue["Action"]))
        self.assertEqual(roles["AppHostProfile"]["Properties"]["Roles"], [{"Ref": "AppHostRole"}])
        self.assertEqual(roles["FeedbackWorkerProfile"]["Properties"]["Roles"], [{"Ref": "FeedbackWorkerRole"}])
        for role in (app, feedback):
            self.assertEqual(role["AssumeRolePolicyDocument"]["Statement"][0]["Principal"],
                             {"Service": "ec2.amazonaws.com"})
            self.assertTrue(all("sqs:" not in str(policy)
                                for policy in role["Policies"][1:]))
            grants = role["Policies"][1]["PolicyDocument"]["Statement"]
            release_grant = next(grant for grant in grants if grant.get("Resource") ==
                                 {"Fn::Sub": "arn:aws:s3:::${PrivateReleaseBucketName}/releases/*"})
            self.assertEqual(release_grant["Action"], "s3:GetObject")
            artifact_objects = next(grant for grant in grants if grant.get("Resource") ==
                                    {"Fn::Sub": "arn:aws:s3:::${PrivateArtifactBucketName}/${ArtifactPrefix}/*"})
            self.assertIn("s3:DeleteObject", artifact_objects["Action"])
            self.assertEqual("s3:DeleteObjectVersion" in artifact_objects["Action"], role is app)
            self.assertEqual(any(grant.get("Action") == "s3:ListBucketVersions" for grant in grants), role is app)
        app_ecr = app["Policies"][1]["PolicyDocument"]["Statement"][-1]
        worker_ecr = feedback["Policies"][1]["PolicyDocument"]["Statement"][-1]
        backup_grant = next(grant for grant in app["Policies"][1]["PolicyDocument"]["Statement"]
                            if grant.get("Resource") == {"Fn::Sub": "arn:aws:s3:::${PrivateBackupBucketName}/backups/*"})
        self.assertEqual(set(backup_grant["Action"]), {"s3:PutObject", "s3:GetObject"})
        self.assertNotIn("PrivateBackupBucketName", str(feedback))
        self.assertTrue(any("OrganicSEOOps/Backup" in grant.get("Condition", {}).get(
            "StringEquals", {}).get("cloudwatch:namespace", [])
            for grant in app["Policies"][1]["PolicyDocument"]["Statement"]))
        self.assertTrue(any("OrganicSEOOps/Jobs" in grant.get("Condition", {}).get(
            "StringEquals", {}).get("cloudwatch:namespace", [])
            for grant in app["Policies"][1]["PolicyDocument"]["Statement"]))
        self.assertFalse(any("OrganicSEOOps/Backup" in grant.get("Condition", {}).get(
            "StringEquals", {}).get("cloudwatch:namespace", [])
            for grant in feedback["Policies"][1]["PolicyDocument"]["Statement"]))
        self.assertNotIn("OrganicSEOOps/Jobs", str(feedback))
        self.assertEqual(app_ecr["Resource"], [{"Ref": "BackendRepositoryArn"}, {"Ref": "RendererRepositoryArn"},
                                                {"Ref": "PostgresRepositoryArn"}, {"Ref": "ProxyRepositoryArn"}])
        self.assertEqual(worker_ecr["Resource"], {"Ref": "BackendRepositoryArn"})
        hosts = json.loads((ROOT / "deploy/backend-host-stack.json").read_text())["Resources"]
        self.assertEqual(hosts["AppDataSecurityGroup"]["Type"], "AWS::EC2::SecurityGroup")
        for service, port in (("FeedbackToPostgres", 15432), ("FeedbackToRedis", 16379)):
            rule = hosts[service]["Properties"]
            self.assertEqual(rule["SourceSecurityGroupId"], {"Ref": "FeedbackSecurityGroup"})
            self.assertEqual((rule["FromPort"], rule["ToPort"]), (port, port))
        for name, profile in (("AppHost", "AppInstanceProfileName"),
                              ("FeedbackHost", "FeedbackInstanceProfileName")):
            host = hosts[name]["Properties"]
            self.assertEqual(host["IamInstanceProfile"], {"Ref": profile})
            self.assertFalse(host["NetworkInterfaces"][0]["AssociatePublicIpAddress"])
            self.assertEqual(host["MetadataOptions"]["HttpTokens"], "required")
            self.assertTrue(host["BlockDeviceMappings"][0]["Ebs"]["Encrypted"])
        self.assertTrue(hosts["AppPostgresVolume"]["Properties"]["Encrypted"])
        self.assertEqual(hosts["AppPostgresVolume"]["DeletionPolicy"], "Retain")
        repositories = json.loads((ROOT / "deploy/backend-ecr-stack.json").read_text())["Resources"]
        self.assertEqual(set(repositories), {"BackendRepository", "RendererRepository", "PostgresRepository", "ProxyRepository"})
        for repo in repositories.values():
            self.assertEqual(repo["DeletionPolicy"], "Retain")
            self.assertEqual(repo["Properties"]["ImageTagMutability"], "IMMUTABLE")
            self.assertTrue(repo["Properties"]["ImageScanningConfiguration"]["ScanOnPush"])
            self.assertEqual(repo["Properties"]["EncryptionConfiguration"]["EncryptionType"], "AES256")
        topic_policy = json.loads((ROOT / "deploy/ses-feedback-topic-policy.json").read_text())
        ses = topic_policy["Statement"][0]
        self.assertEqual(ses["Principal"], {"Service": "ses.amazonaws.com"})
        self.assertEqual(ses["Action"], "sns:Publish")
        self.assertEqual(ses["Condition"]["StringEquals"]["aws:SourceAccount"], "${AWS_ACCOUNT_ID}")
        self.assertEqual(ses["Condition"]["ArnEquals"]["aws:SourceArn"], "${SES_IDENTITY_ARN}")
        self.assertEqual(topic_policy["Statement"][1]["Condition"]["ArnNotEquals"]["aws:SourceArn"],
                         "${SES_IDENTITY_ARN}")
        stack = json.loads((ROOT / "deploy/ses-feedback-stack.json").read_text())["Resources"]
        self.assertEqual(stack["FeedbackTopicPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
                         ["Condition"]["ArnEquals"]["aws:SourceArn"], {"Ref": "SesIdentityArn"})
        self.assertEqual(stack["FeedbackQueuePolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
                         ["Condition"]["ArnEquals"]["aws:SourceArn"], {"Ref": "FeedbackTopic"})
        for name in ("FeedbackQueue", "FeedbackDeadLetterQueue"):
            self.assertTrue(stack[name]["Properties"]["SqsManagedSseEnabled"])
        self.assertEqual(stack["FeedbackQueue"]["Properties"]["RedrivePolicy"]["maxReceiveCount"], 5)
        self.assertFalse(stack["FeedbackSubscription"]["Properties"]["RawMessageDelivery"])
        self.assertEqual(self.services["api"]["environment"]["MFA_ENCRYPTION_KEYS"], "${MFA_ENCRYPTION_KEYS:-}")
        for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI", "GOOGLE_OAUTH_ENCRYPTION_KEYS"):
            self.assertEqual(example[key], "")
            self.assertEqual(self.services["api"]["environment"][key], "${" + key + ":-}")
            for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
                self.assertNotIn(key, self.services[service]["environment"])
            self.assertEqual(self.services["worker-default"]["environment"][key], "${" + key + ":-}")
        for key in ("GOOGLE_ANALYTICS_REDIRECT_URI", "GOOGLE_ANALYTICS_ENCRYPTION_KEYS"):
            self.assertEqual(example[key], "")
            self.assertEqual(self.services["api"]["environment"][key], "${" + key + ":-}")
            for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
                self.assertNotIn(key, self.services[service]["environment"])
        self.assertEqual(self.services["worker-default"]["environment"]["GOOGLE_ANALYTICS_ENCRYPTION_KEYS"],
                         "${GOOGLE_ANALYTICS_ENCRYPTION_KEYS:-}")
        self.assertNotIn("GOOGLE_ANALYTICS_REDIRECT_URI", self.services["worker-default"]["environment"])
        for service in ("api", "worker-default", "worker-crawl", "worker-audit", "beat"):
            self.assertNotIn("OPENAI_API_KEY", self.services[service]["environment"])
            self.assertNotIn("OPENAI_COMPATIBLE_API_KEY", self.services[service]["environment"])
        self.assertEqual(example["PROVIDER_ENCRYPTION_KEYS"], "")
        self.assertEqual(example["PADDLE_ENCRYPTION_KEYS"], "")
        self.assertEqual(example["PADDLE_ENVIRONMENT"], "")
        self.assertEqual(self.services["api"]["environment"]["PADDLE_ENVIRONMENT"], "${PADDLE_ENVIRONMENT:-}")
        self.assertEqual(example["PADDLE_CHECKOUT_URL"], "")
        self.assertEqual(self.services["api"]["environment"]["PADDLE_CHECKOUT_URL"], "${PADDLE_CHECKOUT_URL:-}")
        self.assertEqual(self.services["api"]["environment"]["PADDLE_ENCRYPTION_KEYS"],
                         "${PADDLE_ENCRYPTION_KEYS:-}")
        for service in ("worker-ai", "worker-crawl", "worker-audit", "beat"):
            self.assertNotIn("PADDLE_ENCRYPTION_KEYS", self.services[service]["environment"])
            self.assertNotIn("PADDLE_ENVIRONMENT", self.services[service]["environment"])
            self.assertNotIn("PADDLE_CHECKOUT_URL", self.services[service]["environment"])
        for key in ("PADDLE_ENCRYPTION_KEYS", "PADDLE_ENVIRONMENT"):
            self.assertEqual(self.services["worker-default"]["environment"][key], "${" + key + ":-}")
        self.assertNotIn("PADDLE_CHECKOUT_URL", self.services["worker-default"]["environment"])
        for service in ("worker-default", "worker-crawl", "worker-audit", "beat"):
            self.assertNotIn("PROVIDER_ENCRYPTION_KEYS", self.services[service]["environment"])
        for service in ("api", "worker-ai"):
            self.assertEqual(self.services[service]["environment"]["PROVIDER_ENCRYPTION_KEYS"],
                             "${PROVIDER_ENCRYPTION_KEYS:-}")
        self.assertEqual(example["PERFORMANCE_ENCRYPTION_KEYS"], "")
        for service in ("worker-default", "worker-crawl", "worker-ai", "beat"):
            self.assertNotIn("PERFORMANCE_ENCRYPTION_KEYS", self.services[service]["environment"])
        for service in ("api", "worker-audit"):
            self.assertEqual(self.services[service]["environment"]["PERFORMANCE_ENCRYPTION_KEYS"],
                             "${PERFORMANCE_ENCRYPTION_KEYS:-}")
        self.assertEqual(example["GOOGLE_PERFORMANCE_API_KEY"], "")
        self.assertEqual(self.services["worker-audit"]["environment"]["GOOGLE_PERFORMANCE_API_KEY"], "${GOOGLE_PERFORMANCE_API_KEY:-}")
        for service in ("api", "worker-default", "worker-ai", "worker-crawl", "beat"):
            self.assertNotIn("GOOGLE_PERFORMANCE_API_KEY", self.services[service]["environment"])
        self.assertEqual(self.services["worker-ai"]["environment"]["OPENAI_API_KEY"], "${OPENAI_API_KEY:-}")
        self.assertEqual(
            self.services["worker-ai"]["environment"]["OPENAI_COMPATIBLE_API_KEY"],
            "${OPENAI_COMPATIBLE_API_KEY:-}",
        )
        frontend_source = "\n".join(
            path.read_text() for path in (ROOT / "frontend/src").rglob("*") if path.is_file()
        )
        for key in (
            "DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "ARTIFACT_S3_BUCKET", "AWS_SECRET_ACCESS_KEY",
            "OPENAI_API_KEY", "OPENAI_COMPATIBLE_API_KEY", "PROVIDER_ENCRYPTION_KEYS", "PERFORMANCE_ENCRYPTION_KEYS",
            "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_ENCRYPTION_KEYS", "GOOGLE_PERFORMANCE_API_KEY",
            "GOOGLE_ANALYTICS_ENCRYPTION_KEYS", "PADDLE_ENCRYPTION_KEYS",
        ):
            self.assertNotIn(key, frontend_source)
        self.assertEqual(self.services["api"]["build"], {"context": "./backend"})
        dockerfile = (ROOT / "backend/Dockerfile").read_text()
        self.assertNotIn("COPY . ", dockerfile)
        self.assertNotIn("COPY .env", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("pip --python /opt/venv check", dockerfile)
        self.assertIn("DJANGO_DEBUG=1 EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend", dockerfile)
        self.assertIn("COPY jobs/ ./jobs/", dockerfile)
        self.assertIn("COPY providers/ ./providers/", dockerfile)
        self.assertIn("COPY integrations/ ./integrations/", dockerfile)
        self.assertIn("!jobs/**", (ROOT / "backend/.dockerignore").read_text())
        self.assertIn("!providers/**", (ROOT / "backend/.dockerignore").read_text())
        self.assertIn("!integrations/**", (ROOT / "backend/.dockerignore").read_text())
        self.assertIn("USER 70:70", (ROOT / "deploy/postgres/Dockerfile").read_text())
        self.assertEqual((ROOT / "backend/.dockerignore").read_text().splitlines()[1], "*")

    def test_production_private_data_overlay_requires_vpc_bind_tls_and_acl(self):
        source = (ROOT / "deploy/compose.production-private.yaml").read_text()
        self.assertIn("volumes: !override", source)
        self.assertIn("build: !reset null", source)
        production = yaml.safe_load(source.replace("volumes: !override", "volumes:").replace(
            "build: !reset null", "build: null"))["services"]
        self.assertEqual(set(production), {"postgres", "redis"})
        db, broker = production["postgres"], production["redis"]
        self.assertEqual(db["image"], "${POSTGRES_IMAGE:?Set reviewed PostgreSQL ECR digest}")
        self.assertIsNone(db["build"])
        self.assertEqual(db["ports"], ["${PRIVATE_DB_BIND_IP:?Set owned VPC private address}:15432:5432"])
        self.assertEqual(broker["ports"], ["${PRIVATE_REDIS_BIND_IP:?Set owned VPC private address}:16379:6379"])
        self.assertIn("ssl=on", db["command"])
        self.assertIn("hba_file=/run/organicseoops/pg_hba.conf", db["command"])
        self.assertEqual(db["volumes"][0],
                         "${PRIVATE_POSTGRES_DATA_DIR:?Set retained mounted EBS PostgreSQL directory}:/var/lib/postgresql")
        self.assertTrue(all(mount.endswith(":ro") for mount in db["volumes"][1:] + broker["volumes"]))
        self.assertIn("PRIVATE_REDIS_HEALTH_PASSWORD:?", broker["environment"]["REDISCLI_AUTH"])
        self.assertIn("--tls", broker["healthcheck"]["test"][1])
        redis_conf = (ROOT / "deploy/redis.production.conf").read_text()
        for directive in ("port 0", "tls-port 6379", "tls-auth-clients no",
                          "aclfile /run/organicseoops/redis.acl", "protected-mode yes"):
            self.assertIn(directive, redis_conf)
        pg_hba = (ROOT / "deploy/postgres/pg_hba.production.conf").read_text()
        self.assertIn("hostssl all all 10.0.0.0/8 scram-sha-256", pg_hba)
        self.assertIn("hostnossl all all 0.0.0.0/0 reject", pg_hba)

    def test_production_app_host_has_only_tls_clients_and_no_feedback_worker_role(self):
        source = (ROOT / "deploy/compose.production-app.yaml").read_text()
        self.assertIn("build: !reset null", source)
        services = yaml.safe_load(source.replace("build: !reset null", "build: null"))["services"]
        self.assertEqual(set(services), {"api", "worker-ai", "worker-crawl", "worker-audit", "beat", "worker-default", "proxy", "renderer"})
        self.assertEqual(services["renderer"]["image"], "${RENDERER_IMAGE:?Set reviewed renderer ECR digest}")
        self.assertIsNone(services["renderer"]["build"])
        self.assertEqual(services["proxy"]["image"], "${PROXY_IMAGE:?Set reviewed proxy ECR digest}")
        self.assertIsNone(services["proxy"]["build"])
        self.assertEqual(services["worker-default"]["profiles"], ["feedback-only"])
        for service in ("api", "worker-ai", "worker-crawl", "worker-audit", "beat"):
            row = services[service]
            self.assertEqual(row["environment"]["PRODUCTION_APP_HOST"], "1")
            self.assertEqual(row["environment"]["POSTGRES_SSLMODE"], "verify-full")
            self.assertEqual(row["environment"]["ARTIFACT_STORAGE_BACKEND"], "s3")
            self.assertIn(":?", row["environment"]["CELERY_BROKER_URL"])
            self.assertIn(":?", row["environment"]["DJANGO_CACHE_URL"])
            self.assertEqual(len(row["volumes"]), 2)
            self.assertTrue(all(mount.endswith(":ro") for mount in row["volumes"]))
            self.assertNotIn("SES_FEEDBACK_QUEUE_URL", row["environment"])

    def test_release_override_uses_one_explicit_backend_image_on_both_hosts(self):
        source = (ROOT / "deploy/compose.release.yaml").read_text()
        self.assertEqual(source.count("build: !reset null"), 6)
        class ReleaseLoader(yaml.SafeLoader):
            pass
        ReleaseLoader.add_constructor("!reset", lambda loader, node: None)
        services = yaml.load(source, Loader=ReleaseLoader)["services"]
        self.assertEqual(set(services),
                         {"api", "worker-default", "worker-ai", "worker-crawl", "worker-audit", "beat"})
        for service in services.values():
            self.assertEqual(service, {"image": "${BACKEND_IMAGE:?Set the reviewed backend ECR image digest}",
                                       "build": None})

    def test_development_override_is_isolated_and_source_mounted(self):
        services = self.development["services"]
        self.assertEqual(self.development["name"], "organicseoops-dev")
        backend = {"api", "worker-default", "worker-ai", "worker-crawl", "worker-audit", "beat"}
        self.assertEqual(set(services), backend | {"renderer", "postgres", "redis", "proxy"})
        expected_mounts = {
            "./backend/manage.py:/app/manage.py:ro",
            "./backend/config:/app/config:ro",
            "./backend/accounts:/app/accounts:ro",
            "./backend/tenancy:/app/tenancy:ro",
            "./backend/jobs:/app/jobs:ro",
            "./backend/providers:/app/providers:ro",
            "./backend/integrations:/app/integrations:ro",
        }
        for name in backend:
            self.assertEqual(services[name]["image"], "organicseoops-backend:development")
            self.assertEqual(set(services[name]["volumes"]), expected_mounts)
            self.assertNotIn("ports", services[name])
        self.assertEqual(services["api"]["command"], ["python", "manage.py", "runserver", "0.0.0.0:8000"])
        self.assertEqual(services["renderer"]["image"], "organicseoops-renderer:development")
        self.assertEqual(services["proxy"]["image"], "organicseoops-proxy:development")
        self.assertEqual(self.services["proxy"]["image"], "organicseoops-proxy:local")
        self.assertEqual(self.services["proxy"]["build"], {"context": "./deploy/proxy"})
        self.assertEqual(services["postgres"]["image"], "organicseoops-postgres:development")
        self.assertEqual(services["postgres"]["ports"], ["127.0.0.1:15432:5432"])
        self.assertEqual(services["redis"]["ports"], ["127.0.0.1:16379:6379"])

        script = (ROOT / "backend-dev.sh").read_text()
        self.assertIn("project=organicseoops-dev", script)
        self.assertIn("compose build api postgres renderer proxy", script)
        self.assertIn("compose build api renderer proxy", script)
        self.assertIn("backend_services=(api proxy ", script)
        self.assertNotIn("proxy", script.split("worker_services=(", 1)[1].split(")", 1)[0])
        self.assertIn("proxy_port=18000", script)
        self.assertIn('env_file="$root/backend/.env"', script)
        self.assertNotIn("/tmp/opencode", script)
        self.assertIn('-f "$root/compose.development.yaml"', script)
        self.assertIn("-u EMAIL_BACKEND", script)
        for key, value in {"PUBLIC_CONTACT_ENABLED": "${PUBLIC_CONTACT_ENABLED:-0}",
                           "PUBLIC_CONTACT_RETENTION_DAYS": "${PUBLIC_CONTACT_RETENTION_DAYS:-}"}.items():
            self.assertEqual(self.services["api"]["environment"][key], value)
            for name in ("worker-default", "worker-ai", "worker-crawl", "worker-audit", "beat", "renderer"):
                self.assertNotIn(key, self.services[name].get("environment", {}))
            self.assertIn(f"-u {key}", script[script.index("compose() {"):script.index("existing_state() {")])
        preflight = script[script.index("preflight() {"):script.index("start_infrastructure() {")]
        for key in (
            "DJANGO_SECRET_KEY", "MFA_ENCRYPTION_KEYS", "PROVIDER_ENCRYPTION_KEYS", "PERFORMANCE_ENCRYPTION_KEYS", "OPENAI_API_KEY", "OPENAI_COMPATIBLE_API_KEY",
            "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI", "GOOGLE_OAUTH_ENCRYPTION_KEYS",
            "GOOGLE_PERFORMANCE_API_KEY",
            "EMAIL_BACKEND", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL",
            "SES_FEEDBACK_QUEUE_URL", "SES_FEEDBACK_TOPIC_ARN", "FEEDBACK_WORKER_HOST",
            "POSTGRES_SSLMODE", "POSTGRES_SSLROOTCERT", "REDIS_TLS_CA_FILE",
            "POSTGRES_PASSWORD", "ARTIFACT_S3_BUCKET",
            "PUBLIC_CONTACT_ENABLED", "PUBLIC_CONTACT_RETENTION_DAYS",
            "CUSTOMER_EXPORT_COPY_POLICY_REFERENCE", "CUSTOMER_EXPORT_COPY_LIFETIME_DAYS",
            "SELF_SERVICE_CLOSURE_ENABLED", "SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED",
            "PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE", "PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS",
            "PERSONAL_IDENTITY_RETENTION_KEY",
        ):
            self.assertIn(f"-u {key}", preflight)
        self.assertIn('$app/migrations:/app/$app/migrations:rw', script)
        self.assertIn("test accounts config tenancy jobs providers integrations --noinput", script)
        self.assertLess(script.index("preflight", script.index("makemigrations)")), script.index("start_infrastructure", script.index("makemigrations)")))
        test_lock = script[script.index("lock_test_database() {"):script.index("case ")]
        self.assertIn('/tmp/organicseoops-${UID}-dev-test.lock', test_lock)
        self.assertIn("flock --nonblock", test_lock)
        self.assertIn("Another backend test is using the shared test database", test_lock)
        quickmanage = script[script.index("  quickmanage)"):script.index("  quicktest)")]
        self.assertIn("check|showmigrations", quickmanage)
        self.assertIn("quickmanage makemigrations requires both --check and --dry-run", quickmanage)
        self.assertIn("quickmanage migrate requires --check", quickmanage)
        self.assertIn('compose exec -T api python manage.py "$@"', quickmanage)
        self.assertIn("require_running_api", quickmanage)
        self.assertNotIn("start_infrastructure", quickmanage)
        self.assertNotIn("compose up", quickmanage)
        quicktest = script[script.index("  quicktest)"):script.index("  test)")]
        self.assertIn("require_running_api", quicktest)
        self.assertIn("lock_test_database", quicktest)
        self.assertIn('compose exec -T api python manage.py test "$@" --keepdb --noinput', quicktest)
        self.assertNotIn("start_infrastructure", quicktest)
        self.assertNotIn("compose up", quicktest)
        self.assertEqual(script.count("lock_test_database"), 4)

        package = json.loads((ROOT / "frontend/package.json").read_text())
        self.assertIn("--proxy-config proxy.conf.json", package["scripts"]["start"])
        proxy = json.loads((ROOT / "frontend/proxy.conf.json").read_text())
        self.assertEqual(set(proxy), {"/api", "/_allauth", "/admin", "/static"})
        self.assertTrue(all(value["target"] == "http://127.0.0.1:18000" for value in proxy.values()))

        angular = json.loads((ROOT / "frontend/angular.json").read_text())
        build = angular["projects"]["organicseoops"]["architect"]["build"]
        self.assertEqual(build["configurations"]["production"]["fileReplacements"], [{
            "replace": "src/environments/environment.ts",
            "with": "src/environments/environment.prod.ts",
        }])
        for filename in ("environment.ts", "environment.prod.ts"):
            text = (ROOT / "frontend/src/environments" / filename).read_text()
            self.assertIn("apiBase: '/api'", text)
            self.assertIn("authBase: '/_allauth/browser/v1'", text)


if __name__ == "__main__":
    unittest.main()
