from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import auth, hosts, credentials, software, playbooks, tasks, dashboard, users, installers, agent, hardware

app = FastAPI(title="Fleet Manager API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(hosts.router)
app.include_router(credentials.router)
app.include_router(software.router)
app.include_router(playbooks.router)
app.include_router(tasks.router)
app.include_router(dashboard.router)
app.include_router(users.router)
app.include_router(installers.router)
app.include_router(agent.router)
app.include_router(hardware.router)


@app.get("/health")
def health():
    return {"status": "ok"}
