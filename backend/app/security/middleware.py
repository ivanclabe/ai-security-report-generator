"""Per-request context + request metrics (pure ASGI, so SSE streams pass through untouched).

* assigns a request id (returned as X-Request-ID, used as the audit/ops operation id);
* records client IP and user agent for the audit log;
* measures every request and feeds the observability ring buffer; a 5xx also
  becomes a persisted ERROR event.
"""
import time
import uuid

from app.config.settings import get_settings
from app.security.context import RequestMeta, set_request_meta
from app.services.observability import get_observability, route_template


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = f"req-{uuid.uuid4().hex[:12]}"
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client = scope.get("client")
        ip = client[0] if client else None
        if get_settings().trust_proxy_headers and headers.get("x-forwarded-for"):
            ip = headers["x-forwarded-for"].split(",")[0].strip() or ip
        set_request_meta(RequestMeta(request_id=request_id, ip=ip, user_agent=headers.get("user-agent")))

        status = {"code": 500}

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", request_id.encode())]}
            await send(message)

        started = time.monotonic()
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            path = scope.get("path", "")
            if path.startswith("/api/"):
                duration_ms = int((time.monotonic() - started) * 1000)
                observability = get_observability()
                observability.record_request(scope.get("method", "GET"), path, status["code"], duration_ms)
                if status["code"] >= 500:
                    await observability.emit(
                        "ERROR",
                        "request",
                        "http.server_error",
                        f"{scope.get('method')} {route_template(path)} respondió {status['code']}",
                        status=str(status["code"]),
                        duration_ms=duration_ms,
                    )
