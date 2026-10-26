from contextlib import asynccontextmanager
import logging
from threading import Lock
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .routes import router
from src.config import Config
from src.emdn_importer import load_emdn_database

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.emdn_database = load_emdn_database()
    yield


app = FastAPI(title="Clasificador médico", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(Config.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Key", "X-Admin-User"],
)
app.include_router(router, prefix="/api/v1")

_rate_windows: dict[str, tuple[float, int]] = {}
_rate_lock = Lock()
_last_rate_cleanup = 0.0


@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next):
    global _last_rate_cleanup

    now = monotonic()
    client_ip = request.client.host if request.client else "unknown"
    with _rate_lock:
        if now - _last_rate_cleanup >= Config.RATE_LIMIT_WINDOW_SECONDS:
            _rate_windows.clear()
            _last_rate_cleanup = now

        window_start, count = _rate_windows.get(client_ip, (now, 0))
        if now - window_start >= Config.RATE_LIMIT_WINDOW_SECONDS:
            window_start, count = now, 0
        if count >= Config.RATE_LIMIT_REQUESTS:
            retry_after = max(
                1, int(Config.RATE_LIMIT_WINDOW_SECONDS - (now - window_start))
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Límite de solicitudes excedido; inténtalo más tarde."},
                headers={"Retry-After": str(retry_after)},
            )
        count += 1
        _rate_windows[client_ip] = (window_start, count)

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(Config.RATE_LIMIT_REQUESTS)
    response.headers["X-RateLimit-Remaining"] = str(max(0, Config.RATE_LIMIT_REQUESTS - count))
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "detail": "Solicitud inválida.",
            "errores": jsonable_encoder(exc.errors()),
        },
    )


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")
