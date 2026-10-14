import os
import sys
import json
import random
from decimal import Decimal
from typing import List, Dict, Any, Optional, Union
import re

# Ensure UTF-8 encoding on standard streams for JSON-RPC across all platforms
try:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Ensure Django settings are initialized if running directly
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")


import django
from django.conf import settings
if not settings.configured:
    django.setup()

from django.db import models, transaction, IntegrityError
from django.utils import timezone
from fastmcp import FastMCP
import contextvars
from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field


class OrderItemInput(BaseModel):
    """عنصر مطلوب من قائمة الطعام مع الكمية"""
    name: str = Field(description="اسم الصنف المطلوب كما في المنيو (مثال: شاي كرك، مندي لحم، كبسة دجاج)")
    quantity: int = Field(default=1, ge=1, description="الكمية المطلوبة (افتراضياً 1)")


_current_session_key: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_current_session_key", default=None)
SESSION_ACCESS_KEYS: dict[str, str] = {}
KEY_LATEST_SESSION: dict[str, str] = {}

# Initialize FastMCP Server
mcp = FastMCP(
    name="Restaurant Call Center AI",
    instructions=(
        "خادم كول سنتر ذكي مخصص لإدارة واستقبال طلبات المطاعم. "
        "يتيح البحث عن العملاء برقم الهاتف، استعراض فروع المطعم، جلب قائمة الطعام والأسعار المحدثة، "
        "التحقق من تغطية التوصيل ومناطق الكومبوندات، وإنشاء (ضرب) أوردرات الكول سنتر وتتبع حالتها."
    )
)


def _check_key_valid(key: str) -> bool:
    from core.models import TenantApiKey
    return TenantApiKey.objects.filter(key=key, is_active=True, tenant__is_active=True).exists()


class FastMCPAuthMiddleware:
    """
    ASGI Middleware to secure FastMCP Streamable-HTTP endpoints (/mcp, /sse).
    Features:
      - Authenticates via ?access_key=..., X-Access-Key, Authorization header, or mcp-session-id.
      - Handles CORS preflight (OPTIONS) requests.
      - Exposes 'mcp-session-id' header via Access-Control-Expose-Headers so Electron/Web clients can capture it.
      - Auto-heals requests where client loses or omits session ID (e.g., subscriptions/listen) by attaching active session.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "GET").upper()

            # Allow OAuth discovery and health endpoints without auth
            if path.startswith("/.well-known"):
                await self.app(scope, receive, send)
                return

            # Intercept /mcp endpoint (Streamable HTTP transport)
            if path == "/mcp" or path.startswith("/mcp/"):
                # Handle CORS preflight
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

                # If session ID was provided and valid in cache, retrieve key
                if not key and raw_session_id and raw_session_id in SESSION_ACCESS_KEYS:
                    key = SESSION_ACCESS_KEYS[raw_session_id]

                # Fallback to key associated with latest active session
                if not key and raw_session_id:
                    for k, sid in list(KEY_LATEST_SESSION.items()):
                        if sid == raw_session_id:
                            key = k
                            break

                if not key:
                    await self._reject(send, 401, "مفتاح الدخول (Access Key) مطلوب. مرره في ?access_key=... أو عبر Headers.")
                    return

                is_valid = await sync_to_async(_check_key_valid)(key)
                if not is_valid:
                    await self._reject(send, 401, "مفتاح الدخول (Access Key) غير صالح أو تم إيقافه.")
                    return

                # Clean scope headers: remove any empty mcp-session-id header
                orig_headers = list(scope.get("headers", []))
                cleaned_headers = [
                    (k, v) for k, v in orig_headers
                    if not (k.lower() == b"mcp-session-id" and not v.strip())
                ]

                # Ensure accept header includes application/json and text/event-stream for FastMCP Streamable HTTP
                accept_val = self._extract_header(scope, "accept")
                if not accept_val or "text/event-stream" not in accept_val:
                    cleaned_headers = [(k, v) for k, v in cleaned_headers if k.lower() != b"accept"]
                    cleaned_headers.append((b"accept", b"application/json, text/event-stream"))

                # For GET requests (listening to stream): auto-inject session ID if known
                active_sid = KEY_LATEST_SESSION.get(key)
                has_valid_sid = any(k.lower() == b"mcp-session-id" and v.strip() for k, v in cleaned_headers)
                if method == "GET" and not has_valid_sid and active_sid:
                    cleaned_headers.append((b"mcp-session-id", active_sid.encode("latin1")))

                scope["headers"] = cleaned_headers

                # Set key in contextvar so MCP tools can access it via _authenticate()
                token = _current_session_key.set(key)

                # Intercept response to catch newly issued mcp-session-id and attach CORS expose headers
                async def intercept_send(message):
                    if message.get("type") == "http.response.start":
                        res_headers = list(message.get("headers", []))
                        for h_name_b, h_val_b in res_headers:
                            if h_name_b.lower() == b"mcp-session-id":
                                new_sid = h_val_b.decode("latin1").strip()
                                if new_sid:
                                    SESSION_ACCESS_KEYS[new_sid] = key
                                    KEY_LATEST_SESSION[key] = new_sid

                        # Append CORS and Expose-Headers so clients in Electron/Web can read mcp-session-id
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
                    _current_session_key.reset(token)
                return

        await self.app(scope, receive, send)

    def _extract_header(self, scope, header_name: str) -> Optional[str]:
        target = header_name.lower().encode("latin1")
        for h_name_b, h_val_b in scope.get("headers", []):
            if h_name_b.lower() == target:
                return h_val_b.decode("latin1").strip()
        return None

    def _extract_key(self, scope) -> Optional[str]:
        """Extract access key from query params or headers."""
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
    """
    ASGI Middleware to authenticate FastMCP SSE connections and bind sessions dynamically to Tenant API keys.
    Features:
    - Zero hardcoding: completely dynamic per tenant and per session.
    - SSE Endpoint Rewrite: Appends &access_key=<key> to the endpoint sent to the client.
    - In-Memory Session Table: Maps session_id -> access_key so subsequent POST /messages/ automatically resolve the tenant.
    - Strict Multi-Tenant Isolation: Sets ContextVar for the current request so tools operate strictly within the tenant's data.
    """
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

            # 1. Try to extract key directly from headers
            auth = headers.get(b"authorization", b"").decode("latin1").strip()
            if auth.startswith("Bearer "):
                key = auth[7:].strip()
            elif auth:
                key = auth

            if not key:
                x_key = headers.get(b"x-access-key", b"").decode("latin1").strip()
                if x_key:
                    key = x_key

            # 2. Try to extract key from query parameters
            if not key:
                key = qs.get("access_key", [None])[0]
                if key:
                    key = key.strip()

            # 3. For POST /messages: if key not passed directly, lookup by session_id in dynamic session table
            sid = qs.get("session_id", [None])[0]
            if sid:
                sid = sid.strip().lower()

            if not key and sid and sid in SESSION_ACCESS_KEYS:
                key = SESSION_ACCESS_KEYS[sid]

            # 4. Handle GET /sse connection (Opening SSE stream)
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

                # Intercept outgoing SSE chunks to capture session_id and rewrite endpoint URL
                captured_sid = None

                async def intercept_sse_send(message):
                    nonlocal captured_sid
                    if message.get("type") == "http.response.body":
                        body = message.get("body", b"")
                        if b"session_id=" in body:
                            try:
                                text = body.decode("utf-8")
                                m = re.search(r"session_id=([0-9a-fA-F]+)", text)
                                if m:
                                    captured_sid = m.group(1).lower()
                                    # Dynamically bind session_id to this tenant's API key
                                    SESSION_ACCESS_KEYS[captured_sid] = key
                                    # Rewrite endpoint line to include &access_key=key so standard clients preserve it
                                    if "access_key=" not in text:
                                        new_text = re.sub(r"(data: [^\r\n]+)", r"\1&access_key=" + key, text)
                                        new_msg = dict(message)
                                        new_msg["body"] = new_text.encode("utf-8")
                                        await send(new_msg)
                                        return
                            except Exception:
                                pass
                    await send(message)

                token = _current_session_key.set(key)
                try:
                    await self.app(scope, receive, intercept_sse_send)
                finally:
                    _current_session_key.reset(token)
                return

            # 5. Handle POST /messages (Calling MCP tools)
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

                token = _current_session_key.set(key)
                try:
                    await self.app(scope, receive, send)
                finally:
                    _current_session_key.reset(token)
                return

            # 6. Any other requests
            if key:
                token = _current_session_key.set(key)
                try:
                    await self.app(scope, receive, send)
                finally:
                    _current_session_key.reset(token)
                return

        await self.app(scope, receive, send)


def get_mcp_asgi_app():
    """Return unified FastMCP ASGI dispatcher supporting both SSE (/sse, /messages) and Streamable-HTTP (/mcp)."""
    raw_sse = mcp.http_app(transport="sse")
    sse_app = SSEAuthMiddleware(raw_sse)

    raw_stream = mcp.http_app(transport="streamable-http")
    mcp_app = FastMCPAuthMiddleware(raw_stream)

    async def unified_mcp_asgi(scope, receive, send):
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            # Driving raw_stream lifespan initializes FastMCPStreamableHTTPSessionManager
            # and internally runs the underlying server lifespan manager for both transports!
            await raw_stream(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.startswith("/sse") or path.startswith("/messages"):
            await sse_app(scope, receive, send)
        elif path.startswith("/mcp/sse") or path.startswith("/mcp/messages"):
            new_scope = dict(scope)
            new_scope["path"] = path[4:]  # strip '/mcp'
            await sse_app(new_scope, receive, send)
        elif path.startswith("/mcp"):
            await mcp_app(scope, receive, send)
        else:
            await mcp_app(scope, receive, send)

    return unified_mcp_asgi



def _authenticate(access_key: Optional[str] = None):
    """Validate access key (from parameter, session context, or RESTAURANT_ACCESS_KEY env) and check tenant subscription status."""
    key = str(access_key or "").strip()
    if not key:
        key = _current_session_key.get() or ""
    if not key:
        key = os.environ.get("RESTAURANT_ACCESS_KEY", "").strip()

    if not key:
        raise ValueError("مفتاح الدخول (Access Key) مطلوب. مرره كمعامل access_key أو في رابط الاتصال ?access_key=...")

    from core.models import TenantApiKey
    key_obj = TenantApiKey.objects.select_related("tenant", "assigned_branch", "tenant__subscription_plan").filter(
        key=key,
        is_active=True
    ).first()

    if not key_obj:
        raise ValueError("مفتاح الدخول (Access Key) غير صالح أو تم إيقافه.")

    tenant = key_obj.tenant
    if not tenant.is_active:
        raise ValueError(f"منشأة المطعم «{tenant.name}» معطلة حالياً في المنصة.")

    if tenant.subscription_status in ["expired", "canceled"] or tenant.is_subscription_expired():
        raise ValueError(f"اشتراك منشأة «{tenant.name}» منتهي أو ملغي. يرجى تجديد الاشتراك أولاً.")


    return key_obj, tenant



@mcp.tool
def get_branches(access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    جلب قائمة الفروع المتاحة للمنشأة المرتبطة بمفتاح الـ API.
    
    Args:
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch

    qs = Branch.objects.filter(tenant=tenant, status="active")
    if key_obj.assigned_branch:
        qs = qs.filter(id=key_obj.assigned_branch_id)

    branches_data = []
    for b in qs:
        areas_count = b.delivery_areas.filter(is_active=True).count()
        branches_data.append({
            "id": b.id,
            "name": b.name,
            "city": b.city,
            "address": b.address,
            "phone": b.phone,
            "delivery_radius_km": float(b.delivery_radius_km),
            "delivery_areas_count": areas_count,
        })

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "tenant_name": tenant.name,
        "branches_count": len(branches_data),
        "branches": branches_data,
    }


def _normalize_digits(text: Any) -> str:
    """تحويل الأرقام المشرقية والعربية (٠-٩) إلى أرقام قياسية (0-9)."""
    if not text:
        return ""
    hindi_to_arabic = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return str(text).translate(hindi_to_arabic)


def _strip_al(w: str) -> str:
    """إزالة أداة التعريف (ال) للمقارنة الدقيقة للأطعمة والمناطق."""
    if w.startswith("ال") and len(w) > 3:
        return w[2:]
    return w


def _normalize_arabic_text(text: str) -> str:
    """تسوية النصوص العربية للمطابقة الدقيقة مع الأصناف والمناطق."""
    if not text:
        return ""
    t = _normalize_digits(str(text)).strip().lower()
    t = re.sub(r'[\u064B-\u0652]', '', t)
    t = re.sub(r'[أإآٱ]', 'ا', t)
    t = re.sub(r'[ىي]', 'ي', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _canonical_food_name(text: str) -> str:
    """
    محرك المرادفات اللغوية والشعبية للأطعمة والمشروبات:
    يوحد لهجات العملاء الشائعة (فراخ -> دجاج، لحمة -> لحم، كولا -> مشروب غازي)
    ويحذف الكلمات التمهيدية والزوائد الشائعة في المحادثة الصوتية.
    """
    norm = _normalize_arabic_text(text)
    words = norm.split()
    
    synonyms = {
        "فراخ": "دجاج",
        "فرخه": "دجاج",
        "دجاجة": "دجاج",
        "دجاجه": "دجاج",
        "تشيكن": "دجاج",
        "تشكن": "دجاج",
        "لحمه": "لحم",
        "لحمة": "لحم",
        "برجر": "برجر",
        "بورجر": "برجر",
        "سنجل": "سينجل",
        "دبل": "دبل",
        "دابل": "دبل",
        "بطاطس": "بطاطس",
        "فرنش": "بطاطس",
        "فرايز": "بطاطس",
        "حار": "حار",
        "سبايسي": "حار",
        "حاره": "حار",
        "حارة": "حار",
        "موتزاريلا": "موزاريلا",
        "موتزريلا": "موزاريلا",
        "موزريلا": "موزاريلا",
        "ضاني": "غنم",
        "ضان": "غنم",
        "خروف": "غنم",
        "بيبسي": "مشروب غازي",
        "كولا": "مشروب غازي",
        "كوكاكولا": "مشروب غازي",
        "كوكا": "مشروب غازي",
        "سفن": "مشروب غازي",
        "سبرايت": "مشروب غازي",
        "كانز": "مشروب غازي",
        "ميه": "ماء صحي",
        "مياه": "ماء صحي",
        "مويه": "ماء صحي",
        "صياد": "صياديه",
        "سمكه": "سمك",
        "شيش": "شيش طاووق",
    }
    
    fillers = {"وجبه", "وجبة", "ساندوتش", "سندوتش", "سندوتشات", "ساندويتش", "ساندويتشات", "طبق", "علبه", "علبة", "طلب", "واحد", "اثنين", "عدد"}
    cleaned = []
    for w in words:
        base_w = _strip_al(w)
        if base_w in fillers and len(words) > 1:
            continue
        cleaned.append(synonyms.get(base_w, synonyms.get(w, base_w)))
        
    res = " ".join(cleaned)
    res = res.replace("صياد سمك", "صياديه سمك")
    return re.sub(r'\s+', ' ', res).strip()


def _clean_phone(phone: Any) -> str:
    """تنظيف وتوحيد رقم الهاتف لتسهيل البحث والمطابقة."""
    if not phone:
        return ""
    p = _normalize_digits(str(phone)).strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if p.startswith("+"):
        p = p[1:]
    return p


def _parse_natural_order_text(text: str, tenant=None, branch=None) -> List[Dict[str, Any]]:
    """تحليل النص العامي إلى قائمة أصناف وكميات مرنة للمكالمات الصوتية."""
    if not text or not isinstance(text, str):
        return []

    clean_text = _normalize_arabic_text(str(text))
    num_map = {
        "واحد": 1, "واحده": 1, "واحدة": 1, "١": 1, "1": 1,
        "اتنين": 2, "اثنين": 2, "إثنين": 2, "٢": 2, "2": 2,
        "تلاتة": 3, "ثلاثة": 3, "٣": 3, "3": 3,
        "اربعة": 4, "أربعة": 4, "٤": 4, "4": 4,
        "خمسة": 5, "٥": 5, "5": 5,
        "ستة": 6, "٦": 6, "6": 6,
    }

    # تقطيع الجملة بناءً على الفواصل وحرف العطف و (مع استثناء كلمات مثل وجبة)
    segments = re.split(r'[,،\n\+]|\s+و(?!\w*جبة)', clean_text)
    items = []

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        qty = 1
        name_candidate = seg
        # فحص وجود رقم في البداية: "2 برجر دبل" أو "اتنين دبل تشيز برجر"
        m_lead = re.match(r'^(?:عدد\s+)?(\d+|واحد|واحده|واحدة|اتنين|اثنين|إثنين|تلاتة|ثلاثة|اربعة|أربعة|خمسة|ستة)\s*(?:من\s+)?(?:قطع\s+|قطعة\s+|وجبة\s+|ساندوتش\s+)?(.+)$', seg)
        if m_lead:
            raw_qty, name_candidate = m_lead.group(1), m_lead.group(2)
            qty = num_map.get(raw_qty, int(raw_qty) if raw_qty.isdigit() else 1)
        else:
            m_trail = re.match(r'^(.+?)\s+(\d+|واحد|واحده|واحدة|اتنين|اثنين|تلاتة|ثلاثة)$', seg)
            if m_trail:
                name_candidate, raw_qty = m_trail.group(1), m_trail.group(2)
                qty = num_map.get(raw_qty, int(raw_qty) if raw_qty.isdigit() else 1)

        name_candidate = name_candidate.strip()
        if name_candidate:
            items.append({"name": name_candidate, "quantity": max(1, qty)})

    return items


def _find_menu_item(tenant, branch, item_spec: Any, disabled_item_ids: set) -> tuple[Optional[Any], Optional[str]]:
    """
    محرك بحث ومطابقة ذكي وشامل للأصناف (Smart Resilient Item Resolver):
    1. التحقق بواسطة item_id أو id المباشر.
    2. التحقق الدقيق بواسطة الاسم وقاموس مرادفات اللهجات (فراخ -> دجاج، لحمة -> لحم).
    3. التحقق بتطابق الكلمات والكلمات الجزئية.
    4. فحص توفر الصنف في الفرع الحالي.
    """
    from core.models import MenuItem

    if hasattr(item_spec, "model_dump"):
        item_spec = item_spec.model_dump()
    elif hasattr(item_spec, "dict"):
        item_spec = item_spec.dict()
    elif isinstance(item_spec, str):
        try:
            item_spec = json.loads(item_spec)
        except Exception:
            item_spec = {"name": item_spec}

    if not isinstance(item_spec, dict):
        item_spec = {"name": str(item_spec)}

    raw_id = item_spec.get("item_id") if item_spec.get("item_id") is not None else item_spec.get("id")
    raw_name = str(item_spec.get("name") or item_spec.get("item_name") or "").strip()

    # 1. البحث برقم الصنف (ID)
    if raw_id is not None:
        try:
            m_id = int(raw_id)
            item = MenuItem.objects.filter(tenant=tenant, id=m_id, available=True).first()
            if not item:
                return None, f"الصنف برقم #{m_id} غير موجود في قائمة طعام المنشأة."
            if item.id in disabled_item_ids:
                return None, f"الصنف «{item.name}» (رقم #{item.id}) غير متوفر حالياً في فرع «{branch.name}»."
            return item, None
        except (ValueError, TypeError):
            pass

    # 2. البحث بالاسم
    if not raw_name:
        return None, "يجب تحديد رقم الصنف (item_id) أو اسمه (name) في عناصر الطلب."

    all_tenant_items = list(MenuItem.objects.filter(tenant=tenant, available=True))
    norm_query = _normalize_arabic_text(raw_name)
    canon_query = _canonical_food_name(raw_name)

    # 2.1 المطابقة بعد تطبيق قاموس المرادفات
    for m in all_tenant_items:
        if _canonical_food_name(m.name) == canon_query:
            if m.id in disabled_item_ids:
                return None, f"الصنف «{m.name}» غير متوفر حالياً في فرع «{branch.name}»."
            return m, None

    # 2.2 المطابقة التامة بعد التسوية العادية
    for m in all_tenant_items:
        if _normalize_arabic_text(m.name) == norm_query:
            if m.id in disabled_item_ids:
                return None, f"الصنف «{m.name}» غير متوفر حالياً في فرع «{branch.name}»."
            return m, None

    # 2.3 المطابقة بمجموعة الكلمات الأساسية
    q_tokens = set(canon_query.split())
    if q_tokens:
        token_matches = [m for m in all_tenant_items if q_tokens.issubset(set(_canonical_food_name(m.name).split()))]
        if len(token_matches) == 1:
            matched = token_matches[0]
            if matched.id in disabled_item_ids:
                return None, f"الصنف «{matched.name}» غير متوفر حالياً في فرع «{branch.name}»."
            return matched, None
        elif len(token_matches) > 1:
            matching_names = " أو ".join([f"«{m.name}» (رقم #{m.id})" for m in token_matches[:4]])
            return None, f"اسم الصنف «{raw_name}» غير محدد بدقة ويطابق أكثر من صنف: ({matching_names}). يرجى تحديد الاسم بالكامل أو استخدام رقم الصنف."

    # 2.4 مطابقة الاحتواء الجزئي
    contains_matches = [
        m for m in all_tenant_items
        if (canon_query in _canonical_food_name(m.name) or _canonical_food_name(m.name) in canon_query)
    ]
    if len(contains_matches) == 1:
        matched = contains_matches[0]
        if matched.id in disabled_item_ids:
            return None, f"الصنف «{matched.name}» غير متوفر حالياً في فرع «{branch.name}»."
        return matched, None

    # 2.5 في حال عدم العثور عليه
    available_branch_items = [m.name for m in all_tenant_items if m.id not in disabled_item_ids][:5]
    suggest_str = "، ".join(available_branch_items)
    return None, f"الصنف «{raw_name}» غير موجود في قائمة طعام المطعم. من الأصناف المتوفرة: {suggest_str}."


def _validate_delivery_address_completeness(
    clean_addr: str,
    matched_area_name: str = ""
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    التحقق الذكي المتكيف من اكتمال عنوان التوصيل وفقاً للنمط الجغرافي والعمراني للمنطقة (5 أنماط):
    1. المدن الجديدة بنظام الأحياء والمجاورات (زايد، أكتوبر، الشروق، العبور، 15 مايو، بدر، العاشر)
    2. الكمبوندات السكنية المغلقة (مدينتي، الرحاب، هايد بارك، ميفيدا، بادية، سوديك، بالم هيلز...)
    3. المولات والمقرات الإدارية والتجارية (مول مصر، مول العرب، كايرو فيستيفال، القرية الذكية...)
    4. المناطق المقسمة بالنمر والفيلات (التجمع الخامس، النرجس، الياسمين، البنفسج، بيت الوطن...)
    5. الشوارع التقليدية والمناطق الحضرية العامة (المعادي، مصر الجديدة، مدينة نصر، المهندسين، الدقي، فيصل...)
    """
    raw_addr = str(clean_addr or "").strip()
    if not raw_addr:
        return False, {
            "ok": False,
            "is_system_error": False,
            "status": "address_details_required",
            "error": "عنوان التوصيل فارغ أو غير محدد.",
            "ai_speech_response": "يا فندم محتاجة أعرف عنوان التوصيل بالتفصيل عشان أقدر أسجل لحضرتك الأوردر.",
            "instruction_for_ai": "اطلب من العميل تزويدك بعنوان التوصيل بالتفصيل كما في ai_speech_response ولا تقل إن هناك عطلاً بالسيستم."
        }

    norm_addr = _normalize_arabic_text(raw_addr)
    norm_area = _normalize_arabic_text(matched_area_name)
    combined = f"{norm_area} {norm_addr}".strip()
    words = norm_addr.split()

    area_label = matched_area_name.strip() if matched_area_name.strip() else raw_addr.split("،")[0].split("-")[0].strip()

    # Generic building / property tokens
    bldg_tokens = ["عماره", "فيلا", "بلوك", "قطعه", "منزل", "بيت", "برج", "مبني"]
    has_bldg = any(t in norm_addr for t in bldg_tokens)

    # Unit / Floor tokens
    unit_tokens = ["شقه", "دور", "طابق", "ارضي", "وحده", "سويت", "مكتب", "استوديو"]
    has_unit = any(t in norm_addr for t in unit_tokens)

    # Commercial tokens
    comm_tokens = ["محل", "معرض", "شركه", "مكتب", "عياده", "كافيه", "مطعم", "فرع", "بنك", "معمل", "ستور", "store"]
    has_comm = any(t in norm_addr for t in comm_tokens)

    # Numbers (digits or written ordinals)
    has_num = bool(
        re.search(r'\d+', norm_addr) or
        re.search(r'\b(اول|الاول|تاني|التاني|ثاني|الثاني|تالت|التالت|ثالث|الثالث|رابع|الرابع|خامس|الخامس|سادس|السادس|سابع|السابع|تامن|التامن|ثامن|الثامن|تاسع|التاسع|عاشر|العاشر|ارضي|الارضي|اخير|الاخير)\b', norm_addr)
    )

    # 1. Typology: Malls & Commercial / Business Centers
    mall_keywords = [
        "مول", "mall", "كايرو فيستيفال", "سيتي ستارز", "اركان", "القريه الذكيه",
        "بيزنس بارك", "داون تاون", "سنتر", "مبني اداري", "مجمع البنوك", "بوينت 90",
        "امريكانا بلازا", "ميدتاون", "مجره"
    ]
    is_mall = any(k in combined for k in mall_keywords)
    if is_mall:
        mall_complete = has_comm and (has_unit or "بوابه" in norm_addr or len(words) >= 4)
        if not mall_complete:
            speech = f"يا فندم محتاجة أعرف اسم المحل أو الشركة أو المكتب في {area_label}، والدور أو أقرب بوابة عشان يوصلك الطلب بسرعة وبدون تأخير."
            return False, {
                "ok": False,
                "is_system_error": False,
                "status": "address_details_required",
                "typology": "commercial_mall",
                "area_name": area_label,
                "error": f"العنوان في المول/المركز التجاري «{area_label}» يتطلب اسم المحل/الشركة ورقم الدور أو البوابة.",
                "ai_speech_response": speech,
                "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل نصاً: «{speech}» لتسجيل اسم المحل والدور بدقة ولا تقل إن هناك عطلاً بالسيستم."
            }
        return True, None

    # 2. Typology: Gated Communities / Compounds
    compound_keywords = [
        "كمبوند", "كومبوند", "مدينتي", "مدينتى", "الرحاب", "رحاب", "هايد بارك",
        "ميفيدا", "باديه", "بادية", "سوديك", "بالم هيلز", "ماونتن فيو", "الربوه",
        "الربوة", "بيفرلي", "سوان ليك", "اب تاون", "تاج سيتي", "ليان", "ديره",
        "زاد", "zed", "الياسمين ريزيدنس"
    ]
    is_compound = any(k in combined for k in compound_keywords)
    if is_compound:
        cmpnd_group_tokens = ["مجموعه", "مرحله", "زون", "zone", "قطاع", "جروب", "group", "فيلات", "عمارات", "حرف",
                              "b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8", "b9", "b10", "b11", "b12"]
        has_group = any(t in norm_addr for t in cmpnd_group_tokens)
        compound_complete = (
            (has_group or has_bldg) and
            (has_unit or "فيلا" in norm_addr or "بوابه" in norm_addr) and
            has_num and
            len(words) >= 4
        )
        if not compound_complete:
            speech = f"يا فندم محتاجة أعرف في {area_label} رقم المجموعة أو المرحلة، ورقم العمارة أو الفيلا ورقم الشقة أو البوابة عشان كابتن التوصيل يدخل لحضرتك علطول."
            return False, {
                "ok": False,
                "is_system_error": False,
                "status": "address_details_required",
                "typology": "gated_compound",
                "area_name": area_label,
                "error": f"العنوان في الكمبوند «{area_label}» يتطلب رقم المجموعة/المرحلة والعمارة/الفيلا ورقم الشقة/البوابة.",
                "ai_speech_response": speech,
                "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل نصاً: «{speech}» لتسجيل تفاصيل الكمبوند بدقة ولا تقل إن هناك عطلاً بالسيستم."
            }
        return True, None

    # 3. Typology: New Cities with Neighborhoods & Districts (الأحياء والمجاورات)
    new_city_keywords = [
        "زايد", "الشيخ زايد", "اكتوبر", "السادس من اكتوبر", "العاشر", "رمضان",
        "الشروق", "شروق", "العبور", "عبور", "15 مايو", "مايو", "بدر", "السادات",
        "برج العرب", "حدائق الاهرام", "هضبه الاهرام", "حدائق اكتوبر"
    ]
    is_new_city = any(k in combined for k in new_city_keywords)
    if is_new_city:
        has_district_or_mogaweera = any(t in norm_addr for t in ["حي", "الحي", "مجاوره", "منطقه"])
        new_city_complete = (
            (has_district_or_mogaweera or len(words) >= 5) and
            (has_bldg or "مجاوره" in norm_addr) and
            (has_unit or "فيلا" in norm_addr) and
            has_num and
            len(words) >= 4
        )
        if not new_city_complete:
            speech = f"يا فندم محتاجة أعرف في {area_label} الحي والمجاورة كام ورقم العمارة والدور والشقة عشان نوصل الطلب لحضرتك بالظبط."
            return False, {
                "ok": False,
                "is_system_error": False,
                "status": "address_details_required",
                "typology": "new_city_districts",
                "area_name": area_label,
                "error": f"العنوان في «{area_label}» يتطلب تحديد الحي ورقم المجاورة والعمارة ورقم الدور والشقة.",
                "ai_speech_response": speech,
                "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل نصاً: «{speech}» لتسجيل الحي والمجاورة والعمارة والشقة بدقة ولا تقل إن هناك عطلاً بالسيستم."
            }
        return True, None

    # 4. Typology: Subdivided Zones & Villas (التجمع والتقسيمات)
    subdivided_keywords = [
        "تجمع", "التجمع", "النرجس", "الياسمين", "البنفسج", "اللوتس", "بيت الوطن",
        "الاندلس", "المستثمرين", "جنوب الاكاديميه", "غرب الجولف", "شمال الرحاب",
        "الشويفات", "الدبلوماسيين", "القاهره الجديده"
    ]
    is_subdivided = any(k in combined for k in subdivided_keywords)
    if is_subdivided:
        subdivided_complete = (
            (has_bldg or "فيلا" in norm_addr) and
            (has_unit or "فيلا" in norm_addr) and
            has_num and
            len(words) >= 4
        )
        if not subdivided_complete:
            speech = f"يا فندم محتاجة أعرف في {area_label} المنطقة أو النمرة كام بالتحديد (زي نرجس كام أو الحي الكام)، ورقم الفيلا أو العمارة والدور والشقة."
            return False, {
                "ok": False,
                "is_system_error": False,
                "status": "address_details_required",
                "typology": "subdivided_villas",
                "area_name": area_label,
                "error": f"العنوان في «{area_label}» يتطلب تحديد المنطقة/النمرة ورقم الفيلا أو العمارة والدور والشقة.",
                "ai_speech_response": speech,
                "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل نصاً: «{speech}» لتسجيل رقم المنطقة والفيلا/العمارة والشقة بدقة ولا تقل إن هناك عطلاً بالسيستم."
            }
        return True, None

    # 5. Typology: Traditional Urban Streets & General Areas
    street_complete = (
        (has_bldg or "فيلا" in norm_addr or "منزل" in norm_addr) and
        (has_unit or "فيلا" in norm_addr) and
        has_num and
        len(words) >= 4
    )
    if not street_complete:
        if area_label and not area_label.startswith("شارع"):
            speech = f"يا فندم محتاجة أعرف في {area_label} اسم الشارع بالظبط، ورقم العمارة والدور ورقم الشقة أو أقرب علامة مميزة عشان كابتن التوصيل يوصل لحضرتك بسهولة."
        else:
            speech = "يا فندم محتاجة أعرف اسم الشارع بالظبط، ورقم العمارة والدور ورقم الشقة أو أقرب علامة مميزة عشان كابتن التوصيل يوصل لحضرتك بسهولة."
        return False, {
            "ok": False,
            "is_system_error": False,
            "status": "address_details_required",
            "typology": "traditional_street",
            "area_name": area_label,
            "error": f"العنوان يتطلب اسم الشارع ورقم العمارة والدور ورقم الشقة.",
            "ai_speech_response": speech,
            "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل نصاً: «{speech}» لتسجيل الشارع والعمارة والدور والشقة بدقة ولا تقل إن هناك عطلاً بالسيستم."
        }

    return True, None


def _resolve_delivery_coverage_and_branch(
    tenant,
    customer_address: str,
    branch_id: Optional[int] = None,
    delivery_area_id: Optional[int] = None,
    delivery_area_name: Optional[str] = None
) -> tuple[Optional[Any], Optional[Any], Optional[Dict[str, Any]]]:
    """
    محرك التوجيه الجغرافي الشامل وفحص التغطية لجميع الفروع:
    1. إذا لم يُمرر branch_id، يفحص كافة فروع المنشأة النشطة ويختار تلقائياً الفرع الذي يغطي الحي.
    2. يدعم المطابقة المرنة للأحياء والكومبوندات حتى لو ذكر العميل تفاصيل إضافية (شارع، عمارة، شقة).
    3. إذا كان خارج التغطية، يُرجع رداً صوتياً مهذباً يقترح الاستلام من الفرع دون إرباك الـ AI.
    """
    from core.models import Branch, DeliveryArea

    clean_addr = str(customer_address or "").strip()
    if not clean_addr:
        return None, None, {
            "ok": False,
            "is_system_error": False,
            "error": "عنوان التوصيل مطلوب لتنفيذ طلبات التوصيل (Delivery).",
            "ai_speech_response": "يا فندم محتاجة أعرف عنوان التوصيل بالتفصيل عشان أقدر أأكد لحضرتك الطلب وأشوف أقرب فرع.",
            "instruction_for_ai": "اطلب من العميل تزويدك بعنوان التوصيل بالحي والشارع كما في ai_speech_response ولا تقل إن هناك عطلاً بالسيستم."
        }

    norm_addr = _normalize_arabic_text(clean_addr)

    # Candidate branches
    if branch_id is not None:
        candidate_branches = list(Branch.objects.filter(tenant=tenant, id=branch_id, status="active"))
    else:
        candidate_branches = list(Branch.objects.filter(tenant=tenant, status="active"))

    if not candidate_branches:
        return None, None, {
            "ok": False,
            "is_system_error": False,
            "error": "لا توجد فروع نشطة متاحة للمنشأة حالياً.",
            "ai_speech_response": "بعتذر لحضرتك، فروعنا مغلقة حالياً لاستقبال الطلبات، نسعد بخدمتك في أوقات العمل الرسمية.",
            "instruction_for_ai": "أبلغ العميل بلطف أن الفروع مغلقة حالياً."
        }

    # 1. Mandatory polygon rule: only branches with a drawn polygon (>=3 points) are delivery-enabled
    poly_branches = [
        b for b in candidate_branches
        if b.delivery_polygon and isinstance(b.delivery_polygon, list) and len(b.delivery_polygon) >= 3
    ]

    if not poly_branches:
        return None, None, {
            "ok": False,
            "is_system_error": False,
            "status": "no_polygons_configured",
            "error": "خدمة التوصيل غير مفعلة لعدم اكتمال رسم زون التوصيل الجغرافي (المضلع) على الخريطة.",
            "ai_speech_response": "يا فندم خدمة التوصيل غير مفعلة حالياً لفروعنا لعدم اكتمال تحديد النطاق، لكن يشرفنا نجهز لحضرتك الطلب تستلمه بنفسك من الفرع (سفري). تحب نعمل كده؟",
            "suggested_action": "takeaway",
            "instruction_for_ai": "أبلغ العميل بلطف أن خدمة التوصيل غير متاحة واقترح عليه الاستلام من الفرع سفري ولا تقل إن هناك عطلاً بالسيستم."
        }

    candidate_branches = poly_branches

    # Fetch all active named areas for candidate branches
    all_areas = list(DeliveryArea.objects.filter(branch__in=candidate_branches, is_active=True).select_related("branch"))
    matched_area = None

    # 1. Match by explicit delivery_area_id
    if delivery_area_id:
        matched_area = next((a for a in all_areas if a.id == delivery_area_id), None)

    # 2. Match by delivery_area_name
    if not matched_area and delivery_area_name:
        norm_param_area = _normalize_arabic_text(delivery_area_name)
        for a in all_areas:
            norm_a = _normalize_arabic_text(a.name)
            if norm_a == norm_param_area or norm_param_area in norm_a or norm_a in norm_param_area:
                matched_area = a
                break

    # 3. Direct substring containment in address
    if not matched_area:
        for a in all_areas:
            norm_a = _normalize_arabic_text(a.name)
            if norm_a in norm_addr or norm_addr in norm_a:
                matched_area = a
                break

    # 4. Keyword / Significant Token Overlap
    if not matched_area:
        stop_words = {"مدينه", "مدينة", "حي", "الحي", "منطقه", "منطقة", "كمبوند", "شارع", "طريق", "عمارة", "عماره", "شقه", "شقة", "رقم", "مجاورة", "مجاوره"}
        best_score = 0
        best_candidate = None
        addr_tokens = set(w for w in norm_addr.split() if w not in stop_words)
        for a in all_areas:
            area_tokens = set(w for w in _normalize_arabic_text(a.name).split() if w not in stop_words)
            overlap = len(area_tokens & addr_tokens)
            if overlap > best_score:
                best_score = overlap
                best_candidate = a
        if best_candidate and best_score >= 1:
            matched_area = best_candidate

    if matched_area:
        return matched_area.branch, matched_area, None

    # 5. Smart Google Maps & Geofencing Fallback (إذا لم يتطابق مع أي منطقة نصية مسجلة)
    try:
        from core.google_maps_service import resolve_smart_delivery_with_google
        g_branch, g_area_info, g_res = resolve_smart_delivery_with_google(tenant, clean_addr, branch_id=branch_id)
        if g_branch and g_res and g_res.get("ok"):
            class DynamicDeliveryArea:
                def __init__(self, data, branch_obj):
                    self.id = None
                    self.pk = None
                    self.name = data["name"]
                    self.branch = branch_obj
                    self.area_type = data.get("area_type", "zone")
                    self.delivery_fee = Decimal(str(data["delivery_fee"]))
                    self.estimated_time_minutes = int(data.get("estimated_time_minutes", 35))
                    self.notes = data.get("notes", "")

                def get_area_type_display(self):
                    return self.area_type

                def __str__(self):
                    return f"{self.name} - {self.branch.name}"

            dyn_area = DynamicDeliveryArea(g_area_info, g_branch)
            return g_branch, dyn_area, None
        elif g_res and not g_res.get("ok"):
            return None, None, g_res
    except Exception as e:
        logger.warning(f"Error in smart Google Maps delivery resolution: {e}")

    # Outside coverage
    covered_names = list(dict.fromkeys(a.name for a in all_areas))
    covered_str = "، ".join(covered_names[:5])
    return None, None, {
        "ok": False,
        "is_system_error": False,
        "error": f"العنوان المحدد «{clean_addr}» خارج نطاق تغطية التوصيل لفروعنا حالياً. المناطق المغطاة: {covered_str}.",
        "available_areas": covered_names,
        "suggested_action": "takeaway",
        "ai_speech_response": f"يا فندم للأسف عنوان حضرتك خارج نطاق التوصيل المباشر لفروعنا حالياً. من المناطق اللي بنوصلها: {covered_str}. لكن نقدر نجهز لحضرتك الطلب تستلمه بنفسك من أقرب فرع (سفري). تحب نعمل كده؟",
        "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بلطف أن العنوان خارج نطاق التوصيل واقترح عليه الاستلام من الفرع كما في ai_speech_response."
    }



@mcp.tool
def get_digital_menu_link(branch_id: Optional[int] = None, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    استرجاع رابط قائمة الطعام الإلكترونية المباشرة (المنيو الرقمي QR Menu) للمطعم لمشاركته مع العميل أو إرساله عبر الواتساب.
    يُستخدم فوراً عند طلب العميل رابط المنيو أو تصفح القائمة أونلاين عبر الهاتف أو الواتساب.
    
    Args:
        branch_id: (اختياري) معرف الفرع المحدد لفتح منيو هذا الفرع مباشرة إن طلبه العميل.
        access_key: (اختياري) مفتاح الدخول للمنشأة (يُقرأ تلقائياً من الجلسة).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch

    branch = None
    if branch_id is not None:
        branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
        if not branch:
            return {"ok": False, "status": "error", "error": f"الفرع برقم #{branch_id} غير موجود أو غير تابع للمنشأة."}
    elif key_obj.assigned_branch:
        branch = key_obj.assigned_branch

    # Resolve Domain and URL
    if getattr(tenant, "custom_domain", None):
        c_domain = tenant.custom_domain.strip().rstrip("/")
        if not c_domain.startswith("http"):
            c_domain = f"https://{c_domain}"
        if branch:
            menu_url = f"{c_domain}/branch/{branch.id}/"
        else:
            menu_url = f"{c_domain}/"
    else:
        domain = os.environ.get("DOMAIN_NAME", "uggu.space").strip().rstrip("/")
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        if branch:
            menu_url = f"{domain}/m/{tenant.slug}/branch/{branch.id}/"
        else:
            menu_url = f"{domain}/m/{tenant.slug}/"

    b_name = branch.name if branch else "كافة الفروع"
    whatsapp_text = (
        f"أهلاً بك يا فندم! 🍽️\n"
        f"يسعدنا تواصلك مع مطعم {tenant.name}.\n"
        f"تفضل رابط قائمة الطعام الإلكترونية لتصفح الوجبات والأسعار:\n"
        f"{menu_url}\n"
        f"يسعدنا دائماً خدمتك! ✨"
    )

    return {
        "ok": True,
        "status": "success",
        "menu_url": menu_url,
        "restaurant_name": tenant.name,
        "branch_id": branch.id if branch else None,
        "branch_name": b_name,
        "message": f"رابط قائمة الطعام الإلكترونية لمطعم {tenant.name} هو: {menu_url}",
        "suggested_whatsapp_text": whatsapp_text
    }


@mcp.tool
def get_menu(branch_id: Optional[int] = None, category: Optional[str] = None, query: Optional[str] = None, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    استعراض أصناف قائمة الطعام (Menu) المتوفرة في فرع محدد وأسعارها وتصنيفاتها.
    الأسعار بعملة الفرع الرسمية وشاملة للضريبة.
    
    Args:
        branch_id: (اختياري) معرف الفرع المراد جلب المنيو الخاص به. إن لم يحدد يتم جلب الفرع الأنسب تلقائياً.
        category: (اختياري) تصفية حسب القسم مثل 'برجر', 'دجاج', 'مقبلات', 'مشروبات'.
        query: (اختياري) بحث بالاسم أو المكونات (مثال: 'تشيز برجر', 'بطاطس', 'كولا').
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, MenuItem, BranchMenuAvailability

    if branch_id is not None:
        branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
        if not branch:
            return {"ok": False, "error": f"الفرع برقم #{branch_id} غير موجود أو غير تابع للمنشأة."}
    elif key_obj.assigned_branch:
        branch = key_obj.assigned_branch
    else:
        branch = Branch.objects.filter(tenant=tenant, status="active").first()
        if not branch:
            return {"ok": False, "error": "لا توجد أي فروع نشطة متاحة للمنشأة حالياً."}

    if key_obj.assigned_branch and key_obj.assigned_branch_id != branch.id:
        return {"ok": False, "error": f"مفتاح الـ API هذا مخصص لفرع «{key_obj.assigned_branch.name}» فقط."}

    cur_name = branch.get_currency_name_ar()
    cur_sym = branch.get_currency_symbol_ar()

    items_qs = MenuItem.objects.filter(tenant=tenant, available=True)
    if category and category.strip():
        items_qs = items_qs.filter(category__icontains=category.strip())

    if query and query.strip():
        q_str = query.strip()
        items_qs = items_qs.filter(
            models.Q(name__icontains=q_str) |
            models.Q(name_en__icontains=q_str) |
            models.Q(description__icontains=q_str) |
            models.Q(category__icontains=q_str)
        )

    # Check branch availability overrides
    disabled_items = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )

    categories_map = {}
    items_list = []
    for m in items_qs.order_by("category", "name"):
        if m.id in disabled_items:
            continue
        item_dict = {
            "id": m.id,
            "name": m.name,
            "category": m.category,
            "price": float(m.get_price_for_branch(branch)),
            "currency": branch.currency,
            "currency_name": cur_name,
            "currency_symbol": cur_sym,
            "emoji": m.emoji or "🍽️",
        }
        items_list.append(item_dict)
        categories_map.setdefault(m.category, []).append(item_dict)

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "tenant_name": tenant.name,
        "branch_name": branch.name,
        "branch_id": branch.id,
        "currency": branch.currency,
        "currency_name": cur_name,
        "currency_symbol": cur_sym,
        "total_items": len(items_list),
        "categories": list(categories_map.keys()),
        "items": items_list,
    }


@mcp.tool
def lookup_customer(
    phone: Optional[str] = None,
    customer_phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    البحث عن العميل برقم هاتفه لجلب اسمه وعناوينه والكومبوند وتاريخ طلباته السابقة.
    
    Args:
        phone: رقم هاتف العميل (مثال: '01012345678').
        customer_phone: (بديل) رقم هاتف العميل.
        phone_number: (بديل) رقم هاتف العميل.
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Customer, Order

    raw_val = str(phone or customer_phone or phone_number or "").strip()
    if not raw_val:
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة البحث عن العميل (lookup_customer) جاهزة ونشطة بنجاح.",
            "diagnostic": True
        }

    clean_phone = raw_val.replace(" ", "").replace("-", "")
    customer = Customer.objects.filter(tenant=tenant, phone=clean_phone).first()

    from django.utils import timezone
    now = timezone.now()
    one_hour_ago = now - timezone.timedelta(minutes=60)

    if not customer:
        key_obj.record_usage(placed_order=False)
        welcome_speech = f"أهلاً بحضرتك في مطعم «{tenant.name}»! تشرفنا بخدمتك يا فندم.. تحب تطلب إيه اليوم سفري ولا دليفري؟"
        return {
            "ok": True,
            "found": False,
            "is_new_customer": True,
            "phone": clean_phone,
            "message": "عميل جديد غير مسجل مسبقاً. سيتم حفظ بياناته تلقائياً عند تسجيل الأوردر.",
            "ai_speech_response": welcome_speech,
            "instruction_for_ai": "رحب بالعميل الجديد بنص ai_speech_response واستقبل طلبه باحترافية."
        }

    # 1. Proactive Active Order Check: فحص وجود أوردر جارٍ خلال آخر 60 دقيقة
    active_order = Order.objects.filter(
        tenant=tenant,
        customer=customer,
        created_at__gte=one_hour_ago,
        status__in=["new", "preparing", "ready", "out_for_delivery"]
    ).order_by("-created_at").first()

    if active_order:
        elapsed_min = max(1, int((now - active_order.created_at).total_seconds() / 60))
        if active_order.status in ["new", "preparing"]:
            status_desc = "في المطبخ بنجهزه طازج لحضرتك"
        elif active_order.status in ["ready", "out_for_delivery"]:
            status_desc = "خرج مع الطيار وفي الطريق إليك"
        else:
            status_desc = active_order.get_status_display()

        area_est = active_order.delivery_area.estimated_time_minutes if active_order.delivery_area else 35
        rem_min = max(5, area_est - elapsed_min)
        active_speech = (
            f"أهلاً بحضرتك يا فندم! بخصوص طلبك الأخير رقم #{active_order.order_number}، "
            f"هو حالياً {status_desc} ومتوقع يوصلك خلال {rem_min} دقيقة تقريباً.. "
            f"تحب أساعد حضرتك في أي استفسار بخصوصه؟"
        )

        key_obj.record_usage(placed_order=False)
        return {
            "ok": True,
            "found": True,
            "has_active_recent_order": True,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "address": customer.address,
            },
            "active_order": {
                "order_number": active_order.order_number,
                "status": active_order.status,
                "status_display": status_desc,
                "created_minutes_ago": elapsed_min,
                "estimated_remaining_minutes": rem_min,
                "total": float(active_order.total),
                "branch_name": active_order.branch.name if active_order.branch else "",
            },
            "ai_speech_response": active_speech,
            "instruction_for_ai": (
                "العميل لديه أوردر جارٍ قيد التنفيذ؛ اقرأ عليه نص ai_speech_response فوراً لتطمينه على طلبه. "
                "إذا كان يتصل للاستفسار عنه، أجب على تساؤلاته. أما إذا ذكر أنه يرغب في عمل طلب جديد إضافي، فابدأ معه في تلقي الأصناف الجديدة."
            )
        }

    # 2. Saved Address Recognition: فحص آخر عنوان توصيل مسجل للعميل
    last_delivery_order = Order.objects.filter(
        tenant=tenant,
        customer=customer,
        order_type="delivery"
    ).exclude(address="").order_by("-created_at").first()

    saved_addr = last_delivery_order.address if last_delivery_order else customer.address
    saved_branch = last_delivery_order.branch if last_delivery_order else None
    saved_area = last_delivery_order.delivery_area if last_delivery_order else None

    # Fetch recent orders for customer history
    recent_orders = Order.objects.filter(tenant=tenant, customer=customer).order_by("-created_at")[:3]
    orders_data = [
        {
            "order_number": o.order_number,
            "total": float(o.total),
            "status": o.get_status_display(),
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
            "items_count": o.items.count(),
        }
        for o in recent_orders
    ]
    order_count = customer.orders.count()
    total_spent = float(customer.orders.aggregate(models.Sum("total"))["total__sum"] or 0)

    if saved_addr:
        greeting_speech = (
            f"أهلاً بيك يا {customer.name}! نورتنا يا فندم.. "
            f"تحب نوصل لحضرتك على نفس عنوانك السابق ({saved_addr}) ولا حابب تطلب على عنوان جديد؟"
        )
        instruction = (
            f"العميل مسجل مسبقاً ولديه عنوان محفوظ؛ رحب به باسمه واقرأ عليه نص ai_speech_response واعرض عليه التوصيل لنفس العنوان ({saved_addr}). "
            f"إذا وافق العميل (قال نعم، أو تمام، أو نفس العنوان)، اعتمد هذا العنوان والفرع فوراً دون الحاجة لسؤاله عن الحي أو المنطقة أو رسم الخريطة مجدداً."
        )
    else:
        greeting_speech = f"أهلاً بيك يا {customer.name}! نورتنا في مطعم «{tenant.name}»، تشرفنا بخدمتك يا فندم.. تحب تطلب إيه اليوم؟"
        instruction = "رحب بالعميل باسمه بنص ai_speech_response وتلقى طلبه."

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "found": True,
        "has_active_recent_order": False,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "address": saved_addr or customer.address,
            "total_orders": order_count,
            "total_spent": total_spent,
            "created_at": customer.created_at.strftime("%Y-%m-%d"),
        },
        "saved_delivery_profile": {
            "saved_address": saved_addr,
            "saved_branch_id": saved_branch.id if saved_branch else None,
            "saved_branch_name": saved_branch.name if saved_branch else None,
            "saved_delivery_area_id": saved_area.id if saved_area else None,
            "saved_delivery_area_name": saved_area.name if saved_area else None,
        } if saved_addr else None,
        "recent_orders": orders_data,
        "ai_speech_response": greeting_speech,
        "instruction_for_ai": instruction,
    }


@mcp.tool
def check_delivery_coverage(
    branch_id: Optional[int] = None,
    area_name: Optional[str] = "",
    delivery_area_name: Optional[str] = None,
    customer_address: Optional[str] = None,
    address: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    فحص هل منطقة العميل أو الكومبوند يقع ضمن مناطق توصيل المطعم، وحساب رسوم ووقت التوصيل وتحديد الفرع الأنسب تلقائياً.
    إلزامي الاستدعاء عند رغبة العميل في خدمة التوصيل (Delivery) وقبل إنشاء الطلب.
    
    Args:
        branch_id: (اختياري) معرف الفرع (يتم فحص وتحديد الفرع الأنسب تلقائياً لجميع الفروع إن لم يُحدد).
        area_name: اسم المنطقة أو الحي أو الكومبوند (مثال: 'مدينة الشروق', 'كمبوند النرجس', 'الياسمين').
        delivery_area_name: (بديل) اسم المنطقة أو الحي.
        customer_address: (بديل) عنوان أو منطقة العميل.
        address: (بديل) عنوان العميل.
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, DeliveryArea

    query = str(area_name or delivery_area_name or customer_address or address or "").strip()

    # Diagnostic / Health check call from platform admin
    if not query:
        branch = Branch.objects.filter(tenant=tenant, status="active").first()
        all_areas = list(DeliveryArea.objects.filter(branch__tenant=tenant, is_active=True).values_list("name", flat=True))
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة فحص التغطية (check_delivery_coverage) جاهزة ونشطة بنجاح.",
            "branch_name": branch.name if branch else "الفرع الرئيسي",
            "available_areas": list(set(all_areas)),
            "diagnostic": True,
        }

    effective_branch_id = branch_id if branch_id is not None else (key_obj.assigned_branch_id if key_obj.assigned_branch else None)
    matched_branch, matched_area, err = _resolve_delivery_coverage_and_branch(
        tenant,
        customer_address=query,
        branch_id=effective_branch_id,
        delivery_area_name=query,
    )

    key_obj.record_usage(placed_order=False)
    if err:
        err["covered"] = False
        return err

    cur_name = matched_branch.get_currency_name_ar()
    cur_sym = matched_branch.get_currency_symbol_ar()
    dist_val = getattr(matched_area, "distance_km", 0.0)
    min_order_req = matched_branch.get_min_order_for_distance(dist_val)
    return {
        "ok": True,
        "covered": True,
        "branch_id": matched_branch.id,
        "branch_name": matched_branch.name,
        "currency": matched_branch.currency,
        "currency_name": cur_name,
        "currency_symbol": cur_sym,
        "minimum_order_amount": float(min_order_req),
        "matched_area": {
            "id": matched_area.id,
            "name": matched_area.name,
            "area_type": matched_area.get_area_type_display(),
            "delivery_fee": float(matched_area.delivery_fee),
            "estimated_time_minutes": matched_area.estimated_time_minutes,
            "distance_km": float(dist_val) if dist_val else None,
            "minimum_order_amount": float(min_order_req),
            "notes": matched_area.notes or "",
        },
        "ai_speech_response": f"تمام يا فندم، منطقة «{matched_area.name}» مغطاة من خلال {matched_branch.name}، ورسوم التوصيل {matched_area.delivery_fee:.0f} {cur_name}، ووقت التوصيل التقديري حوالي {matched_area.estimated_time_minutes} دقيقة (والحد الأدنى للطلب {min_order_req:.0f} {cur_name}).",
        "instruction_for_ai": f"أبلغ العميل بأن المنطقة «{matched_area.name}» مغطاة ورسوم التوصيل هي {matched_area.delivery_fee:.0f} {cur_name}، ووقت التوصيل التقديري {matched_area.estimated_time_minutes} دقيقة كما في ai_speech_response."
    }


@mcp.tool
def preview_order(
    items: Optional[List[OrderItemInput]] = None,
    customer_address: Optional[str] = "",
    delivery_area_name: Optional[str] = None,
    delivery_area_id: Optional[int] = None,
    order_type: str = "delivery",
    branch_id: Optional[int] = None,
    branch_name: Optional[str] = None,
    branch: Optional[Any] = None,
    customer_phone: Optional[str] = None,
    phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    customer_name: Optional[str] = None,
    name: Optional[str] = None,
    address: Optional[str] = None,
    notes: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    معاينة وحساب الفاتورة المبدئية للطلب بدقة (الأسعار، الضريبة 15%، ورسوم التوصيل) دون إنشاء أوردر في النظام.
    تُستخدم لحساب التكلفة الإجمالية وإبلاغ العميل بها والحصول على موافقته الصريحة قبل ضرب الطلب نهائياً.

    Args:
        items: قائمة الأصناف المطلوبة مع الكميات (مثال: [{'name': 'شاي كرك', 'quantity': 2}]).
        customer_address: (مطلوب لطلبات التوصيل) عنوان العميل لحساب رسوم التوصيل الصحيحة وتحديد الفرع الأنسب.
        delivery_area_name: (اختياري) اسم المنطقة أو الحي لتطبيق رسوم التوصيل بدقة.
        delivery_area_id: (اختياري) معرف منطقة التوصيل.
        order_type: نوع الطلب ('delivery' للتوصيل أو 'takeaway' للاستلام من الفرع).
        branch_id: (اختياري) معرف الفرع (يُحدد تلقائياً بناءً على عنوان التوصيل إن لم يمرر).
        customer_phone: (اختياري) رقم هاتف العميل.
        phone: (بديل) رقم هاتف العميل.
        phone_number: (بديل) رقم هاتف العميل.
        customer_name: (اختياري) اسم العميل.
        name: (بديل) اسم العميل.
        address: (بديل) عنوان العميل.
        notes: (اختياري) ملاحظات إضافية.
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, MenuItem, BranchMenuAvailability

    if not customer_address and address:
        customer_address = address

    # Diagnostic / Health check call from platform admin
    if not items and not customer_address and not delivery_area_name:
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة معاينة الفاتورة وحساب الإجمالي (preview_order) جاهزة ونشطة بنجاح.",
            "diagnostic": True
        }

    # 1. Parse & normalize items if stringified JSON, natural string, or Pydantic models
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            natural = _parse_natural_order_text(items, tenant)
            if natural:
                items = natural
            else:
                return {
                    "ok": False,
                    "error": "صيغة قائمة الأصناف غير صالحة، يرجى تزويدنا بقائمة أصناف صحيحة.",
                    "ai_speech_response": "يا فندم ما قدرتش أحدد الأصناف المطلوبة، ممكن توضح لي طلبت إيه بالظبط؟",
                    "instruction_for_ai": "اطلب من العميل توضيح الأصناف والكميات المطلوبة."
                }
    elif isinstance(items, dict):
        items = [items]

    cleaned_items = []
    for it in (items or []):
        if hasattr(it, "model_dump"):
            cleaned_items.append(it.model_dump())
        elif hasattr(it, "dict"):
            cleaned_items.append(it.dict())
        elif isinstance(it, dict):
            cleaned_items.append(it)
        elif isinstance(it, str):
            try:
                cleaned_items.append(json.loads(it))
            except Exception:
                nat = _parse_natural_order_text(it, tenant)
                if nat:
                    cleaned_items.extend(nat)
                else:
                    cleaned_items.append({"name": it, "quantity": 1})
        else:
            cleaned_items.append({"name": str(it), "quantity": 1})
    items = cleaned_items

    if not items:
        return {
            "ok": False,
            "error": "يجب تزويدنا بقائمة أصناف صالحة في المعامل items لحساب الفاتورة.",
            "ai_speech_response": "يا فندم محتاجة أعرف الأصناف اللي تحب تطلبها عشان أحسب لحضرتك الفاتورة.",
            "instruction_for_ai": "اسأل العميل عن الأصناف التي يود طلبها."
        }

    # 2. Order Type & Delivery Coverage Calculation
    order_type = str(order_type or "delivery").strip().lower()
    if order_type not in ["delivery", "takeaway", "dine_in"]:
        order_type = "delivery"

    delivery_fee = Decimal("0.00")
    matched_area = None
    branch = None

    effective_branch_id = branch_id if branch_id is not None else (key_obj.assigned_branch_id if key_obj.assigned_branch else None)

    if order_type == "delivery":
        branch, matched_area, err = _resolve_delivery_coverage_and_branch(
            tenant,
            customer_address=customer_address or "",
            branch_id=effective_branch_id,
            delivery_area_id=delivery_area_id,
            delivery_area_name=delivery_area_name,
        )
        if err:
            return err
        delivery_fee = matched_area.delivery_fee
        addr_valid, addr_err = _validate_delivery_address_completeness(
            customer_address or "",
            matched_area_name=matched_area.name if matched_area else (delivery_area_name or "")
        )
    else:
        # Takeaway or Dine-in
        active_branches = list(Branch.objects.filter(tenant=tenant, status="active"))
        if not active_branches:
            return {
                "ok": False,
                "is_system_error": False,
                "error": "لا توجد فروع نشطة متاحة للمنشأة حالياً.",
                "ai_speech_response": "بعتذر لحضرتك، فروعنا مغلقة حالياً لاستقبال الطلبات.",
                "instruction_for_ai": "أبلغ العميل بأن فروعنا مغلقة حالياً."
            }

        candidate_bname = str(branch_name or branch or "").strip()

        if effective_branch_id is not None:
            branch = next((b for b in active_branches if b.id == effective_branch_id), None)
            if not branch and 1 <= effective_branch_id <= len(active_branches):
                branch = active_branches[effective_branch_id - 1]

        if not branch and candidate_bname:
            norm_b = _normalize_arabic_text(candidate_bname)
            for b in active_branches:
                norm_curr = _normalize_arabic_text(b.name)
                norm_city = _normalize_arabic_text(b.city)
                if norm_b in norm_curr or norm_curr in norm_b or (norm_city and (norm_b in norm_city or norm_city in norm_b)):
                    branch = b
                    break

        if not branch:
            if len(active_branches) > 1:
                branch_names = [b.name for b in active_branches]
                b_names_str = " أو ".join([f"«{b.name}»" for b in active_branches[:4]])
                return {
                    "ok": False,
                    "is_system_error": False,
                    "status": "branch_selection_required",
                    "error": f"يرجى تحديد فرع الاستلام لحساب الأسعار بدقة: ({b_names_str}).",
                    "available_branches": branch_names,
                    "ai_speech_response": f"تحب حضرتك تستلم من أي فرع لحساب الإجمالي بدقة؟ متاح عندنا: {b_names_str}.",
                    "instruction_for_ai": "اسأل العميل بلطف عن الفرع الذي يود الاستلام منه كما في ai_speech_response."
                }
            else:
                branch = active_branches[0]

    cur_name = branch.get_currency_name_ar()
    cur_sym = branch.get_currency_symbol_ar()

    # 3. Item validation & Server-side calculation
    disabled_item_ids = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )

    subtotal = Decimal("0.00")
    prepared_items = []

    for idx, item_spec in enumerate(items, start=1):
        menu_item, match_err = _find_menu_item(tenant, branch, item_spec, disabled_item_ids)
        if match_err:
            return {
                "ok": False,
                "error": match_err,
                "ai_speech_response": f"يا فندم بخصوص طلبك، {match_err}",
                "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بما ورد في ai_speech_response واقترح عليه بديلاً متوفراً."
            }

        if isinstance(item_spec, dict):
            try:
                qty = int(item_spec.get("quantity") or item_spec.get("qty") or 1)
            except (ValueError, TypeError):
                qty = 1
        else:
            qty = 1

        if qty <= 0:
            continue

        item_price = menu_item.get_price_for_branch(branch)
        line_total = item_price * qty
        subtotal += line_total
        prepared_items.append({
            "name": menu_item.name,
            "quantity": qty,
            "unit_price": float(item_price),
            "line_total": float(line_total),
        })

    if not prepared_items:
        return {
            "ok": False,
            "error": "لم يتم العثور على أي أصناف صالحة لحساب الفاتورة.",
            "ai_speech_response": "يا فندم محتاجة تحديد الأصناف والكميات بوضوح لحساب الإجمالي.",
            "instruction_for_ai": "اطلب من العميل توضيح طلبه."
        }

    grand_total = subtotal + delivery_fee
    items_speech = " و ".join([f"{it['quantity']} {it['name']}" for it in prepared_items])

    # Minimum order check for delivery orders
    if order_type == "delivery":
        dist_val = getattr(matched_area, "distance_km", 0.0)
        min_order_req = branch.get_min_order_for_distance(dist_val)
        if subtotal < min_order_req:
            diff = min_order_req - subtotal
            min_speech = (
                f"طلبك ({items_speech}) بمجموع أصناف {subtotal:.0f} {cur_name}، "
                f"ولكن الحد الأدنى لطلب التوصيل لمنطقة «{matched_area.name if matched_area else 'حضرتك'}» هو {min_order_req:.0f} {cur_name} "
                f"(باقي {diff:.0f} {cur_name} لتكملة الحد الأدنى).. تحب نضيف لحضرتك مشروب أو صنف إضافي لتكملة الطلب؟"
            )
            key_obj.record_usage(placed_order=False)
            return {
                "ok": True,
                "below_minimum_order": True,
                "branch_name": branch.name,
                "currency": branch.currency,
                "currency_name": cur_name,
                "currency_symbol": cur_sym,
                "order_type": "توصيل",
                "items": prepared_items,
                "subtotal": float(subtotal),
                "minimum_order_required": float(min_order_req),
                "amount_needed": float(diff),
                "delivery_fee": float(delivery_fee),
                "delivery_area": matched_area.name if matched_area else "غير محدد",
                "estimated_delivery_time": f"{matched_area.estimated_time_minutes} دقيقة" if matched_area else "30-45 دقيقة",
                "total": float(grand_total),
                "ai_speech_response": min_speech,
                "ai_speech_summary": min_speech,
                "instruction_for_ai": (
                    f"أبلغ العميل بلطف أن حساب الأصناف ({subtotal:.0f} {cur_name}) أقل من الحد الأدنى المطلوب للتوصيل لهذه المنطقة "
                    f"({min_order_req:.0f} {cur_name})، واقترح عليه إضافة أصناف إضافية بقيمة {diff:.0f} {cur_name} كما في ai_speech_response."
                )
            }

    if order_type == "delivery":
        speech = f"إجمالي طلبك ({items_speech}) بقيمة {subtotal:.0f} {cur_name}، ورسوم التوصيل {delivery_fee:.0f} {cur_name}، الإجمالي النهائي {grand_total:.0f} {cur_name}. تحب أسجل لحضرتك الطلب دلوقتي؟"
    else:
        speech = f"إجمالي طلبك سفري ({items_speech}) بقيمة {subtotal:.0f} {cur_name}، وتقدر تستلمه من فرع {branch.name}. تحب أسجل لحضرتك الطلب دلوقتي؟"

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "below_minimum_order": False,
        "branch_name": branch.name,
        "currency": branch.currency,
        "currency_name": cur_name,
        "currency_symbol": cur_sym,
        "order_type": "توصيل" if order_type == "delivery" else "استلام من الفرع",
        "items": prepared_items,
        "subtotal": float(subtotal),
        "delivery_fee": float(delivery_fee),
        "delivery_area": matched_area.name if matched_area else ("سفري" if order_type == "takeaway" else "غير محدد"),
        "estimated_delivery_time": f"{matched_area.estimated_time_minutes} دقيقة" if matched_area else "30-45 دقيقة",
        "address_status": "complete" if (order_type != "delivery" or addr_valid) else "details_required",
        "address_notice": (addr_err.get("ai_speech_response") if (order_type == "delivery" and not addr_valid and addr_err) else None),
        "total": float(grand_total),
        "ai_speech_response": speech,
        "ai_speech_summary": speech,
        "instruction_for_ai": "أخبر العميل بالإجمالي كما هو موضح في ai_speech_response واطلب موافقته الصريحة قبل تسجيل الأوردر نهائياً."
    }


@mcp.tool
def create_callcenter_order(
    branch_id: Optional[int] = None,
    branch_name: Optional[str] = None,
    branch: Optional[Any] = None,
    customer_phone: Optional[str] = None,
    phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    customer_name: Optional[str] = "",
    name: Optional[str] = None,
    customer_address: Optional[str] = "",
    address: Optional[str] = None,
    items: Optional[List[OrderItemInput]] = None,
    order_type: str = "delivery",
    delivery_area_id: Optional[int] = None,
    delivery_area_name: Optional[str] = None,
    notes: str = "",
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إنشاء (ضرب) أوردر جديد من الكول سنتر مع التعرف التلقائي على العميل برقم هاتفه،
    ومطابقة الأصناف الذكية بالمرادفات واللهجات، والتوجيه التلقائي للفرع الذي يغطي عنوان العميل.
    
    Args:
        branch_id: (اختياري) معرف الفرع المنفذ للطلب. إن لم يحدد يتم التوجيه التلقائي للفرع الأنسب.
        customer_phone: رقم هاتف العميل (إلزامي للتعرف على العميل وتتبع الطلب).
        phone: (بديل) رقم هاتف العميل.
        phone_number: (بديل) رقم هاتف العميل.
        customer_name: (اختياري) اسم العميل (يُحدث تلقائياً ويُسترجع من سجله السابق إن وجد).
        name: (بديل) اسم العميل.
        customer_address: عنوان التوصيل بالتفصيل (الحي، الشارع، العمارة، الشقة).
        address: (بديل) عنوان التوصيل.
        items: قائمة الأصناف المطلوبة مع الكميات (مثال: [{'name': 'شاي كرك', 'quantity': 1}]).
        order_type: نوع الطلب ('delivery' أو 'takeaway' أو 'dine_in'). الافتراضي هو 'delivery'.
        delivery_area_id: (اختياري) معرف منطقة التوصيل لتطبيق رسومها المحددة بدقة.
        delivery_area_name: (اختياري) اسم منطقة أو حي التوصيل (مثل: 'مدينة الشروق', 'العليا').
        notes: أي ملاحظات خاصة بالطلب (مثل: بدون شطة، زيادة صوص).
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, Customer, MenuItem, Order, OrderItem, DeliveryArea, BranchMenuAvailability

    customer_phone = str(customer_phone or phone or phone_number or "").strip()
    if not customer_address and address:
        customer_address = address
    if not customer_name and name:
        customer_name = name

    # Diagnostic / Health check call from platform admin
    if not customer_phone and not items and not customer_address:
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة إنشاء أوردرات الكول سنتر (create_callcenter_order) جاهزة ونشطة بنجاح.",
            "diagnostic": True
        }

    # 1. Parse & normalize items if stringified JSON, natural string, or Pydantic models
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            natural = _parse_natural_order_text(items, tenant)
            if natural:
                items = natural
            else:
                return {
                    "ok": False,
                    "error": "صيغة قائمة الأصناف غير صالحة.",
                    "ai_speech_response": "يا فندم ما قدرتش أسجل الأصناف المطلوبة، ممكن تعيدها لي تاني؟",
                    "instruction_for_ai": "اطلب من العميل إعادة ذكر الأصناف والكميات المطلوبة."
                }
    elif isinstance(items, dict):
        items = [items]

    cleaned_items = []
    for it in (items or []):
        if hasattr(it, "model_dump"):
            cleaned_items.append(it.model_dump())
        elif hasattr(it, "dict"):
            cleaned_items.append(it.dict())
        elif isinstance(it, dict):
            cleaned_items.append(it)
        elif isinstance(it, str):
            try:
                cleaned_items.append(json.loads(it))
            except Exception:
                nat = _parse_natural_order_text(it, tenant)
                if nat:
                    cleaned_items.extend(nat)
                else:
                    cleaned_items.append({"name": it, "quantity": 1})
        else:
            cleaned_items.append({"name": str(it), "quantity": 1})
    items = cleaned_items

    if not items:
        return {
            "ok": False,
            "is_system_error": False,
            "error": "قائمة الأصناف (items) مطلوبة لتنفيذ الطلب.",
            "ai_speech_response": "يا فندم محتاجة أعرف الأصناف والكميات المطلوبة عشان أسجل الأوردر.",
            "instruction_for_ai": "اطلب من العميل تحديد الأصناف التي يود طلبها ولا تقل إن هناك عطلاً بالسيستم."
        }

    # 2. Resilient Phone Validation & Customer Recognition
    clean_phone = _clean_phone(customer_phone)
    if not clean_phone or len(clean_phone) < 7 or customer_phone == "web_dashboard" or "dashboard" in str(customer_phone).lower():
        clean_phone = "0559998877"

    phone_suffix = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone
    customer = Customer.objects.filter(tenant=tenant).filter(
        models.Q(phone=clean_phone) | models.Q(phone__endswith=phone_suffix)
    ).first()

    clean_name = str(customer_name or "").strip()
    clean_addr = str(customer_address or "").strip()
    customer_recognized = False

    if customer:
        customer_recognized = True
        if not clean_name:
            clean_name = customer.name
        elif clean_name != customer.name and not clean_name.startswith("عميل هاتف"):
            customer.name = clean_name

        if not clean_addr:
            clean_addr = customer.address
        elif clean_addr != customer.address:
            customer.address = clean_addr

        customer.save()
    else:
        clean_name = clean_name or f"عميل ({clean_phone[-4:]})"
        try:
            customer = Customer.objects.create(
                tenant=tenant,
                phone=clean_phone,
                name=clean_name,
                address=clean_addr,
            )
        except IntegrityError:
            customer = Customer.objects.filter(tenant=tenant).filter(
                models.Q(phone=clean_phone) | models.Q(phone__endswith=phone_suffix)
            ).first()

    # 3. Order Type & Intelligent Delivery / Branch Resolution
    order_type = str(order_type or "delivery").strip().lower()
    if order_type not in ["delivery", "takeaway", "dine_in"]:
        order_type = "delivery"

    delivery_fee = Decimal("0.00")
    matched_area = None
    branch = None

    effective_branch_id = branch_id if branch_id is not None else (key_obj.assigned_branch_id if key_obj.assigned_branch else None)

    if order_type == "delivery":
        branch, matched_area, err = _resolve_delivery_coverage_and_branch(
            tenant,
            customer_address=clean_addr,
            branch_id=effective_branch_id,
            delivery_area_id=delivery_area_id,
            delivery_area_name=delivery_area_name,
        )
        if err:
            return err
        delivery_fee = matched_area.delivery_fee

        # 3.1 Strict Adaptive Delivery Address Completeness Validation
        addr_valid, addr_err = _validate_delivery_address_completeness(
            clean_addr,
            matched_area_name=matched_area.name if matched_area else (delivery_area_name or "")
        )
        if not addr_valid:
            return addr_err
    else:
        # Takeaway or Dine-in
        active_branches = list(Branch.objects.filter(tenant=tenant, status="active"))
        if not active_branches:
            return {
                "ok": False,
                "is_system_error": False,
                "error": "لا توجد فروع نشطة متاحة للمنشأة حالياً.",
                "ai_speech_response": "بعتذر لحضرتك، فروعنا مغلقة حالياً لاستقبال الطلبات.",
                "instruction_for_ai": "أبلغ العميل بأن الفروع مغلقة حالياً."
            }

        candidate_bname = str(branch_name or branch or "").strip()

        if effective_branch_id is not None:
            branch = next((b for b in active_branches if b.id == effective_branch_id), None)
            if not branch and 1 <= effective_branch_id <= len(active_branches):
                branch = active_branches[effective_branch_id - 1]

        if not branch and candidate_bname:
            norm_b = _normalize_arabic_text(candidate_bname)
            for b in active_branches:
                norm_curr = _normalize_arabic_text(b.name)
                norm_city = _normalize_arabic_text(b.city)
                if norm_b in norm_curr or norm_curr in norm_b or (norm_city and (norm_b in norm_city or norm_city in norm_b)):
                    branch = b
                    break

        if not branch:
            if len(active_branches) > 1:
                branch_names = [b.name for b in active_branches]
                b_names_str = " أو ".join([f"«{b.name}»" for b in active_branches[:4]])
                return {
                    "ok": False,
                    "is_system_error": False,
                    "status": "branch_selection_required",
                    "error": f"يرجى تحديد فرع الاستلام من بين فروع المنشأة المتاحة: ({b_names_str}).",
                    "available_branches": branch_names,
                    "ai_speech_response": f"تحب حضرتك تستلم الطلب من أي فرع من فروعنا؟ متاح عندنا: {b_names_str}.",
                    "instruction_for_ai": "اسأل العميل بلطف عن الفرع الذي يود الاستلام منه من بين الفروع المتاحة كما في ai_speech_response ولا تسجل الطلب إلا بعد تحديد الفرع وتأكيده مع العميل."
                }
            else:
                branch = active_branches[0]

    # 4. Strict Menu Items Resolver & Total Calculation
    disabled_item_ids = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )

    subtotal = Decimal("0.00")
    order_items_prepared = []

    for idx, item_spec in enumerate(items, start=1):
        menu_item, match_err = _find_menu_item(tenant, branch, item_spec, disabled_item_ids)
        if match_err:
            return {
                "ok": False,
                "is_system_error": False,
                "error": match_err,
                "ai_speech_response": f"يا فندم بخصوص طلبك، {match_err}",
                "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بما جاء في ai_speech_response واقترح عليه بديلاً متوفراً."
            }

        if isinstance(item_spec, dict):
            try:
                qty = int(item_spec.get("quantity") or item_spec.get("qty") or 1)
            except (ValueError, TypeError):
                qty = 1
            item_notes = str(item_spec.get("notes") or item_spec.get("special_instructions") or "").strip()
        else:
            qty = 1
            item_notes = ""

        if qty <= 0:
            continue

        item_price = menu_item.get_price_for_branch(branch)
        line_total = item_price * qty
        subtotal += line_total

        order_items_prepared.append({
            "menu_item": menu_item,
            "quantity": qty,
            "price": item_price,
            "total": line_total,
            "notes": item_notes,
        })

    if not order_items_prepared:
        return {
            "ok": False,
            "error": "لم يتم العثور على أي أصناف صالحة أو كميات مقبولة في الطلب.",
            "ai_speech_response": "يا فندم محتاجة تحديد الأصناف بوضوح لتسجيل الأوردر.",
            "instruction_for_ai": "اطلب من العميل توضيح طلبه."
        }

    # Tax (15% VAT included standard) & Grand Total
    tax = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    total = subtotal + delivery_fee

    cur_name = branch.get_currency_name_ar()
    cur_sym = branch.get_currency_symbol_ar()

    # Minimum order check for delivery orders
    if order_type == "delivery":
        dist_val = getattr(matched_area, "distance_km", 0.0)
        min_order_req = branch.get_min_order_for_distance(dist_val)
        if subtotal < min_order_req:
            diff = min_order_req - subtotal
            items_speech = " و ".join([f"{oi['quantity']} {oi['menu_item'].name}" for oi in order_items_prepared])
            return {
                "ok": False,
                "is_system_error": False,
                "below_minimum_order": True,
                "subtotal": float(subtotal),
                "minimum_order_required": float(min_order_req),
                "amount_needed": float(diff),
                "delivery_fee": float(delivery_fee),
                "branch_name": branch.name,
                "currency": branch.currency,
                "currency_name": cur_name,
                "currency_symbol": cur_sym,
                "error": f"حساب أصناف الطلب {subtotal:.0f} {cur_name} وهو أقل من الحد الأدنى لطلب التوصيل ({min_order_req:.0f} {cur_name}).",
                "ai_speech_response": f"يا فندم الحد الأدنى لطلب التوصيل لمنطقتك هو {min_order_req:.0f} {cur_name}، وحساب أصنافك حالياً {subtotal:.0f} {cur_name} (باقي {diff:.0f} {cur_name}). تحب نضيف لحضرتك مشروب أو صنف إضافي لنصل للحد الأدنى؟",
                "instruction_for_ai": f"لا تسجل الأوردر الآن! أبلغ العميل بلطف أن طلبه أقل من الحد الأدنى للتوصيل ({min_order_req:.0f} {cur_name}) واطلب منه إضافة أصناف بقيمة {diff:.0f} {cur_name} لتكملة الطلب كما في ai_speech_response."
            }

    # Unique Order Number with Tenant Scoped Prefix
    prefix = (tenant.slug[:3] if tenant and tenant.slug else "CC").upper()
    full_notes = f"[AI Call Center: {key_obj.name}] {notes}".strip()

    # 5. Atomic Order Creation with Concurrency Retry Loop
    with transaction.atomic():
        order = None
        for attempt in range(5):
            last_order = Order.objects.filter(tenant=tenant).order_by("-id").first()
            next_seq = (last_order.id + 1 + attempt) if last_order else (1 + attempt)
            candidate_num = f"{prefix}-{1000 + next_seq}"
            while Order.objects.filter(tenant=tenant, order_number=candidate_num).exists():
                next_seq += 1
                candidate_num = f"{prefix}-{1000 + next_seq}"
            order_number = candidate_num

            try:
                sid = transaction.savepoint()
                db_delivery_area = matched_area if (matched_area and hasattr(matched_area, "pk") and matched_area.pk) else None
                order_notes = full_notes
                if matched_area and getattr(matched_area, "notes", None) and str(matched_area.notes) not in order_notes:
                    order_notes = f"{order_notes} | {matched_area.notes}".strip(" |")

                order = Order.objects.create(
                    tenant=tenant,
                    branch=branch,
                    order_number=order_number,
                    order_type=order_type,
                    channel="call_center",
                    customer=customer,
                    customer_name=customer.name if customer else "عميل هاتف",
                    customer_phone=customer.phone if customer else clean_phone,
                    address=clean_addr,
                    delivery_area=db_delivery_area,
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    discount=Decimal("0.00"),
                    total=total,
                    paid=False,
                    cashier=f"AI: {key_obj.name}",
                    notes=order_notes,
                    status="new",
                )
                transaction.savepoint_commit(sid)
                break
            except IntegrityError:
                transaction.savepoint_rollback(sid)
                continue

        if not order:
            return {"error": "فشل إنشاء الطلب بسبب تضارب أرقام الطلبات المتزامنة."}

        for oi in order_items_prepared:
            OrderItem.objects.create(
                order=order,
                menu_item=oi["menu_item"],
                name=oi["menu_item"].name,
                price=oi["price"],
                qty=oi["quantity"],
            )

        from core.models import log_audit_event
        cust_label = customer.name if customer else "عميل"
        log_audit_event(
            tenant=tenant,
            user=None,
            action="order_created",
            target_model="Order",
            target_id=order.id,
            description=f"إنشاء الطلب #{order.order_number} تلقائياً عبر كول سنتر الذكاء الاصطناعي ({key_obj.name}) للعميل {cust_label} بقيمة {order.total} {branch.get_currency_symbol_ar()}",
            ip_address=None,
        )

    # Real-time SSE push to kitchen display
    try:
        from core.kitchen_events import notify_kitchen_order_event
        notify_kitchen_order_event(order, "new_order")
    except Exception as e:
        logger.warning(f"Failed to notify kitchen of AI order: {e}")

    key_obj.record_usage(placed_order=True)

    cur_name = branch.get_currency_name_ar()
    cur_sym = branch.get_currency_symbol_ar()

    est_time = f"{matched_area.estimated_time_minutes} دقيقة" if (matched_area and matched_area.estimated_time_minutes) else "30 إلى 45 دقيقة"
    items_speech = " و ".join([f"{oi['quantity']} {oi['menu_item'].name}" for oi in order_items_prepared])
    if order_type == "delivery":
        speech = f"تم تسجيل طلبك بنجاح برقم {order.order_number}! الطلب: ({items_speech}) بإجمالي {total:.0f} {cur_name}، ويوصل لحضرتك خلال {est_time} تقريباً، وبعت لحضرتك تفاصيل الفاتورة ورابط المتابعة على الواتساب دلوقتي."
    else:
        speech = f"تم تسجيل طلبك بنجاح برقم {order.order_number}! الطلب: ({items_speech}) بإجمالي {total:.0f} {cur_name}، وتقدر تستلمه من فرع {branch.name} خلال {est_time}، وبعت لحضرتك تفاصيل الفاتورة على الواتساب دلوقتي."

    # 6. Automatic Instant WhatsApp Confirmation (إذا كان هاتف العميل حقيقياً)
    try:
        from core import partner_service as ps
        wa_cid = getattr(tenant, "voice_client_id", None) or ps.get_client_id_for_tenant(tenant)
        if wa_cid and clean_phone and clean_phone != "web_dashboard" and "dashboard" not in str(clean_phone).lower():
            import threading
            items_lines = "\n".join([f"• {oi['quantity']} × {oi['menu_item'].name} ({oi['total']:.0f} {cur_sym})" for oi in order_items_prepared])

            domain = os.environ.get("DOMAIN_NAME", "uggu.space").strip().rstrip("/")
            if not domain.startswith("http"):
                domain = f"https://{domain}"
            menu_track_url = f"{domain}/m/{tenant.slug}/?order={order.order_number}"

            wa_text = (
                f"🧾 *تأكيد طلبك من مطعم {tenant.name}*\n"
                f"📍 *الفرع:* {branch.name}\n"
                f"🔢 *رقم الطلب:* #{order.order_number}\n\n"
                f"🍔 *الأصناف المطلوبة:*\n{items_lines}\n\n"
                f"💰 *المجموع:* {subtotal:.0f} {cur_sym}\n"
                f"🛵 *رسوم التوصيل:* {delivery_fee:.0f} {cur_sym}\n"
                f"💵 *الإجمالي المطلوب:* {total:.0f} {cur_sym}\n\n"
                f"🏠 *عنوان التوصيل:* {clean_addr or 'استلام من الفرع'}\n"
                f"⏱️ *وقت التوصيل المتوقع:* {est_time}\n\n"
                f"🔗 *متابعة وتتبع حالة الطلب:*\n{menu_track_url}\n\n"
                f"⭐ *رأيك يهمنا جداً!*\n"
                f"كيف كانت تجربتك في المكالمة مع مساعدنا الصوتي الذكي؟ شاركنا تقييمك من 1 إلى 5 نجوم (أو أي ملاحظة) بالرد على هذه الرسالة.\n\n"
                f"شكراً لطلبك! نسعد دائماً بخدمتكم."
            )
            def _send_wa_async():
                try:
                    ps.send_whatsapp_message(wa_cid, clean_phone, wa_text)
                except Exception as ex:
                    import logging
                    logging.getLogger(__name__).warning(f"Error sending WhatsApp message: {ex}")
            wa_thread = threading.Thread(target=_send_wa_async)
            wa_thread.start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Error initiating auto WhatsApp confirmation: {e}")

    return {
        "ok": True,
        "message": f"تم إنشاء الأوردر بنجاح برقم {order.order_number}",
        "order_number": order.order_number,
        "currency": branch.currency,
        "currency_name": cur_name,
        "currency_symbol": cur_sym,
        "customer_recognized": customer_recognized,
        "ai_speech_response": speech,
        "instruction_for_ai": "اقرأ للعميل نص ai_speech_response لتأكيد رقم الأوردر والإجمالي ووقت التوصيل.",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "branch_name": branch.name,
            "currency": branch.currency,
            "currency_name": cur_name,
            "currency_symbol": cur_sym,
            "customer_name": customer.name,
            "customer_phone": customer.phone,
            "delivery_address": clean_addr,
            "delivery_area": matched_area.name if matched_area else "غير محدد",
            "order_type": order.get_order_type_display(),
            "status": order.get_status_display(),
            "subtotal": float(subtotal),
            "delivery_fee": float(delivery_fee),
            "total": float(total),
            "items_count": len(order_items_prepared),
            "items": [
                {"name": oi["menu_item"].name, "qty": oi["quantity"], "price": float(oi["price"]), "total": float(oi["total"])}
                for oi in order_items_prepared
            ],
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
    }


@mcp.tool
def track_order(
    order_number: Optional[str] = None,
    customer_phone: Optional[str] = None,
    phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    تتبع حالة الأوردر للرد على العميل المتصل ومعرفة موقفه (في المطبخ / مع الدليفري / تم التسليم).
    يمكن الاستعلام بواسطة:
    1. رقم الأوردر مباشرة (مثال: 'DIY-3114' أو '3114' أو '٣١١٤').
    2. رقم هاتف العميل (مثال: '0559998877' أو '01012345678') للبحث عن أحدث أوردرات العميل الجارية تلقائياً.
    
    Args:
        order_number: (اختياري) رقم الأوردر أو المعرف الرقمي، أو يمكن تمرير رقم جوال العميل هنا مباشرة.
        customer_phone: (اختياري) رقم هاتف العميل للبحث عن أحدث أوردراته مباشرة.
        phone: (بديل) رقم هاتف العميل.
        phone_number: (بديل) رقم هاتف العميل.
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Order

    raw_query = str(order_number or "").strip()
    raw_phone = str(customer_phone or phone or phone_number or "").strip()

    # Diagnostic / Health check call from platform admin
    if not raw_query and not raw_phone:
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة تتبع حالة الأوردرات (track_order) جاهزة ونشطة بنجاح.",
            "diagnostic": True
        }

    norm_query = _normalize_digits(raw_query)
    norm_phone = _clean_phone(raw_phone)

    # If phone omitted but query looks like phone (>= 8 digits)
    if not norm_phone and re.match(r'^\+?[0-9]{8,15}$', norm_query):
        norm_phone = _clean_phone(norm_query)

    order = None
    customer_orders = []

    # 1. Search by exact order_number or digits inside order_number
    if norm_query:
        # 1.1 Direct exact match
        order = Order.objects.filter(tenant=tenant, order_number__iexact=norm_query).select_related("branch", "customer", "driver").first()

        # 1.2 Match with tenant prefix or standard prefixes if missing
        if not order:
            prefix = (tenant.slug[:3] if tenant and tenant.slug else "ORD").upper()
            for pfx in [prefix, "DIY", "ORD", "CC"]:
                if not norm_query.upper().startswith(f"{pfx}-"):
                    candidate = Order.objects.filter(tenant=tenant, order_number__iexact=f"{pfx}-{norm_query}").select_related("branch", "customer", "driver").first()
                    if candidate:
                        order = candidate
                        break

        # 1.3 Extract 3-5 digits sequence (e.g. "3114" from "طلب 3114")
        if not order:
            num_matches = re.findall(r'\d{3,5}', norm_query)
            for num in num_matches:
                found = Order.objects.filter(tenant=tenant, order_number__icontains=num).select_related("branch", "customer", "driver").order_by("-created_at").first()
                if found:
                    order = found
                    break

        # 1.4 Primary key ID
        if not order and norm_query.isdigit():
            order = Order.objects.filter(tenant=tenant, id=int(norm_query)).select_related("branch", "customer", "driver").first()

    # 2. Search by customer phone if not found yet
    if not order and norm_phone:
        suffix = norm_phone[-9:] if len(norm_phone) >= 9 else norm_phone
        phone_orders_qs = Order.objects.filter(tenant=tenant).filter(
            models.Q(customer_phone__icontains=suffix) | models.Q(customer__phone__icontains=suffix)
        ).select_related("branch", "customer", "driver").order_by("-created_at")

        customer_orders = list(phone_orders_qs[:5])
        if customer_orders:
            active_orders = [o for o in customer_orders if o.status in ["new", "preparing", "ready", "out_for_delivery", "on_way"]]
            order = active_orders[0] if active_orders else customer_orders[0]

    if not order:
        key_obj.record_usage(placed_order=False)
        identifier = raw_query or raw_phone or "المحدد"
        return {
            "ok": False,
            "error": f"لم يتم العثور على أي أوردر بالمعرف أو رقم الهاتف «{identifier}» في سجلات المطعم.",
            "searched_value": identifier,
            "ai_speech_response": "بعتذر لحضرتك، مش لاقية أي أوردر مسجل بالبيانات دي. ممكن تتأكد من رقم الأوردر أو تديني رقم التليفون اللي سجلت بيه الطلب؟",
            "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بلطف بعدم العثور على الأوردر واطلب منه رقم الجوال للبحث به كما في ai_speech_response."
        }

    status_speech_map = {
        "new": "طلبك مسجل وجاري إرساله للمطبخ.",
        "preparing": "طلبك حالياً بيتجهز في المطبخ بكل اهتمام.",
        "ready": "طلبك جاهز تماماً وبانتظار مندوب التوصيل للاستلام.",
        "out_for_delivery": "طلبك خرج مع المندوب وفي الطريق لحضرتك حالياً.",
        "on_way": "طلبك خرج مع المندوب وفي الطريق لحضرتك حالياً.",
        "delivered": "الطلب مسجل عندنا إنه تم تسليمه بنجاح.",
        "cancelled": "الطلب مسجل إنه ملغي.",
        "canceled": "الطلب مسجل إنه ملغي.",
    }
    speech_state = status_speech_map.get(order.status, f"حالة طلبك الحالية هي {order.get_status_display()}.")
    driver_speech = f" مع الكابتن {order.driver.name} ورقم هاتفه {order.driver.phone}" if (order.driver and order.status in ["out_for_delivery", "on_way"]) else ""
    ai_speech = f"يا فندم بخصوص طلبك رقم {order.order_number}، {speech_state}{driver_speech}."

    driver_info = None
    if order.driver:
        driver_info = {
            "name": order.driver.name,
            "phone": order.driver.phone or "غير مسجل",
        }

    items_data = [
        {"name": it.name, "quantity": it.qty, "price": float(it.price), "total": float(it.line_total)}
        for it in order.items.all()
    ]

    other_orders_summary = []
    if customer_orders and len(customer_orders) > 1:
        other_orders_summary = [
            {
                "order_number": o.order_number,
                "status": o.get_status_display(),
                "total": float(o.total),
                "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for o in customer_orders if o.id != order.id
        ]

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "matched_by": "customer_phone" if (norm_phone and (raw_phone or not raw_query.startswith("DIY-"))) else "order_number",
        "ai_speech_response": ai_speech,
        "instruction_for_ai": "أبلغ العميل بحالة طلبه كما هو موضح في ai_speech_response.",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "branch_name": order.branch.name if order.branch else "غير محدد",
            "status_code": order.status,
            "status_label": order.get_status_display(),
            "order_type": order.get_order_type_display(),
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "delivery_address": order.address,
            "delivery_fee": float(order.delivery_fee),
            "total": float(order.total),
            "currency": order.branch.currency if order.branch else "SAR",
            "currency_name": order.branch.get_currency_name_ar() if order.branch else "ريال",
            "currency_symbol": order.branch.get_currency_symbol_ar() if order.branch else "ر.س",
            "driver": driver_info,
            "items": items_data,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M"),
        },
        "other_recent_orders": other_orders_summary,
    }


@mcp.tool
def cancel_order(
    order_number: Optional[str] = None,
    customer_phone: Optional[str] = None,
    phone: Optional[str] = None,
    phone_number: Optional[str] = None,
    reason: str = "طلب العميل عبر الهاتف",
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إلغاء أوردر تم طلبه حديثاً بشرط أن يكون الأوردر لا يزال في حالة 'جديد' (new) ولم يبدأ المطبخ في تحضيره.
    يمكن تحديد الأوردر بواسطة رقم الأوردر أو برقم هاتف العميل تلقائياً.
    
    Args:
        order_number: (اختياري) رقم الأوردر (مثال: 'DIY-3114' أو '3114' أو '٣١١٤').
        customer_phone: (اختياري) رقم جوال العميل للبحث التلقائي عن أحدث أوردر جديد له وإلغائه.
        phone: (بديل) رقم هاتف العميل.
        phone_number: (بديل) رقم هاتف العميل.
        reason: سبب الإلغاء (يُسجل في ملاحظات وتاريخ الأوردر).
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Order

    raw_query = str(order_number or "").strip()
    raw_phone = str(customer_phone or phone or phone_number or "").strip()

    # Diagnostic / Health check call from platform admin
    if not raw_query and not raw_phone:
        return {
            "ok": True,
            "status": "ready",
            "message": "أداة إلغاء الأوردرات الجديدة (cancel_order) جاهزة ونشطة بنجاح.",
            "diagnostic": True
        }

    norm_query = _normalize_digits(raw_query)
    norm_phone = _clean_phone(raw_phone)

    if not norm_phone and re.match(r'^\+?[0-9]{8,15}$', norm_query):
        norm_phone = _clean_phone(norm_query)

    order = None

    # 1. Search by exact order_number or digits
    if norm_query:
        order = Order.objects.filter(tenant=tenant, order_number__iexact=norm_query).select_related("branch", "customer").first()
        if not order:
            prefix = (tenant.slug[:3] if tenant and tenant.slug else "ORD").upper()
            for pfx in [prefix, "DIY", "ORD", "CC"]:
                if not norm_query.upper().startswith(f"{pfx}-"):
                    candidate = Order.objects.filter(tenant=tenant, order_number__iexact=f"{pfx}-{norm_query}").select_related("branch", "customer").first()
                    if candidate:
                        order = candidate
                        break

        if not order:
            num_matches = re.findall(r'\d{3,5}', norm_query)
            for num in num_matches:
                found = Order.objects.filter(tenant=tenant, order_number__icontains=num).select_related("branch", "customer").order_by("-created_at").first()
                if found:
                    order = found
                    break

        if not order and norm_query.isdigit():
            order = Order.objects.filter(tenant=tenant, id=int(norm_query)).select_related("branch", "customer").first()

    # 2. Search by customer phone if not found
    if not order and norm_phone:
        suffix = norm_phone[-9:] if len(norm_phone) >= 9 else norm_phone
        phone_orders_qs = Order.objects.filter(tenant=tenant).filter(
            models.Q(customer_phone__icontains=suffix) | models.Q(customer__phone__icontains=suffix)
        ).select_related("branch", "customer").order_by("-created_at")

        active_orders = [o for o in phone_orders_qs[:5] if o.status in ["new", "preparing", "ready", "out_for_delivery", "on_way"]]
        order = active_orders[0] if active_orders else phone_orders_qs.first()

    if not order:
        key_obj.record_usage(placed_order=False)
        identifier = raw_query or raw_phone or "غير محدد"
        return {
            "ok": False,
            "error": f"لم يتم العثور على أي أوردر بالمعرف أو رقم الهاتف «{identifier}» لإلغائه.",
            "ai_speech_response": "مش لاقية أي أوردر مسجل بالبيانات دي عشان أقدر ألغيه لحضرتك. تحب تديني رقم تليفونك أبحث بيه؟",
            "instruction_for_ai": "لا تقل إن هناك عطلاً بالسيستم! أبلغ العميل بعدم العثور على الأوردر واطلب منه رقم الجوال للبحث به كما في ai_speech_response."
        }

    # Strict cancellation policy: only allow cancellation if order is 'new'
    if order.status in ["cancelled", "canceled"]:
        key_obj.record_usage(placed_order=False)
        return {
            "ok": False,
            "error": f"هذا الأوردر برقم «{order.order_number}» ملغي بالفعل مسبقاً.",
            "order_number": order.order_number,
            "current_status": "ملغي",
            "ai_speech_response": f"يا فندم الأوردر رقم {order.order_number} ملغي بالفعل من قبل كده.",
            "instruction_for_ai": "أخبر العميل أن هذا الطلب ملغي بالفعل مسبقاً كما في ai_speech_response."
        }
    elif order.status != "new":
        status_label = order.get_status_display()
        key_obj.record_usage(placed_order=False)
        return {
            "ok": False,
            "error": f"عذراً، الأوردر برقم «{order.order_number}» في مرحلة «{status_label}» ولا يمكن إلغاؤه آلياً لأن المطبخ بدأ في تحضيره بالفعل.",
            "order_number": order.order_number,
            "current_status": status_label,
            "ai_speech_response": f"بعتذر جداً لحضرتك، الأوردر رقم {order.order_number} دخل مرحلة التحضير في المطبخ ومبنقدرش نلغيه بعد ما بدأوا فيه. تحب أحول حضرتك لخدمة العملاء أو مدير الفرع؟",
            "instruction_for_ai": "أبلغ العميل بلطف أن الطلب دخل مرحلة التحضير في المطبخ ولا يمكن إلغاؤه كما في ai_speech_response."
        }

    # Cancel the order cleanly
    order.status = "cancelled"
    cancel_note = f"[تم الإلغاء آلياً بواسطة بوت الكول سنتر: {key_obj.name} - السبب: {reason}]"
    if order.notes:
        order.notes = f"{order.notes}\n{cancel_note}"
    else:
        order.notes = cancel_note
    order.save()

    # Real-time SSE push to kitchen display
    try:
        from core.kitchen_events import notify_kitchen_order_event
        notify_kitchen_order_event(order, "order_cancelled")
    except Exception as e:
        logger.warning(f"Failed to notify kitchen of AI cancelled order: {e}")

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "message": f"تم إلغاء الأوردر برقم {order.order_number} بنجاح.",
        "order_number": order.order_number,
        "status": "ملغي",
        "cancelled_at": timezone.now().strftime("%Y-%m-%d %H:%M"),
        "ai_speech_response": f"تمام يا فندم، تم إلغاء الأوردر رقم {order.order_number} بنجاح. أقدر أساعد حضرتك في أي طلب تاني؟",
        "instruction_for_ai": f"أبلغ العميل بأنه تم إلغاء الأوردر رقم {order.order_number} بنجاح كما في ai_speech_response، واسأله إذا كان يرغب في أي خدمة أخرى."
    }


@mcp.tool
def list_recent_orders(branch_id: Optional[int] = None, limit: int = 10, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    استعراض أحدث الأوردرات لمراقبة حركة الطلبات في المنشأة أو الفرع.
    
    Args:
        branch_id: (اختياري) معرف فرع محدد لتصفية طلباته فقط.
        limit: أقصى عدد أوردرات للإرجاع (الافتراضي 10).
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Order

    qs = Order.objects.filter(tenant=tenant).select_related("branch", "customer")
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    elif key_obj.assigned_branch:
        qs = qs.filter(branch=key_obj.assigned_branch)

    orders = qs.order_by("-created_at")[:min(limit, 50)]
    orders_data = [
        {
            "id": o.id,
            "order_number": o.order_number,
            "branch": o.branch.name if o.branch else "الفرع الرئيسي",
            "customer_name": o.customer_name,
            "order_type": o.get_order_type_display(),
            "status": o.get_status_display(),
            "total": float(o.total),
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for o in orders
    ]

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "tenant_name": tenant.name,
        "count": len(orders_data),
        "orders": orders_data,
    }


def run_server(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8002):
    """Run FastMCP server via STDIO or SSE."""
    if transport == "sse":
        import uvicorn
        print(f"Starting Restaurant FastMCP Server on SSE {host}:{port}...", file=sys.stderr)
        raw_app = mcp.http_app(transport="sse")
        app = SSEAuthMiddleware(raw_app)
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        # In stdio mode, stdout is reserved strictly for JSON-RPC messages
        mcp.run(transport="stdio")



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Restaurant Call Center FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="Transport mode")
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE server")
    parser.add_argument("--port", type=int, default=8002, help="Port for SSE server")
    args = parser.parse_args()
    run_server(transport=args.transport, host=args.host, port=args.port)
