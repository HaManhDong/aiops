from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

log = structlog.get_logger()


def add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        detail = exc.detail

        if isinstance(detail, dict):
            title = detail.get("title", "Error")
        else:
            title = str(detail) if detail else "Error"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://vst-ai.internal/errors/{exc.status_code}",
                "title": title,
                "status": exc.status_code,
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.error(
            "unhandled_exception",
            error=str(exc),
            exc_type=type(exc).__name__,
            request_id=request_id,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "type": "https://vst-ai.internal/errors/500",
                "title": "Internal Server Error",
                "status": 500,
                "request_id": request_id,
            },
        )
