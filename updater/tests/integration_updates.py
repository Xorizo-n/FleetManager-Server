"""Destructive only to its own isolated Compose project and temporary directory.

Run on a Linux Docker host: python3 -m updater.tests.integration_updates
Requires fleet-platform-check-backend and fleet-platform-check-frontend images.
"""
import copy
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from updater.runner import Updater, atomic


class TestUpdater(Updater):
    def cmd(self, args, **kwargs):
        args = [a.replace("http://127.0.0.1:8000/health", "http://127.0.0.1:18000/health") for a in args]
        return super().cmd(args, **kwargs)


def main():
    root = Path(tempfile.mkdtemp(prefix="fleet-updater-integration-"))
    project = "fleet-updater-test-" + uuid.uuid4().hex[:8]
    root.joinpath(".env").write_text("")
    root.joinpath("certs").mkdir()
    root.joinpath("run").mkdir()
    env = {"JWT_SECRET_KEY": "test", "CREDENTIAL_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
           "DATABASE_URL": "postgresql+psycopg://fleet:test@postgres:5432/fleet",
           "CELERY_BROKER_URL": "redis://redis:6379/0", "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
           "PLATFORM_MAINTENANCE_FILE": "/run/fleet-test-updater/maintenance"}
    backend = "fleet-platform-check-backend"
    frontend = "fleet-platform-check-frontend"
    app = {"image": backend, "environment": env, "volumes": ["data:/app/ansible_data", str(root / "run") + ":/run/fleet-test-updater:ro"],
           "depends_on": {"postgres": {"condition": "service_healthy"}, "redis": {"condition": "service_started"}}}
    config = {"services": {
        "postgres": {"image": "postgres:15", "environment": {"POSTGRES_USER": "fleet", "POSTGRES_PASSWORD": "test", "POSTGRES_DB": "fleet"},
                     "volumes": ["db:/var/lib/postgresql/data"], "healthcheck": {"test": ["CMD", "pg_isready", "-U", "fleet"], "interval": "2s", "timeout": "2s", "retries": 30}},
        "redis": {"image": "redis:7"},
        "backend": {**app, "ports": ["127.0.0.1:18000:8000"], "command": ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]},
        "celery": {**app, "command": "celery -A celery_app.celery_app worker --loglevel=warning --concurrency=1"},
        "celery-beat": {**app, "command": "celery -A celery_app.celery_app beat --loglevel=warning"},
        "frontend": {"image": frontend, "ports": ["127.0.0.1:18443:443"], "volumes": [str(root / "certs") + ":/etc/nginx/certs"], "depends_on": ["backend"]},
    }, "volumes": {"db": {}, "data": {}}}
    atomic(root / "docker-compose.yml", config)  # Compose accepts JSON as YAML.
    updater = TestUpdater(root, root / "state", root / "run", project=project, wait_seconds=30)

    def sql(query):
        return updater.dc("exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "fleet", "-d", "fleet", "-Atc", query).decode().strip()

    def run_install(tag, fail_migration=False):
        target = copy.deepcopy(config)
        target["services"]["backend"]["command"] = "uvicorn main:app --host 0.0.0.0 --port 8000"
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            raw = json.dumps(target).encode()
            member = tarfile.TarInfo("compose.json"); member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
            member = tarfile.TarInfo("ansible"); member.type = tarfile.DIRTYPE; archive.addfile(member)
        bundle = out.getvalue()
        release = {"version": tag, "commit": "a" * 40, "schema_revision": updater.db_revision(),
                   "bundle_sha256": hashlib.sha256(bundle).hexdigest(), "images": {"backend": backend, "frontend": frontend}}
        real_dc = updater.dc
        def dc(*args, **kwargs):
            result = real_dc(*args, **kwargs)
            if fail_migration and args[:5] == ("run", "--rm", "--no-deps", "backend", "alembic"):
                sql("CREATE TABLE updater_new_schema (id int)")
                raise RuntimeError("Simulated failure after a migration committed")
            return result
        # Locally built images substitute for GHCR; contract checks are covered by unit tests.
        # Pull must be skipped because these temporary image names are not published.
        def local_dc(*args, **kwargs):
            if args and args[0] == "pull": return b""
            return dc(*args, **kwargs)
        with patch("updater.runner.release", return_value=release), patch("updater.runner.get", return_value=bundle), patch.object(updater, "dc", side_effect=local_dc):
            updater.start(tag, "integration-test")
            deadline = time.monotonic() + 240
            while updater.lock.locked() and time.monotonic() < deadline:
                time.sleep(1)
            assert not updater.lock.locked(), updater.status()

    try:
        updater.dc("up", "-d", timeout=180)
        updater.health(updater.compose)
        sql("CREATE TABLE updater_sentinel (id int); INSERT INTO updater_sentinel VALUES (1)")
        run_install("v1.0.0")
        assert updater.data["operation"]["status"] == "succeeded", updater.status()
        assert updater.data["current"]["version"] == "v1.0.0"
        assert sql("SELECT count(*) FROM updater_sentinel") == "1"
        print("PASS: complete installation with real containers, backup, migration and health checks", flush=True)
        run_install("v1.0.1", fail_migration=True)
        assert updater.data["operation"]["status"] == "recovery_required", updater.status()
        assert updater.runtime.joinpath("maintenance").exists()
        sql("INSERT INTO updater_sentinel VALUES (2)")
        assert sql("SELECT to_regclass('updater_new_schema')") == "updater_new_schema"
        updater.start(None, "integration-test", restore=True)
        deadline = time.monotonic() + 240
        while updater.lock.locked() and time.monotonic() < deadline:
            time.sleep(1)
        assert updater.data["operation"]["status"] == "rolled_back", updater.status()
        assert not updater.runtime.joinpath("maintenance").exists()
        assert sql("SELECT count(*) FROM updater_sentinel") == "1"
        assert sql("SELECT to_regclass('updater_new_schema')") == ""
        print("PASS: failure after schema change, explicit database/configuration restore and return to previous version", flush=True)
    finally:
        updater.dc("down", "-v", "--remove-orphans", timeout=180)
        # Remove only the explicitly created temporary directory after Compose released its volumes.
        assert root.parent == Path(tempfile.gettempdir()) and root.name.startswith("fleet-updater-integration-")
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
