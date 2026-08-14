from celery import Celery

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
        "sync-agent-installer": {
            "task": "services.agent_installer_sync.sync_agent_installer_task",
            "schedule": 3600.0,
        },
    },
)
