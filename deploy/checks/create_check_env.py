"""Create a private backend environment; never overwrite existing state."""
import argparse
import os
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--project-name", default="organicseoops-ci")
    parser.add_argument("--proxy-port", type=int, default=18080)
    parser.add_argument("--profile", choices=("check", "development", "production"), default="check")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.project_name):
        parser.error("project name must use lowercase letters, numbers, underscores or hyphens")
    if not 1 <= args.proxy_port <= 65535:
        parser.error("proxy port must be between 1 and 65535")
    text = (ROOT / ".env.example").read_text()
    values = {
        "COMPOSE_PROJECT_NAME": args.project_name,
        "PROXY_PORT": str(args.proxy_port),
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"http://localhost:{args.proxy_port},http://127.0.0.1:{args.proxy_port}",
        "FRONTEND_ORIGIN": f"http://localhost:{args.proxy_port}",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(50),
    }
    if args.profile == "development":
        values.update(
            FRONTEND_ORIGIN="http://127.0.0.1:4200",
            DJANGO_CSRF_TRUSTED_ORIGINS="http://localhost:4200,http://127.0.0.1:4200",
        )
    elif args.profile == "production":
        # Unconfigured deployment template: never reuse or invent production secrets.
        values.update(
            COMPOSE_PROJECT_NAME="organicseoops-prod", PROXY_PORT="18001",
            DJANGO_DEBUG="0", DJANGO_SECRET_KEY="", POSTGRES_PASSWORD="",
            DJANGO_ALLOWED_HOSTS="", DJANGO_CSRF_TRUSTED_ORIGINS="",
            FRONTEND_ORIGIN="https://app.example.invalid", EMAIL_BACKEND="",
            ARTIFACT_STORAGE_BACKEND="s3",
        )
    else:
        values.update(
            POSTGRES_HOST="postgres", POSTGRES_PORT="5432",
            DJANGO_CACHE_URL="redis://redis:6379/1",
            CELERY_BROKER_URL="redis://redis:6379/0",
        )
    for key, value in values.items():
        text, count = re.subn(rf"(?m)^{key}=.*$", lambda match: f"{key}={value}", text)
        if count != 1:
            parser.error(f"template must contain exactly one {key} entry")
    fd = os.open(args.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(text)
    print("Private backend environment created; values not displayed.")


if __name__ == "__main__":
    main()
