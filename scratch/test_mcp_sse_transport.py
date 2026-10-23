import os
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import django
import asyncio
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from core.models import TenantApiKey
from core.mcp_server import SSEAuthMiddleware, _get_cached_session_key, _set_cached_session_key

async def run_asgi_tests(api_key: str):
    print("=================================================================")
    print("  TESTING ASGI SSE TRANSPORT & UUID SESSION REGEX BINDING")
    print("=================================================================")

    # Mock inner app that emits an SSE chunk containing a standard UUID session_id with hyphens

    # Mock inner app that emits an SSE chunk containing a standard UUID session_id with hyphens
    test_uuid = str(uuid.uuid4())
    print(f"Testing with standard UUID4: {test_uuid}")

    async def mock_app(scope, receive, send):
        # Emit initial SSE event containing the session_id
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/event-stream")]
        })
        body_text = f"event: endpoint\ndata: /messages/?session_id={test_uuid}\n\n"
        await send({
            "type": "http.response.body",
            "body": body_text.encode("utf-8")
        })

    middleware = SSEAuthMiddleware(mock_app)

    # 2. Test Unauthenticated request to /sse (must reject with 401)
    unauth_scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "query_string": b"",
        "headers": []
    }
    sent_messages = []
    async def mock_send(msg):
        sent_messages.append(msg)

    async def mock_recv():
        return {"type": "http.request"}

    await middleware(unauth_scope, mock_recv, mock_send)
    assert sent_messages[0]["status"] == 401, f"Expected 401, got {sent_messages[0]['status']}"
    print(" [1/3] Unauthenticated /sse request rejected with 401: PASS")

    # 3. Test Authenticated request to /sse?access_key=... and capture of full UUID session_id
    auth_scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "query_string": f"access_key={api_key}".encode("utf-8"),
        "headers": []
    }
    sent_messages.clear()
    await middleware(auth_scope, mock_recv, mock_send)
    assert sent_messages[0]["status"] == 200

    # Verify session was cached in Redis with full UUID (not truncated by hyphen)
    cached_key = _get_cached_session_key(test_uuid)
    assert cached_key == api_key, f"Expected key {api_key}, got {cached_key} for UUID {test_uuid}"
    print(f" [2/3] Full UUID session ({test_uuid}) captured and bound in Redis: PASS")

    # 4. Test Authenticated POST /messages/?session_id=<UUID> without passing access_key
    # Middleware must resolve access_key from Redis via session_id
    async def mock_msg_app(scope, receive, send):
        # Inner tool handler receives request with access key resolved
        from core.mcp_server import _current_session_key
        assert _current_session_key.get() == api_key, "ContextVar did not have resolved API key!"
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")]
        })
        await send({
            "type": "http.response.body",
            "body": b'{"jsonrpc": "2.0", "result": "ok"}'
        })

    msg_middleware = SSEAuthMiddleware(mock_msg_app)
    msg_scope = {
        "type": "http",
        "method": "POST",
        "path": "/messages/",
        "query_string": f"session_id={test_uuid}".encode("utf-8"),
        "headers": []
    }
    sent_messages.clear()
    await msg_middleware(msg_scope, mock_recv, mock_send)
    assert sent_messages[0]["status"] == 200
    print(" [3/3] POST /messages/?session_id=<UUID> automatically resolved tenant via Redis: PASS")

    print("\n=================================================================")
    print("  ALL SSE AUTH & UUID SESSION TESTS PASSED WITH 100% SUCCESS!")
    print("=================================================================")

if __name__ == "__main__":
    key_obj = TenantApiKey.objects.filter(is_active=True, tenant__is_active=True).first()
    assert key_obj is not None, "No active API key found"
    asyncio.run(run_asgi_tests(key_obj.key))
