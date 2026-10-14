"""Punto de entrada: ``uvicorn app.main:app``."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db as database
from .api import auth, films, media, reco, system
from .config import VERSION, get_env
from .services import demo
from .services.errors import NotConfigured, ServiceError


def _static_dir() -> Path | None:
    env = get_env()
    candidates = [env.static_dir] if env.static_dir else []
    candidates += [Path(__file__).resolve().parent.parent / "static",
                   Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"]
    for c in candidates:
        if c and (c / "index.html").exists():
            return c
    return None


def bootstrap_data() -> None:
    """Primera arranque: catálogo semilla y atributos. Es idempotente."""
    with database.session_scope() as db:
        added = demo.load_seed(db)
        filled = demo.ensure_attrs_all(db)
    if added or filled:
        logging.getLogger("claqueta").info("catálogo semilla: +%s películas, %s fichas con atributos", added, filled)


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = get_env()
    logging.basicConfig(level=env.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    database.configure(env.data_dir)
    database.init_db()
    bootstrap_data()
    if not env.disable_scheduler:
        from .scheduler import scheduler

        scheduler.start()
    yield
    if not env.disable_scheduler:
        from .scheduler import scheduler

        scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Claqueta", version=VERSION, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(auth.AuthMiddleware)

    @app.exception_handler(NotConfigured)
    async def _not_configured(_: Request, exc: NotConfigured):
        return JSONResponse({"detail": exc.message, "code": "not_configured"}, status_code=409)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError):
        return JSONResponse({"detail": exc.message, "code": "service_error"}, status_code=502)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()[:3])
        return JSONResponse({"detail": f"Datos no válidos ({msg})", "code": "validation"}, status_code=422)

    for r in (auth.router, system.router, reco.router, films.router, media.router):
        app.include_router(r)

    static = _static_dir()
    if static:
        assets = static / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "No encontrado"}, status_code=404)
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False)
        async def no_front():
            return JSONResponse({"app": "Claqueta", "version": VERSION, "docs": "/api/docs",
                                 "note": "Frontend no compilado: ejecuta `npm run build` en /frontend"})

    return app


app = create_app()
