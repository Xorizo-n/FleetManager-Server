"""Резервные копии вне ВМ: restic по SFTP в хранилище, заданное в интерфейсе (Администрирование →
«Резервные копии»).

Что копируется и когда (часы — по Екатеринбургу):
- db — каждые 4 часа: дамп БД (pg_dump потоком, без временного файла; restic проверяет код
  выхода pg_dump) и конфигурация: .env с ключом шифрования учётных данных, certs/, локальные
  плейбуки. Без .env SSH-ключи ПК из дампа не расшифровать, поэтому они всегда идут вместе.
- share — каждую ночь в 02:30: /mnt/soft-share (установщики, обои). restic передаёт только
  изменившиеся куски, полная передача — лишь в первый раз.
- check — по воскресеньям в 05:00: restic check с чтением части данных, восстановление
  последнего дампа во временную БД, сверка с рабочей и расшифровка учётных данных ключом из
  скопированного .env; затем prune — освобождение места после forget.

Копии зашифрованы паролем restic. Он хранится в БД зашифрованным, но держать его нужно и вне
сервера: при потере ВМ без него копии не открыть. Ключ SSH хранилища закрепляется при
первом сохранении настроек; если он сменится, копирование остановится с ошибкой.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

from sqlalchemy import select

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.backup import BackupRun, BackupSettings

DB = "db"
SHARE = "share"
CHECK = "check"
KINDS = (DB, SHARE, CHECK)
RESTIC_HOST = "fleet-manager"
DB_FILE = "fleet_manager.sql"
RESTORE_DB = "fm_restore_check"
SHARE_EXCLUDES = (".upload-tmp", "lost+found")
RETENTION = {
    DB: ["--keep-within", "2d", "--keep-daily", "14", "--keep-weekly", "8", "--keep-monthly", "12"],
    "config": ["--keep-within", "2d", "--keep-daily", "14", "--keep-weekly", "8", "--keep-monthly", "12"],
    SHARE: ["--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6"],
}
RUN_TIMEOUT = {DB: 2 * 3600, SHARE: 12 * 3600, CHECK: 6 * 3600}


class BackupError(RuntimeError):
    """Текст показывается в интерфейсе."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    user: str
    path: str
    password: str
    repo_password: str
    host_key: str | None = None

    @property
    def repository(self) -> str:
        return f"sftp:{self.user}@{self.host}:{self.path}"


def target_from_row(row: BackupSettings) -> Target:
    from services.crypto import decrypt_secret

    def secret(value):
        return decrypt_secret(value) if value else ""

    return Target(row.sftp_host, row.sftp_port, row.sftp_user, row.sftp_path,
                  secret(row.sftp_password_encrypted), secret(row.repo_password_encrypted), row.host_key)


# --- SSH и restic -------------------------------------------------------------------------

def scan_host_key(host: str, port: int) -> str:
    """Ключ SSH хоста («ssh-ed25519 AAAA…») — закрепляется при сохранении настроек."""
    try:
        result = subprocess.run(["ssh-keyscan", "-T", "10", "-p", str(port), "-t", "ed25519,ecdsa,rsa", host],
                                capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"{host}:{port} не ответил по SSH") from exc
    keys = [line.split(None, 1)[1] for line in result.stdout.splitlines() if line and not line.startswith("#") and len(line.split()) >= 3]
    if not keys:
        raise BackupError(f"Не удалось получить ключ SSH {host}:{port} — хост недоступен или это не SSH")
    return next((k for k in keys if k.startswith("ssh-ed25519")), keys[0])


def fingerprint(host_key: str | None) -> str | None:
    if not host_key:
        return None
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=f"host {host_key}\n", capture_output=True, text=True)
    parts = result.stdout.split()
    return parts[1] if len(parts) > 1 else None


def _ssh_options(target: Target, known_hosts: str) -> list[str]:
    """Опции ssh/sftp: только закреплённый ключ хоста, вход только паролем (пароль — в SSHPASS).

    Без запятых: restic режет значение -o sftp.command=… по запятым (поэтому нет
    PreferredAuthentications=password,keyboard-interactive — с PubkeyAuthentication=no ssh
    и так переходит к паролю)."""
    return ["-o", f"UserKnownHostsFile={known_hosts}", "-o", "StrictHostKeyChecking=yes",
            "-o", "PubkeyAuthentication=no", "-o", "GSSAPIAuthentication=no",
            "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=6"]


@contextlib.contextmanager
def _session(target: Target, extra_env: dict | None = None):
    """(окружение, known_hosts) для одного обращения к хранилищу."""
    if not target.host_key:
        raise BackupError("Ключ SSH хранилища не закреплён — сохраните настройки")
    with tempfile.TemporaryDirectory(prefix="restic-") as tmp:
        known_hosts = os.path.join(tmp, "known_hosts")
        name = target.host if target.port == 22 else f"[{target.host}]:{target.port}"
        with open(known_hosts, "w") as f:
            f.write(f"{name} {target.host_key}\n")
        env = {
            **os.environ,
            "RESTIC_REPOSITORY": target.repository,
            "RESTIC_PASSWORD": target.repo_password,
            "SSHPASS": target.password,  # пароль SFTP — не в командной строке
            "RESTIC_CACHE_DIR": "/app/ansible_data/restic-cache",
            **(extra_env or {}),
        }
        yield env, known_hosts


@contextlib.contextmanager
def _restic_env(target: Target, extra_env: dict | None = None):
    with _session(target, extra_env) as (env, known_hosts):
        ssh = " ".join(["sshpass", "-e", "ssh", "-p", str(target.port), *_ssh_options(target, known_hosts),
                        f"{target.user}@{target.host}", "-s", "sftp"])
        yield env, ["-o", f"sftp.command={ssh}"]


def explain(stderr: str) -> str:
    text = stderr.lower()
    if "is there a repository at the following location" in text or "config file does not exist" in text:
        return "Хранилище restic по этому пути ещё не создано"
    if "wrong password or no key found" in text:
        return "Неверный пароль шифрования копий"
    if "permission denied" in text:
        return "SFTP: неверный логин или пароль, или нет прав на каталог"
    if "host key verification failed" in text or "identification has changed" in text:
        return "Ключ SSH хранилища изменился — проверьте сервер и сохраните настройки заново"
    if "already locked" in text:
        return "Хранилище занято другой операцией restic — повторится в следующий раз"
    if "no such file or directory" in text and "sftp" in text:
        return "Каталог в хранилище не найден"
    if "connection timed out" in text or "no route to host" in text or "connection refused" in text:
        return "Хранилище недоступно по сети"
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    return (lines[-1] if lines else "restic завершился с ошибкой")[:500]


def restic(target: Target, *args: str, timeout: int = 600, extra_env: dict | None = None, check: bool = True):
    with _restic_env(target, extra_env) as (env, options):
        try:
            result = subprocess.run(["restic", *options, *args], env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise BackupError(f"restic {args[0]} не уложился в {timeout // 60} мин") from exc
    if check and result.returncode != 0:
        raise BackupError(explain(result.stderr))
    return result


def repository_state(target: Target) -> str:
    """exists / missing; остальные ошибки (пароль, сеть, ключ хоста) — исключение."""
    result = restic(target, "cat", "config", timeout=120, check=False)
    if result.returncode == 0:
        return "exists"
    message = explain(result.stderr)
    if message.startswith("Хранилище restic по этому пути ещё не создано"):
        return "missing"
    raise BackupError(message)


def ensure_repository(target: Target) -> bool:
    """Создаёт хранилище, если его ещё нет. True — создано сейчас."""
    if repository_state(target) == "exists":
        return False
    restic(target, "init", timeout=300)
    return True


def _summary(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("message_type") == "summary":
            return data
    raise BackupError("restic не сообщил итог копирования")


def pg_env(database: str | None = None) -> dict:
    """Подключение pg_dump/psql к БД приложения — из DATABASE_URL, пароль через PGPASSWORD."""
    url = urlsplit(settings.database_url.replace("+psycopg", ""))
    return {
        "PGHOST": url.hostname or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGUSER": unquote(url.username or ""),
        "PGPASSWORD": unquote(url.password or ""),
        "PGDATABASE": database or url.path.lstrip("/"),
    }


def _forget(target: Target, tag: str) -> None:
    restic(target, "forget", "--tag", tag, "--host", RESTIC_HOST, "--group-by", "host,tags", *RETENTION[tag], timeout=1800)


# --- Копирование -------------------------------------------------------------------------

def backup_db(target: Target) -> dict:
    """Дамп БД и конфигурация двумя снимками: db и config."""
    config_paths = [p for p in (settings.offsite_config_dir, settings.local_playbooks_dir) if os.path.exists(p)]
    if not os.path.isfile(os.path.join(settings.offsite_config_dir, ".env")):
        raise BackupError(f"Нет {settings.offsite_config_dir}/.env — без него копия БД бесполезна (ключ шифрования учётных данных)")
    db = _summary(restic(target, "backup", "--json", "--tag", DB, "--host", RESTIC_HOST, "--stdin-filename", DB_FILE,
                         "--stdin-from-command", "--", "pg_dump", "--no-password", timeout=RUN_TIMEOUT[DB],
                         extra_env=pg_env()).stdout)
    config = _summary(restic(target, "backup", "--json", "--tag", "config", "--host", RESTIC_HOST, *config_paths,
                             timeout=1800).stdout)
    _forget(target, DB)
    _forget(target, "config")
    return {
        "snapshot_ids": [db.get("snapshot_id"), config.get("snapshot_id")],
        "bytes_added": int(db.get("data_added", 0)) + int(config.get("data_added", 0)),
        "details": {"db_bytes": db.get("total_bytes_processed"), "config_files": config.get("total_files_processed")},
    }


def backup_share(target: Target) -> dict:
    excludes = [arg for name in SHARE_EXCLUDES for arg in ("--exclude", os.path.join(settings.offsite_share_dir, name))]
    share = _summary(restic(target, "backup", "--json", "--tag", SHARE, "--host", RESTIC_HOST, *excludes,
                            settings.offsite_share_dir, timeout=RUN_TIMEOUT[SHARE]).stdout)
    _forget(target, SHARE)
    return {
        "snapshot_ids": [share.get("snapshot_id")],
        "bytes_added": int(share.get("data_added", 0)),
        "details": {"files": share.get("total_files_processed"), "bytes": share.get("total_bytes_processed"),
                    "files_new": share.get("files_new"), "files_changed": share.get("files_changed")},
    }


def _latest(target: Target, tag: str) -> dict:
    snapshots = json.loads(restic(target, "snapshots", "--json", "--tag", tag, "--host", RESTIC_HOST, "--latest", "1", timeout=300).stdout or "[]")
    if not snapshots:
        raise BackupError(f"В хранилище нет снимков «{tag}»")
    return snapshots[-1]


def _psql(sql: str, database: str) -> str:
    result = subprocess.run(["psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1", "-c", sql], capture_output=True, text=True,
                            env={**os.environ, **pg_env(database)}, timeout=600)
    if result.returncode != 0:
        raise BackupError(f"psql: {result.stderr.strip()[-300:]}")
    return result.stdout.strip()


def _env_value(text: str, name: str) -> str | None:
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def restore_check(target: Target) -> dict:
    """Проверка, что из копии реально можно восстановиться: целостность, дамп и ключ шифрования."""
    from cryptography.fernet import Fernet

    restic(target, "check", "--read-data-subset=2%", timeout=RUN_TIMEOUT[CHECK])
    snapshot = _latest(target, DB)
    config = _latest(target, "config")
    env_text = restic(target, "dump", config["id"], os.path.join(settings.offsite_config_dir, ".env"), timeout=300).stdout
    key = _env_value(env_text, "CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise BackupError("В скопированном .env нет CREDENTIAL_ENCRYPTION_KEY")

    _psql(f"DROP DATABASE IF EXISTS {RESTORE_DB}", "postgres")
    _psql(f"CREATE DATABASE {RESTORE_DB}", "postgres")
    try:
        with _restic_env(target) as (env, options):
            dump = subprocess.Popen(["restic", *options, "dump", snapshot["id"], f"/{DB_FILE}"], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            load = subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-o", "/dev/null"], stdin=dump.stdout,
                                  capture_output=True, text=True, env={**os.environ, **pg_env(RESTORE_DB)}, timeout=RUN_TIMEOUT[CHECK])
            dump.stdout.close()
            dump_err = dump.stderr.read().decode(errors="replace")
            dump.wait(timeout=60)
        if dump.returncode != 0:
            raise BackupError(f"restic dump: {explain(dump_err)}")
        if load.returncode != 0:
            raise BackupError(f"Восстановление дампа: {load.stderr.strip()[-300:]}")

        restored = {t: int(_psql(f"SELECT count(*) FROM {t}", RESTORE_DB)) for t in ("hosts", "credentials", "users")}
        live = {t: int(_psql(f"SELECT count(*) FROM {t}", pg_env()["PGDATABASE"])) for t in ("hosts", "credentials", "users")}
        version = _psql("SELECT version_num FROM alembic_version", RESTORE_DB)
        secret = _psql("SELECT secret_encrypted FROM credentials WHERE secret_encrypted IS NOT NULL LIMIT 1", RESTORE_DB)
        decrypted = False
        if secret:
            Fernet(key.encode()).decrypt(secret.encode())  # InvalidToken — ключ из копии не подходит к БД из копии
            decrypted = True
        if restored["hosts"] == 0 and live["hosts"] > 0:
            raise BackupError("В восстановленной БД нет хостов")
    finally:
        with contextlib.suppress(BackupError):
            _psql(f"DROP DATABASE IF EXISTS {RESTORE_DB}", "postgres")

    restic(target, "prune", timeout=RUN_TIMEOUT[CHECK])
    stats = json.loads(restic(target, "stats", "--json", "--mode", "raw-data", timeout=1800).stdout or "{}")
    return {
        "snapshot_ids": [snapshot["id"], config["id"]],
        "details": {"snapshot_time": snapshot.get("time"), "restored": restored, "live": live, "alembic": version,
                    "credentials_decrypted": decrypted, "repository_bytes": stats.get("total_size")},
    }


RUNNERS = {DB: backup_db, SHARE: backup_share, CHECK: restore_check}


def sftp_check(target: Target) -> None:
    """Вход по SFTP с паролем и доступ к каталогу хранилища (или к родительскому — каталог создаст restic)."""
    parent = os.path.dirname(target.path.rstrip("/")) or "/"
    with _session(target) as (env, known_hosts):
        # Без -b: пакетный режим sftp включает BatchMode, а он запрещает вход по паролю
        command = ["sshpass", "-e", "sftp", "-P", str(target.port), *_ssh_options(target, known_hosts), f"{target.user}@{target.host}"]
        try:
            result = subprocess.run(command, input=f"ls {parent}\nbye\n", env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise BackupError("Хранилище не ответило по SFTP") from exc
    output = f"{result.stderr}\n{result.stdout}"
    if result.returncode != 0:
        raise BackupError(explain(output))
    if "can't ls" in output.lower() or "not found" in output.lower():
        raise BackupError(f"Каталог {parent} в хранилище не найден или недоступен")


def _last_ok(db, kind: str):
    return db.execute(select(BackupRun).where(BackupRun.kind == kind, BackupRun.ok.is_(True))
                      .order_by(BackupRun.finished_at.desc()).limit(1)).scalar_one_or_none()


def offsite_status(db) -> dict:
    """Для мониторинга: свежесть копии БД вне ВМ и итог последней проверки восстановления."""
    row = db.get(BackupSettings, 1)
    last_db = _last_ok(db, DB)
    last_check = db.execute(select(BackupRun).where(BackupRun.kind == CHECK, BackupRun.finished_at.isnot(None))
                            .order_by(BackupRun.finished_at.desc()).limit(1)).scalar_one_or_none()
    last_failed = db.execute(select(BackupRun).where(BackupRun.finished_at.isnot(None)).order_by(BackupRun.finished_at.desc()).limit(1)).scalar_one_or_none()
    return {
        "enabled": bool(row and row.enabled),
        "last_db_at": last_db.finished_at if last_db else None,
        "max_age_hours": settings.offsite_db_max_age_hours,
        "last_check_at": last_check.finished_at if last_check else None,
        "last_check_ok": last_check.ok if last_check else None,
        "last_error": last_failed.message if last_failed and last_failed.ok is False else None,
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(name="services.offsite_backup.run_backup", soft_time_limit=13 * 3600, time_limit=13 * 3600 + 600)
def run_backup(kind: str, run_id: str | None = None) -> None:
    """Плановый запуск (run_id нет) — только если копирование включено; ручной — по готовой записи BackupRun."""
    import uuid

    db = SessionLocal()
    try:
        row = db.get(BackupSettings, 1)
        if run_id is None:
            if row is None or not row.enabled:
                return
            run = BackupRun(kind=kind)
            db.add(run)
            db.commit()
        else:
            run = db.get(BackupRun, uuid.UUID(run_id))
            if run is None:
                return
        try:
            if row is None or not row.sftp_host or not row.repo_password_encrypted:
                raise BackupError("Хранилище копий не настроено")
            target = target_from_row(row)
            created = ensure_repository(target)
            if created or not row.initialized:
                row.initialized = True
                db.commit()
            result = RUNNERS[kind](target)
            run.ok = True
            run.snapshot_ids = result.get("snapshot_ids")
            run.bytes_added = result.get("bytes_added")
            run.details = {**(result.get("details") or {}), **({"repository_created": True} if created else {})}
        except Exception as exc:  # noqa: BLE001 — любая ошибка — в журнал копий, а не в лог Celery
            run.ok = False
            run.message = str(exc)[:2000] if isinstance(exc, BackupError) else f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = _now()
        db.commit()
    finally:
        db.close()

