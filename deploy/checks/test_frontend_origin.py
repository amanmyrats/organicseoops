"""Static source contract: the intended browser host has only two dynamic API route spaces."""

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
NO_CACHE = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
ALL_VIEWER_AND_CLOUDFRONT = "33f36d7e-f396-46d9-90e0-52428a34d9dc"


class FrontendOriginContractTests(unittest.TestCase):
    def test_https_api_origin_is_only_from_cloudfront_and_private_alb_to_proxy(self):
        template = json.loads((ROOT / "deploy/api-origin-alb-stack.json").read_text())
        stack = template["Resources"]
        self.assertEqual(template["Parameters"]["ApiInstanceId"]["Default"], "")
        self.assertIn("HasApiInstance", template["Conditions"])
        self.assertEqual(stack["ApiAlb"]["Properties"]["Scheme"], "internet-facing")
        self.assertEqual(stack["ApiHttpsListener"]["Properties"]["Protocol"], "HTTPS")
        self.assertEqual(stack["ApiHttpsListener"]["Properties"]["Port"], 443)
        self.assertEqual(stack["ApiTargetGroup"]["Properties"]["HealthCheckPath"], "/api/health/")
        ingress = stack["AlbSecurityGroup"]["Properties"]["SecurityGroupIngress"]
        self.assertEqual(ingress, [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                                   "SourcePrefixListId": {"Ref": "CloudFrontOriginPrefixListId"}}])
        backend = stack["ApiHostHttpFromAlb"]["Properties"]
        self.assertEqual(backend["SourceSecurityGroupId"], {"Ref": "AlbSecurityGroup"})
        self.assertEqual((backend["FromPort"], backend["ToPort"]), (80, 80))
        proxy = (ROOT / "deploy/nginx.production.conf").read_text()
        self.assertIn("real_ip_header CloudFront-Viewer-Address", proxy)
        self.assertIn('if ($http_cloudfront_viewer_address = "") { return 403; }', proxy)
        self.assertIn("proxy_set_header X-Forwarded-Proto https", proxy)
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr", proxy)
        app = yaml.safe_load((ROOT / "deploy/compose.production-app.yaml").read_text().replace(
            "build: !reset null", "build: null"))["services"]
        self.assertIn(":?", app["proxy"]["ports"][0])
        self.assertEqual(app["proxy"]["volumes"], ["./deploy/nginx.production.conf:/etc/nginx/conf.d/default.conf:ro"])

    def test_frontend_deploy_oidc_trust_and_resource_scope_are_exact(self):
        trust = json.loads((ROOT / "deploy/iam-frontend-deploy-trust.json").read_text())["Statement"][0]
        self.assertEqual(trust["Action"], "sts:AssumeRoleWithWebIdentity")
        self.assertEqual(trust["Principal"], {
            "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
        })
        claims = trust["Condition"]["StringEquals"]
        self.assertEqual(claims["token.actions.githubusercontent.com:aud"], "sts.amazonaws.com")
        self.assertEqual(claims["token.actions.githubusercontent.com:sub"],
                         "repo:${GITHUB_OWNER}/${GITHUB_REPO}:ref:refs/heads/${PRODUCTION_BRANCH}")
        policy = json.loads((ROOT / "deploy/iam-frontend-deploy-policy.json").read_text())["Statement"]
        self.assertEqual({row["Resource"] for row in policy}, {
            "arn:aws:s3:::${FRONTEND_BUCKET_NAME}", "arn:aws:s3:::${FRONTEND_BUCKET_NAME}/*",
            "arn:aws:cloudfront::${AWS_ACCOUNT_ID}:distribution/${FRONTEND_DISTRIBUTION_ID}",
        })
        self.assertEqual(set(policy[2]["Action"]), {"cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"})

    def test_private_static_origin_and_explicit_uncached_same_origin_browser_paths(self):
        stack = json.loads((ROOT / "deploy/frontend-origin-stack.json").read_text())
        resources = stack["Resources"]
        bucket = resources["FrontendBucket"]["Properties"]
        self.assertTrue(all(bucket["PublicAccessBlockConfiguration"].values()))
        self.assertEqual(bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
                         ["ServerSideEncryptionByDefault"]["SSEAlgorithm"], "AES256")
        self.assertEqual(resources["FrontendBucket"]["DeletionPolicy"], "Retain")
        oac = resources["FrontendOac"]["Properties"]["OriginAccessControlConfig"]
        self.assertEqual((oac["SigningBehavior"], oac["SigningProtocol"]), ("always", "sigv4"))
        access = resources["FrontendBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
        self.assertEqual(access["Principal"], {"Service": "cloudfront.amazonaws.com"})
        self.assertIn("SourceArn", next(iter(access["Condition"]["StringEquals"])))

        distribution = resources["FrontendDistribution"]["Properties"]["DistributionConfig"]
        self.assertNotIn("CustomErrorResponses", distribution)
        self.assertEqual({item["Id"] for item in distribution["Origins"]}, {"private-static", "django-https"})
        api = next(item for item in distribution["Origins"] if item["Id"] == "django-https")
        self.assertEqual(api["CustomOriginConfig"]["OriginProtocolPolicy"], "https-only")
        self.assertEqual(distribution["DefaultCacheBehavior"]["TargetOriginId"], "private-static")
        self.assertEqual(distribution["DefaultCacheBehavior"]["AllowedMethods"], ["GET", "HEAD", "OPTIONS"])
        behaviors = distribution["CacheBehaviors"]
        self.assertEqual({item["PathPattern"] for item in behaviors},
                         {"/api/*", "/_allauth/*", "/admin/*", "/static/*"})
        for behavior in behaviors:
            self.assertEqual(behavior["TargetOriginId"], "django-https")
            self.assertEqual(behavior["ViewerProtocolPolicy"], "https-only")
            self.assertEqual(behavior["CachePolicyId"], NO_CACHE)
            self.assertEqual(behavior["OriginRequestPolicyId"], ALL_VIEWER_AND_CLOUDFRONT)
            expected_methods = ({"GET", "HEAD", "OPTIONS"} if behavior["PathPattern"] == "/static/*"
                                else {"GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"})
            self.assertEqual(set(behavior["AllowedMethods"]), expected_methods)
            self.assertEqual(behavior["ResponseHeadersPolicyId"], {"Ref": "ApiNoStore"})
        no_store = resources["ApiNoStore"]["Properties"]["ResponseHeadersPolicyConfig"]
        self.assertEqual(no_store["CustomHeadersConfig"]["Items"][0]["Value"], "private, no-store")
        public_config = (ROOT / "frontend/src/environments/environment.prod.ts").read_text()
        self.assertIn("apiBase: '/api'", public_config)
        self.assertIn("authBase: '/_allauth/browser/v1'", public_config)
