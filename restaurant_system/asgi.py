import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant_system.settings')
django_application = get_asgi_application()

from core.mcp_server import get_mcp_asgi_app
mcp_application = get_mcp_asgi_app()


async def application(scope, receive, send):
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

