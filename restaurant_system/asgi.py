import os
from django.core.asgi import get_asgi_application
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant_system.settings')
_raw_django_app = get_asgi_application()
django_application = ASGIStaticFilesHandler(_raw_django_app) if settings.DEBUG else _raw_django_app

from core.mcp_server import get_mcp_asgi_app
mcp_application = get_mcp_asgi_app()


class ASGICORSMiddleware:
    """
    Universal CORS Middleware for all ASGI traffic (Django + FastMCP SSE/Messages/MCP).
    - Automatically handles OPTIONS Preflight requests with 200 OK.
    - Appends Access-Control-Allow-Origin, Allow-Methods, Allow-Headers, Allow-Credentials to all responses.
    - Exposes mcp-session-id and custom headers for third-party servers and web tools.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope.get("method", "GET").upper()

            # Determine request origin (echo requesting origin or default to wildcard)
            origin = b"*"
            for h_name, h_val in scope.get("headers", []):
                if h_name.lower() == b"origin" and h_val:
                    origin = h_val
                    break

            # Handle CORS preflight (OPTIONS)
            if method == "OPTIONS":
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"access-control-allow-origin", origin),
                        (b"access-control-allow-methods", b"GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD"),
                        (b"access-control-allow-headers", b"Authorization, Content-Type, X-Access-Key, X-CSRFToken, mcp-session-id, Accept, Origin, User-Agent, Cache-Control, *"),
                        (b"access-control-expose-headers", b"mcp-session-id, Content-Disposition, *"),
                        (b"access-control-allow-credentials", b"true"),
                        (b"access-control-max-age", b"86400"),
                        (b"content-length", b"0"),
                    ],
                })
                await send({"type": "http.response.body", "body": b""})
                return

            # Intercept response to inject CORS headers
            async def cors_send(message):
                if message.get("type") == "http.response.start":
                    headers = list(message.get("headers", []))
                    if not any(h[0].lower() == b"access-control-allow-origin" for h in headers):
                        headers.append((b"access-control-allow-origin", origin))
                    if not any(h[0].lower() == b"access-control-allow-credentials" for h in headers):
                        headers.append((b"access-control-allow-credentials", b"true"))
                    if not any(h[0].lower() == b"access-control-expose-headers" for h in headers):
                        headers.append((b"access-control-expose-headers", b"mcp-session-id, Content-Disposition, *"))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, cors_send)
            return

        await self.app(scope, receive, send)


async def _raw_application(scope, receive, send):
    """
    Unified ASGI Application for Restaurant Platform & 24/7 Call Center FastMCP:
    - /sse, /messages, /mcp -> FastMCP SSE Starlette Server (AI Call Center)
    - Lifespan events -> Handled by FastMCP Lifespan Manager
    - All other URLs -> Django Core Application (POS, KDS, Admin, Dashboard, APIs)
    """
    scope_type = scope.get("type")

    if scope_type == "lifespan":
        await mcp_application(scope, receive, send)
        return

    if scope_type in ("http", "websocket"):
        path = scope.get("path", "")
        # Route FastMCP Streamable-HTTP & SSE traffic + OAuth discovery
        if path.startswith("/mcp") or path.startswith("/sse") or path.startswith("/messages") or path.startswith("/.well-known"):
            await mcp_application(scope, receive, send)
            return

    await django_application(scope, receive, send)


# Wrap root application in universal ASGI CORS Middleware
application = ASGICORSMiddleware(_raw_application)

