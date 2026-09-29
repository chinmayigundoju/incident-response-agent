import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import api_router, health_router, webhook_router
from app.core.config import get_settings
from app.core.errors import ApplicationError, application_error_handler
from app.core.security import RedactingFormatter, security_middleware

settings = get_settings()
logger = logging.getLogger(__name__)
for handler in logging.getLogger().handlers:
    handler.setFormatter(RedactingFormatter(handler.formatter._fmt if handler.formatter else None))
app = FastAPI(title="Incident Response Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.API_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_exception_handler(ApplicationError, application_error_handler)
app.middleware("http")(
    security_middleware(
        max_request_bytes=settings.API_MAX_REQUEST_BYTES,
        rate_limit=settings.MUTATION_RATE_LIMIT_PER_MINUTE,
    )
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_, exc: RequestValidationError) -> JSONResponse:
    details = [
        {key: value for key, value in error.items() if key not in {"input", "ctx", "url"}}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": details,
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled API error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}},
    )


app.include_router(health_router)
app.include_router(api_router)
app.include_router(webhook_router)
