import os
import sys
import asyncio
from pathlib import Path
from urllib.parse import parse_qs
import contextvars

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass




from asgiref.sync import sync_to_async
from fastmcp import FastMCP
from core.models import TenantApiKey

_test_session_key: contextvars.ContextVar = contextvars.ContextVar("_test_session_key", default=None)
SESSION_ACCESS_KEYS: dict[str, str] = {}

def _check_key_in_db(key: str) -> bool:
    return TenantApiKey.objects.filter(key=key, is_active=True).exists()

mcp = FastMCP("callcenter-test")

@mcp.tool()
def sample_tool(query: str = "") -> dict:
    key = _test_session_key.get()
    return {"ok": True, "authenticated_key_prefix": key[:10] if key else None, "query": query}

raw_app = mcp.http_app(transport="sse")

class FastMCPSseAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")

            if path.startswith("/sse"):
                query_string = scope.get("query_string", b"").decode("utf-8")
                params = parse_qs(query_string)
                key = params.get("access_key", [None])[0]

                if not key:
                    for header_name, header_val in scope.get("headers", []):
                        h_name = header_name.decode("latin1").lower()
                        if h_name == "x-access-key":
                            key = header_val.decode("latin1").strip()
                            break
                        elif h_name == "authorization":
                            auth_str = header_val.decode("latin1").strip()
                            key = auth_str[7:].strip() if auth_str.startswith("Bearer ") else auth_str
                            break

                if not key:
                    body = "مفتاح الدخول (Access Key) مطلوب. مرره في الرابط ?access_key=... أو في Headers.\n".encode("utf-8")
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode("ascii")),
                        ],
                    })
                    await send({"type": "http.response.body", "body": body})
                    return

                is_valid = await sync_to_async(_check_key_in_db)(key)
                if not is_valid:
                    body = "مفتاح الدخول (Access Key) غير صالح أو تم إيقافه.\n".encode("utf-8")
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode("ascii")),
                        ],
                    })
                    await send({"type": "http.response.body", "body": body})
                    return

                async def intercept_send(message):
                    if message["type"] == "http.response.body":
                        body_chunk = message.get("body", b"").decode("utf-8", errors="ignore")
                        if "session_id=" in body_chunk:
                            try:
                                for part in body_chunk.split():
                                    if "session_id=" in part:
                                        s_id = part.split("session_id=")[-1].strip()
                                        SESSION_ACCESS_KEYS[s_id] = key
                            except Exception:
                                pass
                    await send(message)

                await self.app(scope, receive, intercept_send)
                return

            elif path.startswith("/messages"):
                query_string = scope.get("query_string", b"").decode("utf-8")
                params = parse_qs(query_string)
                s_id = params.get("session_id", [None])[0]
                session_key = SESSION_ACCESS_KEYS.get(s_id) if s_id else None

                if session_key:
                    token = _test_session_key.set(session_key)
                    try:
                        await self.app(scope, receive, send)
                    finally:
                        _test_session_key.reset(token)
                    return

        await self.app(scope, receive, send)

wrapped_app = FastMCPSseAuthMiddleware(raw_app)

import httpx

async def test_all():
    print("Testing SSE Authentication Middleware...")
    valid_key_obj = await TenantApiKey.objects.filter(is_active=True).afirst()
    valid_key = valid_key_obj.key if valid_key_obj else "ak_live_test"
    print(f"Using valid key: {valid_key[:15]}...")


    transport = httpx.ASGITransport(app=wrapped_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Test missing key -> expect 401
        res1 = await client.get("/sse")
        print("1. Missing key status:", res1.status_code, "->", res1.text.strip())
        assert res1.status_code == 401, f"Expected 401, got {res1.status_code}"

        # 2. Test invalid key -> expect 401
        res2 = await client.get("/sse?access_key=ak_live_INVALID_KEY")
        print("2. Invalid key status:", res2.status_code, "->", res2.text.strip())
        assert res2.status_code == 401, f"Expected 401, got {res2.status_code}"

        # 3. Test valid key in header
        res3_header = await client.get("/sse", headers={"X-Access-Key": "ak_live_INVALID_KEY"})
        print("3. Invalid header key status:", res3_header.status_code)
        assert res3_header.status_code == 401

        # 4. Test valid key connection -> expect 200 and endpoint event
        print("4. Testing valid key connection...")
        async with client.stream("GET", f"/sse?access_key={valid_key}") as sse_res:
            print("   Valid connection status:", sse_res.status_code)
            assert sse_res.status_code == 200, f"Expected 200, got {sse_res.status_code}"
            
            endpoint_line = None
            async for line in sse_res.aiter_lines():
                if "endpoint" in line or "session_id=" in line:
                    endpoint_line = line
                    print("   Received SSE event line:", line)
                    break
            
            assert endpoint_line is not None, "Did not receive endpoint event"
            print("   Captured session_id in SESSION_ACCESS_KEYS:", list(SESSION_ACCESS_KEYS.keys()))
            assert len(SESSION_ACCESS_KEYS) > 0, "session_id was not captured in SESSION_ACCESS_KEYS"

        print("✓ ALL TESTS PASSED 100%! SSE AUTH INTERCEPTOR IS FULLY FUNCTIONAL!")

asyncio.run(test_all())

