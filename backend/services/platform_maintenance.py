from pathlib import Path

from starlette.responses import JSONResponse

from config import settings


async def maintenance(request, call_next):
    path = request.url.path
    if Path(settings.platform_maintenance_file).exists() and path != "/health" and not path.startswith("/settings/platform"):
        return JSONResponse({"detail": "Идёт обновление платформы. Повторите запрос позже."}, status_code=503,
                            headers={"Retry-After": "30"})
    return await call_next(request)
