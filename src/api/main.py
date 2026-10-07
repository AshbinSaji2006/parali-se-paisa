from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import os
import time
import uuid
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import balers, buyers, certificates, dispatch, fields, research, system, verification
from src.db.session import create_schema, make_engine, make_session_factory
from src.api import security


def create_app(database_url: str | None = None, *, initialize_schema: bool = True,
               demo_mode: bool | None = None) -> FastAPI:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    if initialize_schema:
        create_schema(engine)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        engine.dispose()

    app = FastAPI(title="Parali Se Paisa Action Platform API", version="1.0.0",
                  description="Offline-first prototype API. Demo records remain marked synthetic; this is not an operational government service.",
                  lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.demo_mode = demo_mode if demo_mode is not None else os.getenv("DEMO_MODE", "true").lower() == "true"
    security.configure_security(app, app.state.demo_mode)
    origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS must contain explicit origins")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger("parali.api").exception("Unexpected backend error; request_id=%s", request_id)
            response = JSONResponse({"detail": "Unexpected server error", "request_id": request_id}, status_code=500)
        response.headers.update({"X-Request-ID": request_id, "X-Content-Type-Options": "nosniff",
                                 "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
        logging.getLogger("parali.api").info(json.dumps({"event": "http_request", "request_id": request_id,
            "method": request.method, "path": request.url.path, "status": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000)}))
        return response

    from src.api.routes import product
    app.include_router(system.router, prefix="/api/v1")
    app.include_router(security.router, prefix="/api/v1")
    app.include_router(product.public_router, prefix="/api/v1")
    for router in (product.router, fields.router, balers.router, buyers.router, dispatch.router,
                   verification.router, certificates.router, research.router):
        app.include_router(router, prefix="/api/v1", dependencies=[Depends(security.authorize)])
    return app


app = create_app()
