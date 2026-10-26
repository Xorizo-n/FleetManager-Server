import logging

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import auth, hosts, credentials, software, playbooks, tasks, dashboard, users, installers, agent, hardware, wallpapers, ldap_settings, backup, host_tags

logger = logging.getLogger(__name__)

# Число воркеров threadpool, в котором FastAPI крутит sync-зависимости и хендлеры.
# Держим его НЕ БОЛЬШЕ суммарного размера пула БД (database.py: 20+30=50), иначе
# потоки конкурируют за соединения и возникает кольцевой дедлок (см. database.py).
DB_THREADPOOL_TOKENS = 40

app = FastAPI(title="Fleet Manager API", version="1.0.0")


@app.on_event("startup")
async def _cap_threadpool() -> None:
    # Фиксируем размер threadpool явно: по умолчанию anyio даёт 40, но полагаться
    # на умолчание нельзя — инвариант «потоков <= соединений в пуле» критичен.
    try:
        anyio.to_thread.current_default_thread_limiter().total_tokens = DB_THREADPOOL_TOKENS
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось зафиксировать размер threadpool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ldap_settings.router)
app.include_router(backup.router)
app.include_router(hosts.router)
app.include_router(host_tags.router)
app.include_router(credentials.router)
app.include_router(software.router)
app.include_router(playbooks.router)
app.include_router(tasks.router)
app.include_router(dashboard.router)
app.include_router(users.router)
app.include_router(installers.router)
app.include_router(agent.router)
app.include_router(agent.router, prefix="/api")
app.include_router(hardware.router)
app.include_router(wallpapers.router)


@app.get("/health")
def health():
    return {"status": "ok"}
