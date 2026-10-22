from celery import Celery
from celery.schedules import crontab

from config import settings

celery_app = Celery(
    "fleet_manager",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "services.ansible_runner",
        "services.software_scanner",
        "services.host_health",
        "services.host_diagnostics",
        "services.agent_installer_sync",
        "services.agent_update",
        "services.host_grouping",
        "services.access_change",
        "services.waiting_tasks",
        "services.wake_on_lan",
        "services.wallpapers",
        "services.offsite_backup",
    ],
)

celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-scheduled-playbooks": {
            "task": "services.ansible_runner.dispatch_scheduled_playbooks",
            "schedule": 60.0,
        },
        "ping-hosts": {
            "task": "services.host_health.ping_hosts",
            "schedule": 300.0,
        },
        # Отменяет задачи, чей ПК так и не появился в сети за waiting_task_ttl_days
        "expire-waiting-tasks": {
            "task": "services.waiting_tasks.expire_waiting_tasks",
            "schedule": 3600.0,
        },
        "sync-agent-installer": {
            "task": "services.agent_installer_sync.sync_agent_installer_task",
            "schedule": 3600.0,
        },
        # Раскладывает по группам и ПК без агента или выключенные (агентские — сразу при heartbeat).
        # Смена обоев в заданное время (services/wallpapers.py)
        "apply-wallpaper-schedules": {
            "task": "services.wallpapers.apply_wallpaper_schedules",
            "schedule": 60.0,
        },
        "regroup-hosts": {
            "task": "services.host_grouping.regroup_hosts",
            "schedule": 3600.0,
        },
        # Копии вне ВМ (services/offsite_backup.py), часы в UTC: БД каждые 4 часа (06:15, 10:15…
        # по Екатеринбургу), soft-share в 02:30, проверка восстановления по воскресеньям в 05:00
        "offsite-backup-db": {
            "task": "services.offsite_backup.run_backup",
            "schedule": crontab(minute=15, hour="*/4"),
            "args": ("db",),
        },
        "offsite-backup-share": {
            "task": "services.offsite_backup.run_backup",
            "schedule": crontab(minute=30, hour=21),
            "args": ("share",),
        },
        "offsite-backup-check": {
            "task": "services.offsite_backup.run_backup",
            "schedule": crontab(minute=0, hour=0, day_of_week="sunday"),
            "args": ("check",),
        },
    },
)
