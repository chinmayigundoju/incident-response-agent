import logging
import re
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|token|password)([\"']?\s*[:=]\s*[\"']?)([^\s,\"']+)"
)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return SECRET_PATTERN.sub(r"\1\2[REDACTED]", super().format(record))


class MutationRateLimiter:
    def __init__(self, limit: int):
        self.limit = limit
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else now
        bucket = self.requests[key]
        while bucket and timestamp - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(timestamp)
        return True


def security_middleware(
    *, max_request_bytes: int, rate_limit: int
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    limiter = MutationRateLimiter(rate_limit)

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        try:
            request_size = int(content_length) if content_length else 0
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_CONTENT_LENGTH",
                        "message": "Invalid Content-Length header",
                    }
                },
            )
        if request_size < 0 or request_size > max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request too large"}},
            )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(client):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {"code": "RATE_LIMITED", "message": "Mutation rate exceeded"}
                    },
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return middleware
