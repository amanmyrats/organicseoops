"""Synthetic Bookworm-to-Alpine restore rehearsal. Never migrates user data."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE_IMAGE = "postgres:18.6-bookworm@sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650"
SETUP = "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); import django; django.setup();\n"
SNAPSHOT = """
import hashlib, json
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core import serializers
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
objects = []
for model in (get_user_model(), Group, Permission, ContentType, MigrationRecorder.Migration):
    objects.extend(model.objects.order_by('pk'))
digest = hashlib.sha256(serializers.serialize('json', objects).encode()).hexdigest()
with connection.cursor() as cursor:
    cursor.execute('SELECT datlocprovider FROM pg_database WHERE datname=current_database()')
    provider = cursor.fetchone()[0]
print(json.dumps({'digest': digest, 'users': get_user_model().objects.count(),
                  'migrations': MigrationRecorder.Migration.objects.count(), 'provider': provider}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--compose-override", help="Optional disposable image selection override")
    args = parser.parse_args()
    compose = ["docker", "compose", "--env-file", args.env_file]
    if args.compose_override:
        compose += ["-f", "compose.yaml", "-f", args.compose_override]

    def output(command):
        return subprocess.check_output(command, cwd=ROOT, text=True, timeout=120).strip()

    def api(code, host="postgres"):
        return output(compose + ["run", "--rm", "--no-deps", "-T", "-e", f"POSTGRES_HOST={host}",
                                 "api", "python", "-c", SETUP + code])

    target_id = output(compose + ["ps", "-q", "postgres"])
    target = json.loads(output(["docker", "inspect", target_id]))[0]
    project = target["Config"]["Labels"]["com.docker.compose.project"]
    if project not in {"organicseoops-ci", "organicseoops-remediation", "organicseoops-ci-atomic", "organicseoops-p13-04"}:
        raise RuntimeError("Restore checks are limited to disposable CI/remediation projects")
    started = time.monotonic()
    count = api("""
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f')")
    print(cursor.fetchone()[0])
""")
    if count != "0":
        raise RuntimeError("Target public schema must be empty; nothing was overwritten")

    networks = target["NetworkSettings"]["Networks"]
    assert len(networks) == 1 and target["Config"]["User"] == "70:70"
    source = f"{project}-restore-source"
    assert not output(["docker", "ps", "-a", "-q", "--filter", f"name=^/{source}$"]), "Existing restore source needs reconciliation"
    volume = f"{project}-restore-{uuid.uuid4().hex}"
    values = dict(value.split("=", 1) for value in target["Config"]["Env"])
    env = {**os.environ, **{key: values[key] for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD")}}
    created = False
    try:
        subprocess.run(["docker", "run", "-d", "--name", source, "--network", next(iter(networks)),
                        "--network-alias", "restore-source", "--mount", f"type=volume,src={volume},dst=/var/lib/postgresql",
                        "-e", "POSTGRES_USER", "-e", "POSTGRES_DB", "-e", "POSTGRES_PASSWORD",
                        "-e", "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256", SOURCE_IMAGE],
                       env=env, check=True, stdout=subprocess.DEVNULL, timeout=120)
        created = True
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", source, "pg_isready", "-h", "127.0.0.1",
                                    "-U", values["POSTGRES_USER"], "-d", values["POSTGRES_DB"]],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Synthetic Bookworm source did not become ready")
        output(compose + ["run", "--rm", "--no-deps", "-T", "-e", "POSTGRES_HOST=restore-source",
                          "api", "python", "manage.py", "migrate", "--noinput"])
        api("""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
User = get_user_model()
assert User.objects.count() == 0
group = Group.objects.create(name='restore-fixture')
user = User.objects.create_user(' restore.one@EXAMPLE.INVALID ', first_name='Łódź', last_name='İstanbul / 東京', is_active=False)
user.groups.add(group)
user.user_permissions.add(Permission.objects.first())
User.objects.create_user('case@BÜCHER.EXAMPLE', first_name='e\\u0301 / Σ', is_active=False)
""", "restore-source")
        before = json.loads(api(SNAPSHOT, "restore-source"))
        assert before["users"] == 2 and before["provider"] == "c"
        # Custom-format logical dump, never a physical volume copy. Only synthetic data.
        with tempfile.TemporaryFile() as dump:
            subprocess.run(["docker", "exec", source, "pg_dump", "-Fc", "--no-owner", "--no-privileges",
                            "-U", values["POSTGRES_USER"], "-d", values["POSTGRES_DB"]],
                           stdout=dump, check=True, timeout=120)
            restore_command = compose + ["exec", "-T", "postgres", "pg_restore", "--single-transaction",
                                         "--exit-on-error", "--no-owner", "--no-privileges",
                                         "-U", values["POSTGRES_USER"], "-d", values["POSTGRES_DB"]]
            # Force a post-data index failure and prove that earlier restored
            # tables/data roll back. This is restricted to the empty test DB.
            api("""
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("CREATE SCHEMA restore_fault; CREATE FUNCTION restore_fault.fail_index() RETURNS event_trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'D056 intentional restore failure'; END; $$; CREATE EVENT TRIGGER d056_restore_failure ON ddl_command_end WHEN TAG IN ('CREATE INDEX') EXECUTE FUNCTION restore_fault.fail_index()")
""")
            try:
                dump.seek(0)
                failed = subprocess.run(restore_command, cwd=ROOT, stdin=dump, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True, timeout=120)
                assert failed.returncode != 0 and "D056 intentional restore failure" in failed.stderr
                empty = api("""
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f')")
    print(cursor.fetchone()[0])
""")
                assert empty == "0", "Failed restore left partial application objects"
            finally:
                api("""
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('DROP EVENT TRIGGER d056_restore_failure; DROP SCHEMA restore_fault CASCADE')
""")
            dump.seek(0)
            subprocess.run(restore_command, cwd=ROOT, stdin=dump, check=True, timeout=120)
        after = json.loads(api(SNAPSHOT))
        assert after["provider"] == "b"
        assert before["digest"] == after["digest"] and before["migrations"] == after["migrations"]
        api("""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
try:
    with transaction.atomic():
        get_user_model().objects.create_user('CASE@BÜCHER.EXAMPLE')
except IntegrityError as error:
    assert error.__cause__.diag.constraint_name == 'accounts_user_email_key'
else:
    raise AssertionError('Normalized Unicode email uniqueness was lost')
probe = get_user_model().objects.create_user('sequence-probe@example.invalid', is_active=False)
assert probe.pk > 2
probe.delete()
""")
        print("PASS: logical restore preserved Unicode users, groups/permissions, sequences and migrations; normalized email uniqueness retained")
        print("PASS: failed restore rolled back atomically before successful retry; libc -> builtin locale")
        print(f"Synthetic restore rehearsal elapsed: {time.monotonic() - started:.1f}s; not a hosted RTO measurement")
        print("Synthetic rows remain for restart verification")
    finally:
        if created:
            subprocess.run(["docker", "stop", source], check=True, stdout=subprocess.DEVNULL, timeout=60)
            subprocess.run(["docker", "rm", source], check=True, stdout=subprocess.DEVNULL, timeout=30)
            subprocess.run(["docker", "volume", "rm", volume], check=True, stdout=subprocess.DEVNULL, timeout=30)


if __name__ == "__main__":
    main()
