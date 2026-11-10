from pathlib import Path

from starlette.responses import JSONResponse

from config import settings


async def maintenance(request, call_next):
    path = request.url.path
    # Refreshing the session keeps the update page usable during a long task drain.
    # Backend is fully stopped before the database snapshot is taken.
    allowed = path in {"/health", "/auth/refresh"} or path == "/settings/platform" or path.startswith("/settings/platform/")
    if Path(settings.platform_maintenance_file).exists() and not allowed:
        return JSONResponse({"detail": "Идёт обновление платформы. Повторите запрос позже."}, status_code=503,
                            headers={"Retry-After": "30"})
    return await call_next(request)
