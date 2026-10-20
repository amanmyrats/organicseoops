"""Prepare a secret-free, exact-digest SSM command; never calls AWS."""
import argparse
import json
import re
import shlex


def command(*, role, region, account, bucket, commit, bundle_sha256, backend_image, renderer_image="", postgres_image="", proxy_image="", mode="release"):
    if role not in {"app", "feedback"}:
        raise ValueError("Invalid host role")
    if mode not in {"release", "rollback"}:
        raise ValueError("Invalid release mode")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region):
        raise ValueError("Invalid AWS region")
    if not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("Invalid AWS account")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("Invalid release bucket")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[0-9a-f]{64}", bundle_sha256):
        raise ValueError("Invalid source or bundle digest")
    prefix = f"{account}.dkr.ecr.{region}.amazonaws.com/"
    for image in (backend_image, renderer_image, postgres_image, proxy_image) if role == "app" else (backend_image,):
        if not image.startswith(prefix) or not re.fullmatch(r"[a-z0-9_/-]+@sha256:[0-9a-f]{64}", image[len(prefix):]):
            raise ValueError("Image must be an exact-account/region ECR digest")
    if role == "app" and (not renderer_image or not postgres_image or not proxy_image):
        raise ValueError("App host needs renderer, PostgreSQL and proxy images")

    directory = f"/opt/organicseoops/releases/{commit}"
    bundle = f"{directory}/bundle.tar.gz"
    private_file = f"/etc/organicseoops/{role}.env.prod"
    env_file = f"{directory}/backend/.env.prod" if role == "app" else f"{directory}/backend/.env.feedback.prod"
    commands = [
        "set -eu", "umask 077", f"mkdir -p {directory}",
        f"aws s3api get-object --bucket {shlex.quote(bucket)} --key releases/{commit}.tar.gz "
        f"--region {region} {bundle} >/dev/null",
        f"printf '%s  %s\\n' {bundle_sha256} {bundle} | sha256sum --check --status",
        f"tar -xzf {bundle} -C {directory}",
        f"test -f {private_file} && test \"$(stat -c %a {private_file})\" = 600",
        f"mkdir -p {directory}/backend && ln -s {private_file} {env_file}",
        f"cd {directory}",
        f"aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin "
        f"{account}.dkr.ecr.{region}.amazonaws.com >/dev/null",
        f"BACKEND_IMAGE={shlex.quote(backend_image)} " +
        (f"RENDERER_IMAGE={shlex.quote(renderer_image)} POSTGRES_IMAGE={shlex.quote(postgres_image)} PROXY_IMAGE={shlex.quote(proxy_image)} "
         "BACKUP_VERIFIED=1 ORIGIN_DRAINED=1 " +
         ("SCHEMA_COMPATIBLE=1 " if mode == "rollback" else "") if role == "app" else "") +
        f"ENV_FILE={env_file} bash deploy/backend-release.sh {role} {mode}",
    ]
    commands.append(f"ln -sfn {directory} /opt/organicseoops/current")
    return {"commands": commands, "executionTimeout": ["3600"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("role", "region", "account", "bucket", "commit", "bundle-sha256", "backend-image"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--renderer-image", default="")
    parser.add_argument("--postgres-image", default="")
    parser.add_argument("--proxy-image", default="")
    parser.add_argument("--mode", choices=("release", "rollback"), default="release")
    args = vars(parser.parse_args())
    try:
        print(json.dumps(command(**args)))
    except ValueError as error:
        parser.error(str(error))
