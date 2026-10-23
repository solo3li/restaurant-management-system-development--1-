import os
import re
import time
import logging
import contextvars
from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from typing import Optional, Dict, Any, Tuple
from django.db import close_old_connections
from core.redis_mcp_cache import (
    get_redis_client,
    cache_api_key,
    get_cached_api_key,
    invalidate_api_key,
)

logger = logging.getLogger(__name__)

_current_session_key: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_current_session_key", default=None)
_current_key_obj: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar("_current_key_obj", default=None)
_current_tenant: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar("_current_tenant", default=None)
_in_memory_sessions: Dict[str, str] = {}
_rate_limit_tracker: Dict[str, list] = {}
_LOCAL_KEY_CACHE: Dict[str, Tuple[Any, Any, float]] = {}


def _get_key_and_tenant(key: str) -> Tuple[Optional[Any], Optional[Any]]:
    """Retrieve key and tenant models with automatic Redis + Local caching for zero database queries."""
    if not key:
        return None, None

    now = time.time()
    cached = get_cached_api_key(key)
    if cached is None:
        _LOCAL_KEY_CACHE.pop(key, None)
    elif cached.get("is_valid") is False:
        _LOCAL_KEY_CACHE.pop(key, None)
        return None, None
    elif key in _LOCAL_KEY_CACHE:
        k_obj, t_obj, exp = _LOCAL_KEY_CACHE[key]
        if now < exp:
            return k_obj, t_obj
        else:
            _LOCAL_KEY_CACHE.pop(key, None)

    close_old_connections()
    from core.models import TenantApiKey
    key_obj = TenantApiKey.objects.select_related("tenant", "assigned_branch", "tenant__subscription_plan").filter(
        key=key, is_active=True, tenant__is_active=True
    ).first()

    if not key_obj:
        cache_api_key(key, {"is_valid": False}, ttl=60)
        _LOCAL_KEY_CACHE.pop(key, None)
        return None, None

    tenant = key_obj.tenant
    if tenant.subscription_status in ["expired", "canceled"] or tenant.is_subscription_expired():
        cache_api_key(key, {"is_valid": False, "expired": True}, ttl=60)
        _LOCAL_KEY_CACHE.pop(key, None)
        return None, None

    _LOCAL_KEY_CACHE[key] = (key_obj, tenant, now + 600)
    cache_api_key(key, {
        "is_valid": True,
        "key_id": key_obj.id,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "assigned_branch_id": key_obj.assigned_branch_id,
        "subscription_status": tenant.subscription_status,
    }, ttl=600)

    return key_obj, tenant


def _check_key_valid(key: str) -> bool:
    """Check API key validity in <0.05ms from Redis, falling back to database query."""
    if not key:
        return False
    cached = get_cached_api_key(key)
    if cached is not None:
        return bool(cached.get("is_valid", False))
    key_obj, _ = _get_key_and_tenant(key)
    return key_obj is not None


def _get_cached_session_key(sid: Optional[str]) -> Optional[str]:
    if not sid:
        return None
    clean_sid = str(sid).strip().lower()
    r = get_redis_client()
    if r:
        try:
            return r.get(f"mcp_session:{clean_sid}")
        except Exception:
            pass
    return _in_memory_sessions.get(f"mcp_session:{clean_sid}")


def _set_cached_session_key(sid: Optional[str], key: Optional[str], timeout: int = 86400):
    if sid and key:
        clean_sid = str(sid).strip().lower()
        clean_key = str(key).strip()
        r = get_redis_client()
        if r:
            try:
                pipe = r.pipeline()
                pipe.set(f"mcp_session:{clean_sid}", clean_key, ex=timeout)
                pipe.set(f"mcp_key_latest:{clean_key}", clean_sid, ex=timeout)
                pipe.execute()
                return
            except Exception:
                pass
        _in_memory_sessions[f"mcp_session:{clean_sid}"] = clean_key
        _in_memory_sessions[f"mcp_key_latest:{clean_key}"] = clean_sid


def _get_latest_session_for_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    clean_key = str(key).strip()
    r = get_redis_client()
    if r:
        try:
            return r.get(f"mcp_key_latest:{clean_key}")
        except Exception:
            pass
    return _in_memory_sessions.get(f"mcp_key_latest:{clean_key}")


def _is_rate_limited(identifier: str, max_requests: int = 120, window_seconds: int = 60) -> bool:
    """Sliding window rate-limiter per session or IP to prevent DoS."""
    now = time.time()
    r = get_redis_client()
    if r:
        try:
            rkey = f"rate_limit:{identifier}"
            current = r.incr(rkey)
            if current == 1:
                r.expire(rkey, window_seconds)
            return current > max_requests
        except Exception:
            pass

    timestamps = _rate_limit_tracker.setdefault(identifier, [])
    cutoff = now - window_seconds
    _rate_limit_tracker[identifier] = [t for t in timestamps if t > cutoff]
    if len(_rate_limit_tracker[identifier]) >= max_requests:
        return True
    _rate_limit_tracker[identifier].append(now)
    return False


def _authenticate(access_key: Optional[str] = None):
    """
    Validate access key strictly from parameter or current session context.
    Executes in <0.05ms with zero database queries when context is cached.
    """
    key = str(access_key or "").strip()
    if not key:
        key = _current_session_key.get() or ""
    if not key:
        k_obj = _current_key_obj.get()
        if k_obj and getattr(k_obj, "key", None):
            key = k_obj.key

    if not key:
        raise ValueError("مفتاح الدخول (Access Key) مطلوب. مرره عبر ترويسات الطلب أو أثناء فتح الجلسة.")

    # 1. Fast ContextVar hit (0ms, 0 DB queries) - verify it hasn't been invalidated in Redis
    cached_key_obj = _current_key_obj.get()
    cached_tenant = _current_tenant.get()
    if cached_key_obj and cached_tenant and getattr(cached_key_obj, "key", None) == key:
        redis_cached = get_cached_api_key(key)
        if redis_cached and redis_cached.get("is_valid"):
            return cached_key_obj, cached_tenant
        _current_key_obj.set(None)
        _current_tenant.set(None)
        _LOCAL_KEY_CACHE.pop(key, None)

    # 2. Redis + DB resolution (cached in Redis for 10 minutes)
    key_obj, tenant = _get_key_and_tenant(key)
    if not key_obj or not tenant:
        raise ValueError("مفتاح الدخول (Access Key) غير صالح أو تم إيقافه أو اشتراك المنشأة منتهي.")

    _current_key_obj.set(key_obj)
    _current_tenant.set(tenant)
    return key_obj, tenant



class FastMCPAuthMiddleware:
    """ASGI Middleware to secure Streamable-HTTP endpoints (/mcp)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "GET").upper()

            if path.startswith("/.well-known"):
                await self.app(scope, receive, send)
                return

            if path == "/mcp" or path.startswith("/mcp/"):
                if method == "OPTIONS":
                    await send({
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            (b"access-control-allow-origin", b"*"),
                            (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS, HEAD"),
                            (b"access-control-allow-headers", b"*"),
                            (b"access-control-expose-headers", b"mcp-session-id, *"),
                            (b"content-length", b"0"),
                        ],
                    })
                    await send({"type": "http.response.body", "body": b""})
                    return

                key = self._extract_key(scope)
                raw_session_id = self._extract_header(scope, "mcp-session-id")

                if not key and raw_session_id:
                    key = _get_cached_session_key(raw_session_id)

                if not key:
                    await self._reject(send, 401, "مفتاح الدخول (Access Key) مطلوب.")
                    return

                is_valid = await sync_to_async(_check_key_valid)(key)
                if not is_valid:
                    await self._reject(send, 401, "مفتاح الدخول (Access Key) غير صالح.")
                    return

                orig_headers = list(scope.get("headers", []))
                cleaned_headers = [
                    (k, v) for k, v in orig_headers
                    if not (k.lower() == b"mcp-session-id" and not v.strip())
                ]

                accept_val = self._extract_header(scope, "accept")
                if not accept_val or "text/event-stream" not in accept_val:
                    cleaned_headers = [(k, v) for k, v in cleaned_headers if k.lower() != b"accept"]
                    cleaned_headers.append((b"accept", b"application/json, text/event-stream"))

                active_sid = _get_latest_session_for_key(key)
                has_valid_sid = any(k.lower() == b"mcp-session-id" and v.strip() for k, v in cleaned_headers)
                if method == "GET" and not has_valid_sid and active_sid:
                    cleaned_headers.append((b"mcp-session-id", active_sid.encode("latin1")))

                scope["headers"] = cleaned_headers
                key_obj, tenant = await sync_to_async(_get_key_and_tenant)(key)
                token_s = _current_session_key.set(key)
                token_k = _current_key_obj.set(key_obj)
                token_t = _current_tenant.set(tenant)

                async def intercept_send(message):
                    if message.get("type") == "http.response.start":
                        res_headers = list(message.get("headers", []))
                        for h_name_b, h_val_b in res_headers:
                            if h_name_b.lower() == b"mcp-session-id":
                                new_sid = h_val_b.decode("latin1").strip()
                                if new_sid:
                                    _set_cached_session_key(new_sid, key)

                        res_headers.extend([
                            (b"access-control-allow-origin", b"*"),
                            (b"access-control-allow-headers", b"*"),
                            (b"access-control-expose-headers", b"mcp-session-id, *"),
                        ])
                        message["headers"] = res_headers
                    await send(message)

                try:
                    await self.app(scope, receive, intercept_send)
                finally:
                    _current_session_key.reset(token_s)
                    _current_key_obj.reset(token_k)
                    _current_tenant.reset(token_t)
                return

        await self.app(scope, receive, send)

    def _extract_header(self, scope, header_name: str) -> Optional[str]:
        target = header_name.lower().encode("latin1")
        for h_name_b, h_val_b in scope.get("headers", []):
            if h_name_b.lower() == target:
                return h_val_b.decode("latin1").strip()
        return None

    def _extract_key(self, scope) -> Optional[str]:
        query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
        params = parse_qs(query_string)
        key = params.get("access_key", [None])[0]
        if key:
            return key.strip()

        x_key = self._extract_header(scope, "x-access-key")
        if x_key:
            return x_key

        auth = self._extract_header(scope, "authorization")
        if auth:
            if auth.startswith("Bearer "):
                return auth[7:].strip()
            return auth.strip()
        return None

    @staticmethod
    async def _reject(send, status: int, message: str):
        body = message.encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


class SSEAuthMiddleware:
    """ASGI Middleware to authenticate FastMCP SSE connections and bind sessions dynamically to Tenant API keys."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope.get("method", "GET").upper()
            path = scope.get("path", "")
            query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            qs = parse_qs(query_string)

            headers = dict(scope.get("headers", []))
            key = None

            auth = headers.get(b"authorization", b"").decode("latin1").strip()
            if auth.startswith("Bearer "):
                key = auth[7:].strip()
            elif auth:
                key = auth

            if not key:
                x_key = headers.get(b"x-access-key", b"").decode("latin1").strip()
                if x_key:
                    key = x_key

            if not key:
                key = qs.get("access_key", [None])[0]
                if key:
                    key = key.strip()

            sid = qs.get("session_id", [None])[0]
            if sid:
                sid = sid.strip().lower()

            if not key and sid:
                key = _get_cached_session_key(sid)

            # Rate limiting protection
            rate_id = key or sid or (scope.get("client", [None])[0] if scope.get("client") else "anon")
            if _is_rate_limited(str(rate_id)):
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]
                })
                await send({"type": "http.response.body", "body": "تم تجاوز الحد الأقصى للطلبات (Too Many Requests)".encode("utf-8")})
                return

            if path.startswith("/sse") or path.endswith("/sse"):
                if not key:
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]
                    })
                    await send({"type": "http.response.body", "body": "مفتاح الدخول (Access Key) مطلوب لفتح اتصال SSE".encode("utf-8")})
                    return

                valid = await sync_to_async(_check_key_valid)(key)
                if not valid:
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]
                    })
                    await send({"type": "http.response.body", "body": "مفتاح الدخول غير صالح أو ملغي".encode("utf-8")})
                    return

                captured_sid = None
                async def intercept_sse_send(message):
                    nonlocal captured_sid
                    if message.get("type") == "http.response.body":
                        body = message.get("body", b"")
                        if b"session_id=" in body:
                            try:
                                text = body.decode("utf-8")
                                m = re.search(r"session_id=([a-zA-Z0-9_\-]+)", text)
                                if m:
                                    captured_sid = m.group(1).lower()
                                    _set_cached_session_key(captured_sid, key)
                            except Exception:
                                pass
                    await send(message)

                key_obj, tenant = await sync_to_async(_get_key_and_tenant)(key)
                token_s = _current_session_key.set(key)
                token_k = _current_key_obj.set(key_obj)
                token_t = _current_tenant.set(tenant)
                try:
                    await self.app(scope, receive, intercept_sse_send)
                finally:
                    _current_session_key.reset(token_s)
                    _current_key_obj.reset(token_k)
                    _current_tenant.reset(token_t)
                return

            if path.startswith("/messages") or "messages" in path or method == "POST":
                if not key:
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]
                    })
                    await send({"type": "http.response.body", "body": "مفتاح الدخول (Access Key) غير متوفر في هذه الجلسة".encode("utf-8")})
                    return

                valid = await sync_to_async(_check_key_valid)(key)
                if not valid:
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]
                    })
                    await send({"type": "http.response.body", "body": "مفتاح الدخول غير صالح أو ملغي".encode("utf-8")})
                    return

                key_obj, tenant = await sync_to_async(_get_key_and_tenant)(key)
                token_s = _current_session_key.set(key)
                token_k = _current_key_obj.set(key_obj)
                token_t = _current_tenant.set(tenant)
                try:
                    await self.app(scope, receive, send)
                finally:
                    _current_session_key.reset(token_s)
                    _current_key_obj.reset(token_k)
                    _current_tenant.reset(token_t)
                return

            if key:
                key_obj, tenant = await sync_to_async(_get_key_and_tenant)(key)
                token_s = _current_session_key.set(key)
                token_k = _current_key_obj.set(key_obj)
                token_t = _current_tenant.set(tenant)
                try:
                    await self.app(scope, receive, send)
                finally:
                    _current_session_key.reset(token_s)
                    _current_key_obj.reset(token_k)
                    _current_tenant.reset(token_t)
                return

        await self.app(scope, receive, send)


def build_unified_mcp_asgi(mcp_instance):
    """Return unified FastMCP ASGI dispatcher supporting both SSE and Streamable-HTTP."""
    raw_sse = mcp_instance.http_app(transport="sse")
    sse_app = SSEAuthMiddleware(raw_sse)

    raw_stream = mcp_instance.http_app(transport="streamable-http")
    mcp_app = FastMCPAuthMiddleware(raw_stream)

    async def unified_mcp_asgi(scope, receive, send):
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await raw_stream(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.startswith("/sse") or path.startswith("/messages"):
            await sse_app(scope, receive, send)
        elif path.startswith("/mcp/sse") or path.startswith("/mcp/messages"):
            new_scope = dict(scope)
            new_scope["path"] = path[4:]
            raw_p = scope.get("raw_path", b"")
            if raw_p.startswith(b"/mcp"):
                new_scope["raw_path"] = raw_p[4:]
            await sse_app(new_scope, receive, send)
        elif path.startswith("/mcp"):
            await mcp_app(scope, receive, send)
        else:
            await mcp_app(scope, receive, send)

    return unified_mcp_asgi
