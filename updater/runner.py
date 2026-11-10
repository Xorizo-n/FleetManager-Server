"""Runs outside the application containers; never executes release-supplied scripts."""
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from updater.release import MAX_BUNDLE, REPO, get, release, unpack, version

SERVICES = ["backend", "celery", "celery-beat", "frontend"]
TERMINAL = {"succeeded", "failed", "rolled_back", "recovery_required"}


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(tmp, path)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class Updater:
    def __init__(self, root, state, runtime, project="fleet-manager", wait_seconds=900):
        self.root, self.state_dir, self.runtime = map(Path, (root, state, runtime))
        self.project, self.wait_seconds = project, wait_seconds
        for path in (self.state_dir, self.runtime):
            path.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.data = self.read("state.json", {"current": {"version": "unversioned"}, "history": []})
        self.compose = self.root / "docker-compose.yml"
        current = self.data.get("current", {}).get("compose")
        if current:
            self.compose = Path(current)
        if self.data.get("operation", {}).get("status") not in TERMINAL | {None}:
            # We cannot know whether a migration committed before the host lost power.
            if self.data["operation"].get("previous_compose"):
                self.runtime.joinpath("maintenance").touch()
                self.event("recovery_required", "Сервер был перезапущен во время обновления. Требуется восстановление.")
            else:
                self.event("failed", "Подготовка прервана перезапуском сервера; платформа не изменялась")

    def read(self, name, default):
        path = self.state_dir / name
        return json.loads(path.read_text()) if path.exists() else default

    def save(self):
        atomic(self.state_dir / "state.json", self.data)

    def status(self):
        # Return a JSON snapshot, not a mutable reference shared with the worker.
        return json.loads(json.dumps({**self.data, "maintenance": self.runtime.joinpath("maintenance").exists(),
                                     "busy": self.lock.locked()}))

    def event(self, status, message):
        op = self.data["operation"]
        op.update(status=status, message=message, updated_at=now())
        op.setdefault("events", []).append({"at": now(), "message": message})
        if status in TERMINAL:
            op["finished_at"] = now()
        self.save()

    def check(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError("Обновление уже выполняется")
        try:
            try:
                self.data["available"] = release()
                self.data["check_error"] = None
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    self.data["available"], self.data["check_error"] = None, None
                else:
                    self.data["check_error"] = f"Не удалось проверить GitHub: HTTP {exc.code}"
            except Exception as exc:
                self.data["check_error"] = f"Не удалось проверить GitHub: {exc}"
            self.data["checked_at"] = now()
            self.save()
            return self.status()
        finally:
            self.lock.release()

    def start(self, tag, actor, restore=False):
        if not self.lock.acquire(blocking=False):
            raise ValueError("Обновление уже выполняется")
        try:
            if restore:
                op = self.data.get("operation", {})
                if op.get("status") != "recovery_required" or not op.get("previous_compose") or (op.get("migration_started") and not op.get("backup_complete")):
                    raise ValueError("Нет готовой копии для восстановления")
                self.event("restoring", "Восстановление предыдущей версии и БД")
            else:
                version(tag)
                if self.data.get("operation", {}).get("status") == "recovery_required":
                    raise ValueError("Сначала завершите восстановление")
                current = self.data["current"].get("version")
                if current != "unversioned" and version(tag) <= version(current):
                    raise ValueError("Выберите более новую версию")
                if self.data.get("operation"):
                    self.data["history"] = ([self.data["operation"]] + self.data["history"])[:20]
                self.data["operation"] = {"id": str(uuid.uuid4()), "version": tag, "actor": actor,
                                          "started_at": now(), "events": [], "previous": self.data["current"]}
                self.event("preparing", "Подготовка обновления")
            threading.Thread(target=self.worker, args=(restore,), daemon=True).start()
            return self.status()
        except Exception:
            self.lock.release()
            raise

    def cmd(self, args, timeout=120, input=None):
        result = subprocess.run(args, cwd=self.root, input=input, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            # Do not expose environment/configuration or command output containing credentials.
            raise RuntimeError(f"Команда {args[0]} завершилась с кодом {result.returncode}")
        return result.stdout

    def dc(self, *args, compose=None, timeout=120, input=None):
        file = compose or self.compose
        return self.cmd(["docker", "compose", "--project-directory", str(self.root), "--env-file", str(self.root / ".env"),
                         "-p", self.project, "-f", str(file), *args], timeout=timeout, input=input)

    def inspect_tasks(self):
        script = ("import json; from celery_app import celery_app; "
                  "i=celery_app.control.inspect(timeout=5); "
                  "print(json.dumps([i.active(),i.reserved(),i.scheduled()]))")
        reports = json.loads(self.dc("exec", "-T", "celery", "python", "-c", script))
        if len(reports) != 3 or not all(isinstance(r, dict) and r for r in reports):
            raise RuntimeError("Воркер не подтвердил состояние задач")
        return any(tasks for report in reports for tasks in report.values())

    def quiesce(self):
        self.runtime.joinpath("maintenance").touch()
        self.event("waiting", "Ожидание завершения фоновых задач; новые запросы временно приостановлены")
        self.dc("stop", "celery-beat")
        script = ("from celery_app import celery_app; "
                  "r=celery_app.control.cancel_consumer('celery',reply=True,timeout=10); "
                  "assert r and all('ok' in v for item in r for v in item.values()); "
                  "q=celery_app.control.inspect(timeout=5).active_queues(); "
                  "assert q and all(not queues for queues in q.values())")
        self.dc("exec", "-T", "celery", "python", "-c", script)
        deadline = time.monotonic() + self.wait_seconds
        while self.inspect_tasks():
            if time.monotonic() >= deadline:
                raise RuntimeError("Задачи не завершились за отведённое время. Обновление отложено")
            time.sleep(5)
        # Warm shutdown, after active/reserved/scheduled tasks have drained.
        self.dc("stop", "-t", "120", "celery", timeout=150)
        self.dc("stop", "-t", "120", "backend", timeout=150)
        self.data["operation"]["quiesced"] = True
        self.save()

    def db_revision(self):
        sql = "SELECT version_num FROM alembic_version"
        return self.dc("exec", "-T", "postgres", "sh", "-c",
                       'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"', "sh", sql).decode().strip()

    def backup(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        dump = directory / "database.dump"
        # Stream to disk: large databases must not be buffered in the updater's memory.
        args = ["docker", "compose", "--project-directory", str(self.root), "--env-file", str(self.root / ".env"),
                "-p", self.project, "-f", str(self.compose), "exec", "-T", "postgres", "sh", "-c",
                'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"']
        with dump.open("wb") as out:
            subprocess.run(args, cwd=self.root, stdout=out, stderr=subprocess.PIPE, check=True, timeout=600)
        self.dc("cp", str(dump), "postgres:/tmp/fleet-pre-update.dump")
        try:
            self.dc("exec", "-T", "postgres", "pg_restore", "--list", "/tmp/fleet-pre-update.dump", timeout=600)
        finally:
            self.dc("exec", "-T", "postgres", "rm", "-f", "/tmp/fleet-pre-update.dump")
        with tarfile.open(directory / "config.tar.gz", "w:gz") as archive:
            for name in (".env", "certs", "secrets", "docker-compose.yml", "postgres-entrypoint.sh"):
                path = self.root / name
                if path.exists():
                    archive.add(path, arcname=name)
        script = ("import tarfile; from pathlib import Path; p=Path('/app/ansible_data/local_playbooks'); "
                  "a=tarfile.open('/snapshot/playbooks.tar.gz','w:gz'); "
                  "a.add(p,arcname='local_playbooks') if p.exists() else None; a.close()")
        self.dc("run", "--rm", "--no-deps", "-v", f"{directory}:/snapshot", "--entrypoint", "python",
                "backend", "-c", script, timeout=300)

    def health(self, compose):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                data = json.loads(self.cmd(["curl", "--fail", "--silent", "--max-time", "5", "http://127.0.0.1:8000/health"]))
                if data.get("status") == "ok":
                    self.dc("exec", "-T", "backend", "python", "-c",
                            "from database import engine; from sqlalchemy import text; c=engine.connect(); c.execute(text('SELECT 1')); c.close()", compose=compose)
                    self.dc("exec", "-T", "frontend", "wget", "-q", "--no-check-certificate", "-O", "/dev/null", "https://127.0.0.1/", compose=compose)
                    return
            except Exception:
                pass
            time.sleep(3)
        raise RuntimeError("Новая версия не прошла проверку работоспособности")

    def resume(self, compose):
        self.dc("up", "-d", "--no-build", "--no-deps", "backend", "frontend", "celery", compose=compose)
        self.health(compose)
        # A running container alone does not prove Celery has loaded its Redis transport.
        self.dc("exec", "-T", "celery", "python", "-c",
                "from celery_app import celery_app; r=celery_app.control.ping(timeout=10); assert r", compose=compose)
        self.dc("up", "-d", "--no-build", "--no-deps", "celery-beat", compose=compose)

    def restore(self):
        op = self.data["operation"]
        previous = Path(op["previous_compose"])
        directory = Path(op["backup"])
        if op.get("migration_container"):
            container = op["migration_container"]
            found = self.cmd(["docker", "ps", "-aq", "--filter", f"name=^/{container}$"]).decode().strip()
            if found:
                # A Docker one-off may outlive the updater process that launched it.
                self.cmd(["docker", "rm", "-f", container])
        self.dc("stop", "-t", "120", "backend", "celery", "celery-beat", compose=Path(op["target_compose"]), timeout=180)
        if not op.get("migration_started"):
            self.resume(previous)
            self.compose = previous
            self.data["current"] = op["previous"]
            self.runtime.joinpath("maintenance").unlink(missing_ok=True)
            self.event("rolled_back", "Предыдущая версия запущена; миграция и восстановление БД не требовались")
            return
        # This intentionally discards changes since the pre-update snapshot; the API requires confirmation.
        self.dc("cp", str(directory / "database.dump"), "postgres:/tmp/fleet-pre-update.dump", compose=previous)
        try:
            self.dc("exec", "-T", "postgres", "sh", "-c",
                    'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB" && pg_restore --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/fleet-pre-update.dump',
                    timeout=600, compose=previous)
        finally:
            self.dc("exec", "-T", "postgres", "rm", "-f", "/tmp/fleet-pre-update.dump", compose=previous)
        with tarfile.open(directory / "config.tar.gz") as archive:
            archive.extractall(self.root, filter="data")
        script = ("import tarfile,shutil; from pathlib import Path; p=Path('/app/ansible_data/local_playbooks'); "
                  "shutil.rmtree(p) if p.exists() else None; "
                  "a=tarfile.open('/snapshot/playbooks.tar.gz'); a.extractall('/app/ansible_data',filter='data'); a.close()")
        self.dc("run", "--rm", "--no-deps", "-v", f"{directory}:/snapshot:ro", "--entrypoint", "python",
                "backend", "-c", script, compose=previous, timeout=300)
        self.resume(previous)
        self.compose = previous
        self.data["current"] = op["previous"]
        self.runtime.joinpath("maintenance").unlink(missing_ok=True)
        self.event("rolled_back", "Восстановлены БД и предыдущая версия платформы")

    def install(self):
        op = self.data["operation"]
        target = release(op["version"])
        if shutil.disk_usage(self.root).free < 4 * 1024**3:
            raise RuntimeError("Для обновления нужно не менее 4 ГБ свободного места")
        directory = self.state_dir / "releases" / op["id"]
        directory.mkdir(parents=True)
        bundle = get(f"https://github.com/{REPO}/releases/download/{target['version']}/platform.tar.gz", MAX_BUNDLE)
        unpack(bundle, directory, target["bundle_sha256"])
        compose = directory / "compose.json"
        config = json.loads(compose.read_text())
        # Pin release inputs again on the host; the bundle cannot choose another image.
        for name in SERVICES:
            config["services"][name]["image"] = target["images"]["frontend" if name == "frontend" else "backend"]
        for name in ("backend", "celery"):
            volumes = config["services"][name]["volumes"]
            config["services"][name]["volumes"] = [str(directory / "ansible") + ":/app/ansible:ro" if v == "./ansible:/app/ansible:ro" else v for v in volumes]
        atomic(compose, config)
        self.dc("config", "--quiet", compose=compose)
        self.event("downloading", "Загрузка образов новой версии")
        self.dc("pull", *SERVICES, compose=compose, timeout=1800)
        # Require enough space for the dump, verification copy, configuration, and old images.
        db_bytes = int(self.dc("exec", "-T", "postgres", "sh", "-c",
                              'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT pg_database_size(current_database())"'))
        if shutil.disk_usage(self.root).free < 4 * 1024**3 + 3 * db_bytes:
            raise RuntimeError("Недостаточно места для резервной копии и восстановления БД")
        # Capture exact running images, even for the initial unversioned installation.
        old = json.loads(self.dc("config", "--format", "json"))
        for name in SERVICES:
            cid = self.dc("ps", "-q", name).decode().strip()
            image_id = self.cmd(["docker", "inspect", "--format", "{{.Image}}", cid]).decode().strip()
            tag = f"fleet-manager-rollback:{op['id']}-{name}"
            self.cmd(["docker", "tag", image_id, tag])
            old["services"][name].pop("build", None)
            old["services"][name]["image"] = tag
        previous = directory / "previous.json"
        atomic(previous, old)
        op["previous"] = {**op["previous"], "compose": str(previous)}
        op.update(target_compose=str(compose), previous_compose=str(previous), backup=str(directory / "backup"))
        self.save()
        self.quiesce()
        op["previous_revision"] = self.db_revision()
        self.event("backing_up", "Создание резервной копии БД и конфигурации")
        self.backup(Path(op["backup"]))
        op["backup_complete"] = True
        self.event("migrating", "Применение миграций БД")
        op["migration_started"] = True
        op["migration_container"] = f"{self.project}-migration-{op['id']}"
        self.save()
        self.dc("run", "--rm", "--no-deps", "--name", op["migration_container"], "backend", "alembic", "upgrade", "head", compose=compose, timeout=600)
        revision = self.db_revision()
        if revision != target["schema_revision"]:
            raise RuntimeError("Версия схемы БД не совпадает с релизом")
        op["schema_unchanged"] = revision == op["previous_revision"]
        self.event("starting", "Запуск и проверка новой версии")
        self.resume(compose)
        self.compose = compose
        self.data["current"] = {"version": target["version"], "commit": target["commit"], "compose": str(compose)}
        self.runtime.joinpath("maintenance").unlink(missing_ok=True)
        self.event("succeeded", "Платформа обновлена")

    def worker(self, restore=False):
        try:
            self.restore() if restore else self.install()
        except Exception as exc:
            op = self.data["operation"]
            if restore or (op.get("migration_started") and not op.get("schema_unchanged")):
                self.runtime.joinpath("maintenance").touch()
                self.event("recovery_required", f"{exc}. Требуется восстановление из копии")
                # If the backend cannot start, the independent CLI remains available.
            elif op.get("previous_compose"):
                try:
                    if op.get("quiesced"):
                        self.resume(Path(op["previous_compose"]))
                    else:
                        # Waiting timed out: don't recreate containers with active playbooks.
                        self.dc("exec", "-T", "celery", "python", "-c",
                                "from celery_app import celery_app; celery_app.control.add_consumer('celery',reply=True,timeout=10)")
                        self.dc("start", "backend", "celery", "celery-beat")
                    self.runtime.joinpath("maintenance").unlink(missing_ok=True)
                    self.event("failed", f"{exc}. Предыдущая версия продолжает работу")
                except Exception:
                    self.runtime.joinpath("maintenance").touch()
                    self.event("recovery_required", f"{exc}. Автоматический возврат не удался")
            else:
                self.event("failed", str(exc))
        finally:
            self.lock.release()
