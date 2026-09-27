import os
import sys
import json
import random
from decimal import Decimal
from typing import List, Dict, Any, Optional
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

from django.db import models
from django.utils import timezone
from fastmcp import FastMCP
import contextvars
from urllib.parse import parse_qs
from asgiref.sync import sync_to_async

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
    return TenantApiKey.objects.filter(key=key, is_active=True).exists()


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

                # If still no key, but there is only one active key in system or latest session
                if not key and len(KEY_LATEST_SESSION) == 1:
                    key = list(KEY_LATEST_SESSION.keys())[0]

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
    """ASGI Middleware to authenticate FastMCP SSE connections."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode("latin1")
            key = None
            if auth.startswith("Bearer "):
                key = auth[7:].strip()
            elif auth:
                key = auth.strip()

            if not key:
                x_key = headers.get(b"x-access-key", b"").decode("latin1")
                if x_key:
                    key = x_key.strip()

            if not key:
                query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
                qs = parse_qs(query_string)
                key = qs.get("access_key", [None])[0]

            if not key and len(KEY_LATEST_SESSION) == 1:
                key = list(KEY_LATEST_SESSION.keys())[0]

            if key:
                valid = await sync_to_async(_check_key_valid)(key)
                if not valid:
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]
                    })
                    await send({"type": "http.response.body", "body": "مفتاح الدخول غير صالح".encode("utf-8")})
                    return
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

    if tenant.subscription_status in ["expired", "canceled"]:
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


def _normalize_arabic_text(text: str) -> str:
    """تسوية النصوص العربية للمطابقة الدقيقة مع الأصناف والمناطق."""
    if not text:
        return ""
    t = str(text).strip().lower()
    t = re.sub(r'[\u064B-\u0652]', '', t)
    t = re.sub(r'[أإآٱ]', 'ا', t)
    t = re.sub(r'[ىي]', 'ي', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _clean_phone(phone: Any) -> str:
    """تنظيف وتوحيد رقم الهاتف لتسهيل البحث والمطابقة."""
    if not phone:
        return ""
    p = str(phone).strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if p.startswith("+"):
        p = p[1:]
    return p


def _find_menu_item(tenant, branch, item_spec: Dict[str, Any], disabled_item_ids: set) -> tuple[Optional[Any], Optional[str]]:
    """
    محرك بحث ومطابقة صارم للأصناف (Strict Dual Resolver):
    1. التحقق بواسطة item_id أو id (معرف الصنف المباشر).
    2. التحقق بواسطة name أو item_name (المطابقة الاسمية الصارمة مع تنظيف الحروف والتشكيل).
    3. التحقق من توفر الصنف في الفرع الحالي عبر BranchMenuAvailability.
    """
    from core.models import MenuItem

    raw_id = item_spec.get("item_id") if item_spec.get("item_id") is not None else item_spec.get("id")
    raw_name = str(item_spec.get("name") or item_spec.get("item_name") or "").strip()

    # 1. البحث بمعرف الصنف (ID)
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

    # 2. البحث بالاسم (Name)
    if not raw_name:
        return None, "يجب تحديد رقم الصنف (item_id) أو اسمه الدقيق (name) في عناصر الطلب."

    norm_query = _normalize_arabic_text(raw_name)
    all_tenant_items = list(MenuItem.objects.filter(tenant=tenant, available=True))

    # 2.1 المطابقة التامة بعد التسوية
    exact_matches = [m for m in all_tenant_items if _normalize_arabic_text(m.name) == norm_query]
    if len(exact_matches) == 1:
        matched = exact_matches[0]
        if matched.id in disabled_item_ids:
            return None, f"الصنف «{matched.name}» غير متوفر حالياً في فرع «{branch.name}»."
        return matched, None

    # 2.2 المطابقة بمجموعة الكلمات (Token Matching)
    q_tokens = set(norm_query.split())
    if q_tokens:
        token_matches = [m for m in all_tenant_items if q_tokens.issubset(set(_normalize_arabic_text(m.name).split()))]
        if len(token_matches) == 1:
            matched = token_matches[0]
            if matched.id in disabled_item_ids:
                return None, f"الصنف «{matched.name}» غير متوفر حالياً في فرع «{branch.name}»."
            return matched, None
        elif len(token_matches) > 1:
            matching_names = " أو ".join([f"«{m.name}» (رقم #{m.id})" for m in token_matches[:4]])
            return None, f"اسم الصنف «{raw_name}» غير محدد بدقة ويطابق أكثر من صنف: ({matching_names}). يرجى تحديد الاسم بالكامل أو استخدام رقم الصنف."

    # 2.3 مطابقة الاحتواء الجزئي إذا كان يطابق صنفاً واحداً فقط
    contains_matches = [m for m in all_tenant_items if (norm_query in _normalize_arabic_text(m.name) or _normalize_arabic_text(m.name) in norm_query)]
    if len(contains_matches) == 1:
        matched = contains_matches[0]
        if matched.id in disabled_item_ids:
            return None, f"الصنف «{matched.name}» غير متوفر حالياً في فرع «{branch.name}»."
        return matched, None

    # 2.4 في حال عدم العثور عليه نهائياً، رفض صريح مع اقتراح الأصناف المتوفرة
    available_branch_items = [m.name for m in all_tenant_items if m.id not in disabled_item_ids][:5]
    suggest_str = "، ".join(available_branch_items)
    return None, f"الصنف «{raw_name}» غير موجود في قائمة طعام المطعم. من الأصناف المتوفرة: {suggest_str}."


@mcp.tool
def get_menu(branch_id: Optional[int] = None, category: Optional[str] = None, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    استعراض أصناف قائمة الطعام (Menu) المتوفرة في فرع محدد وأسعارها وتصنيفاتها.
    الأسعار بالريال السعودي وشاملة لضريبة القيمة المضافة 15%.
    
    Args:
        branch_id: (اختياري) معرف الفرع المراد جلب المنيو الخاص به. إن لم يحدد يتم جلب الفرع الرئيسي تلقائياً.
        category: (اختياري) تصفية حسب القسم مثل 'أطباق رئيسية', 'مشويات', 'مقبلات', 'مشروبات'.
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

    items_qs = MenuItem.objects.filter(tenant=tenant, available=True)
    if category and category.strip():
        items_qs = items_qs.filter(category__icontains=category.strip())

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
            "price": float(m.price),
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
        "total_items": len(items_list),
        "categories": list(categories_map.keys()),
        "items": items_list,
    }


@mcp.tool
def lookup_customer(phone: str, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    البحث عن العميل برقم هاتفه لجلب اسمه وعناوينه والكومبوند وتاريخ طلباته السابقة.
    
    Args:
        phone: رقم هاتف العميل (مثال: '01012345678').
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Customer, Order

    clean_phone = str(phone).strip().replace(" ", "").replace("-", "")
    customer = Customer.objects.filter(tenant=tenant, phone=clean_phone).first()

    if not customer:
        key_obj.record_usage(placed_order=False)
        return {
            "ok": True,
            "found": False,
            "phone": clean_phone,
            "message": "عميل جديد غير مسجل مسبقاً. سيتم إنشاؤه وحفظ بياناته تلقائياً عند تسجيل الأوردر."
        }

    # Fetch recent orders for this customer
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

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "found": True,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "address": customer.address,
            "total_orders": order_count,
            "total_spent": total_spent,
            "created_at": customer.created_at.strftime("%Y-%m-%d"),
        },
        "recent_orders": orders_data,
    }


@mcp.tool
def check_delivery_coverage(branch_id: int, area_name: str, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    فحص هل منطقة العميل أو الكومبوند يقع ضمن مناطق توصيل الفرع المحدد، وحساب رسوم ووقت التوصيل.
    
    Args:
        branch_id: معرف الفرع.
        area_name: اسم المنطقة أو الحي أو الكومبوند (مثال: 'مدينة الشروق', 'كمبوند النرجس', 'الياسمين').
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, DeliveryArea

    branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
    if not branch:
        return {"ok": False, "error": f"الفرع برقم #{branch_id} غير موجود."}

    query = str(area_name).strip()
    area = DeliveryArea.objects.filter(
        branch=branch,
        name__icontains=query,
        is_active=True
    ).first()

    all_areas = list(
        DeliveryArea.objects.filter(branch=branch, is_active=True).values("id", "name", "area_type", "delivery_fee", "estimated_time_minutes")
    )

    key_obj.record_usage(placed_order=False)
    if area:
        return {
            "ok": True,
            "covered": True,
            "branch_id": branch.id,
            "branch_name": branch.name,
            "matched_area": {
                "id": area.id,
                "name": area.name,
                "area_type": area.get_area_type_display(),
                "delivery_fee": float(area.delivery_fee),
                "estimated_time_minutes": area.estimated_time_minutes,
                "notes": area.notes or "",
            }
        }
    else:
        return {
            "ok": True,
            "covered": False,
            "branch_id": branch.id,
            "branch_name": branch.name,
            "searched_area": query,
            "message": f"المنطقة «{query}» لم يتم العثور عليها في مناطق تغطية فرع {branch.name}.",
            "available_areas": [a["name"] for a in all_areas],
        }


@mcp.tool
def create_callcenter_order(
    branch_id: Optional[int] = None,
    customer_phone: str = "",
    customer_name: Optional[str] = "",
    customer_address: Optional[str] = "",
    items: Optional[List[Dict[str, Any]]] = None,
    order_type: str = "delivery",
    delivery_area_id: Optional[int] = None,
    delivery_area_name: Optional[str] = None,
    notes: str = "",
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إنشاء (ضرب) أوردر جديد من الكول سنتر مع التعرف التلقائي على العميل برقم هاتفه،
    ومطابقة الأصناف الصارمة بالرقم أو الاسم، والتحقق الصارم من مناطق التوصيل.
    
    Args:
        branch_id: (اختياري) معرف الفرع المنفذ للطلب. إن لم يحدد يتم اعتماد الفرع الرئيسي.
        customer_phone: رقم هاتف العميل (إلزامي للتعرف على العميل وتتبع الطلب).
        customer_name: (اختياري) اسم العميل (يُحدث تلقائياً ويُسترجع من سجله السابق إن وجد).
        customer_address: عنوان التوصيل بالتفصيل (الحي، الشارع، العمارة، الشقة).
        items: قائمة الأصناف المطلوبة. كل عنصر يمكن تمريره برقم الصنف 'item_id' أو اسمه 'name' مع الكمية 'quantity'.
        order_type: نوع الطلب ('delivery' أو 'takeaway' أو 'dine_in'). الافتراضي هو 'delivery'.
        delivery_area_id: (اختياري) معرف منطقة التوصيل لتطبيق رسومها المحددة بدقة.
        delivery_area_name: (اختياري) اسم منطقة أو حي التوصيل (مثل: 'مدينة الشروق', 'العليا').
        notes: أي ملاحظات خاصة بالطلب (مثل: بدون شطة، زيادة صوص).
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, Customer, MenuItem, Order, OrderItem, DeliveryArea, BranchMenuAvailability

    # 1. Branch Resolution
    if branch_id is not None:
        branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
        if not branch:
            return {"ok": False, "error": f"الفرع برقم #{branch_id} غير موجود أو غير نشط في المنشأة."}
    elif key_obj.assigned_branch:
        branch = key_obj.assigned_branch
    else:
        branch = Branch.objects.filter(tenant=tenant, status="active").first()
        if not branch:
            return {"ok": False, "error": "لا توجد فروع نشطة متاحة للمنشأة حالياً."}

    if key_obj.assigned_branch and key_obj.assigned_branch_id != branch.id:
        return {"ok": False, "error": f"مفتاح الـ API مقيد بفرع «{key_obj.assigned_branch.name}» فقط."}

    # 2. Strict Phone Validation & Customer Recognition
    clean_phone = _clean_phone(customer_phone)
    if not clean_phone or len(clean_phone) < 8:
        return {"ok": False, "error": "رقم هاتف العميل غير صالح. يرجى تزويدنا برقم جوال صالح مكون من 8 أرقام على الأقل."}

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
        customer = Customer.objects.create(
            tenant=tenant,
            phone=clean_phone,
            name=clean_name,
            address=clean_addr,
        )

    # 3. Order Type & Strict Delivery Coverage Verification
    order_type = str(order_type or "delivery").strip().lower()
    if order_type not in ["delivery", "takeaway", "dine_in"]:
        order_type = "delivery"

    delivery_fee = Decimal("0.00")
    matched_area = None

    if order_type == "delivery":
        if not clean_addr:
            return {
                "ok": False,
                "error": "عنوان التوصيل مطلوب لتنفيذ طلبات التوصيل (Delivery). يرجى تزويدنا بعنوان العميل بالتفصيل أو اختيار الاستلام من الفرع (takeaway)."
            }

        active_areas = list(DeliveryArea.objects.filter(branch=branch, is_active=True))
        if not active_areas:
            return {
                "ok": False,
                "error": f"عذراً، خدمة التوصيل غير مفعلة حالياً في فرع «{branch.name}». يمكنك استلام الطلب من الفرع (سفري)."
            }

        norm_addr = _normalize_arabic_text(clean_addr)

        if delivery_area_id:
            matched_area = next((a for a in active_areas if a.id == delivery_area_id), None)

        if not matched_area and delivery_area_name:
            norm_param_area = _normalize_arabic_text(delivery_area_name)
            for area in active_areas:
                norm_area = _normalize_arabic_text(area.name)
                if norm_area == norm_param_area or norm_param_area in norm_area or norm_area in norm_param_area:
                    matched_area = area
                    break

        if not matched_area:
            for area in active_areas:
                norm_area = _normalize_arabic_text(area.name)
                if norm_area in norm_addr or norm_addr in norm_area:
                    matched_area = area
                    break

        if not matched_area:
            addr_words = set(norm_addr.split())
            for area in active_areas:
                area_words = set(_normalize_arabic_text(area.name).split())
                if area_words and area_words.issubset(addr_words):
                    matched_area = area
                    break

        # STRICT REJECTION: Reject immediately if outside coverage
        if not matched_area:
            covered_names = [a.name for a in active_areas]
            covered_str = "، ".join(covered_names[:6])
            return {
                "ok": False,
                "error": f"عذراً، العنوان المحدد «{clean_addr}» خارج نطاق تغطية التوصيل لفرع «{branch.name}». يرجى إبلاغ العميل بأنه يمكنه استلام الطلب بنفسه من الفرع (سفري / Takeaway) أو تزويدنا بعنوان بديل داخل نطاق التغطية. المناطق والأحياء المغطاة حالياً: {covered_str}.",
                "available_areas": covered_names,
                "suggested_action": "takeaway"
            }

        delivery_fee = matched_area.delivery_fee

    # 4. Strict Menu Items Resolver & Total Calculation
    if not items or not isinstance(items, list):
        return {
            "ok": False,
            "error": "قائمة الأصناف (items) مطلوبة لتنفيذ الطلب. يرجى تزويدنا بالأصناف والكميات المطلوبة."
        }

    disabled_item_ids = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )

    subtotal = Decimal("0.00")
    order_items_prepared = []

    for idx, item_spec in enumerate(items, start=1):
        if not isinstance(item_spec, dict):
            return {"ok": False, "error": f"بيانات الصنف رقم {idx} غير صالحة، يجب أن تكون كائناً يحتوي على 'item_id' أو 'name' و 'quantity'."}

        menu_item, match_err = _find_menu_item(tenant, branch, item_spec, disabled_item_ids)
        if match_err:
            return {"ok": False, "error": match_err}

        try:
            qty = int(item_spec.get("quantity") or item_spec.get("qty") or 1)
        except (ValueError, TypeError):
            qty = 1

        if qty <= 0:
            continue

        line_total = menu_item.price * qty
        subtotal += line_total
        item_notes = str(item_spec.get("notes") or item_spec.get("special_instructions") or "").strip()

        order_items_prepared.append({
            "menu_item": menu_item,
            "quantity": qty,
            "price": menu_item.price,
            "total": line_total,
            "notes": item_notes,
        })

    if not order_items_prepared:
        return {"ok": False, "error": "لم يتم العثور على أي أصناف صالحة أو كميات مقبولة في الطلب."}

    # Tax (15% VAT included standard) & Grand Total
    tax = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    total = subtotal + delivery_fee

    # Unique Order Number
    while True:
        order_number = f"DIY-{random.randint(1000, 9999)}"
        if not Order.objects.filter(tenant=tenant, order_number=order_number).exists():
            break

    full_notes = f"[AI Call Center: {key_obj.name}] {notes}".strip()

    # 5. Atomic Order Creation
    order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number=order_number,
        order_type=order_type,
        channel="call_center",
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        address=clean_addr,
        delivery_area=matched_area,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        discount=Decimal("0.00"),
        total=total,
        paid=False,
        cashier=f"AI: {key_obj.name}",
        notes=full_notes,
        status="new",
    )

    for oi in order_items_prepared:
        OrderItem.objects.create(
            order=order,
            menu_item=oi["menu_item"],
            name=oi["menu_item"].name,
            price=oi["price"],
            qty=oi["quantity"],
        )

    key_obj.record_usage(placed_order=True)

    return {
        "ok": True,
        "message": f"تم إنشاء الأوردر بنجاح برقم {order.order_number}",
        "customer_recognized": customer_recognized,
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "branch_name": branch.name,
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
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    تتبع حالة الأوردر للرد على العميل المتصل ومعرفة موقفه (في المطبخ / مع الدليفري / تم التسليم).
    يمكن الاستعلام بواسطة:
    1. رقم الأوردر مباشرة (مثال: 'DIY-1041' أو معرف الأوردر الرقمي).
    2. رقم هاتف العميل (مثال: '0559998877' أو '+966559998877') للبحث عن أحدث أوردرات العميل الجارية تلقائياً.
    
    Args:
        order_number: (اختياري) رقم الأوردر أو المعرف الرقمي، أو يمكن تمرير رقم جوال العميل هنا مباشرة.
        customer_phone: (اختياري) رقم هاتف العميل للبحث عن أحدث أوردراته مباشرة.
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Order

    query_str = str(order_number or "").strip()
    phone_str = str(customer_phone or "").strip()

    cleaned_phone = _clean_phone(phone_str)
    if not cleaned_phone and query_str and not query_str.startswith("DIY-") and any(c.isdigit() for c in query_str) and len(query_str) >= 8:
        potential_phone = _clean_phone(query_str)
        if len(potential_phone) >= 8:
            cleaned_phone = potential_phone

    order = None

    # 1. Search by exact order_number or numeric id
    if query_str:
        order = Order.objects.filter(tenant=tenant, order_number__iexact=query_str).select_related("branch", "customer", "driver").first()
        if not order and query_str.isdigit():
            order = Order.objects.filter(tenant=tenant, id=int(query_str)).select_related("branch", "customer", "driver").first()

    # 2. Search by customer phone if not found or if searched by phone
    customer_orders = []
    if not order and cleaned_phone:
        suffix = cleaned_phone[-9:] if len(cleaned_phone) >= 9 else cleaned_phone
        phone_orders_qs = Order.objects.filter(tenant=tenant).filter(
            models.Q(customer_phone__icontains=suffix) | models.Q(customer__phone__icontains=suffix)
        ).select_related("branch", "customer", "driver").order_by("-created_at")

        customer_orders = list(phone_orders_qs[:5])
        if customer_orders:
            active_orders = [o for o in customer_orders if o.status in ["new", "preparing", "ready", "on_way"]]
            order = active_orders[0] if active_orders else customer_orders[0]

    if not order:
        key_obj.record_usage(placed_order=False)
        identifier = phone_str or query_str or "غير محدد"
        return {
            "ok": False,
            "error": f"لم يتم العثور على أي أوردر بالمعرف أو رقم الهاتف «{identifier}» في سجلات المطعم.",
            "searched_value": identifier,
            "hint": "تأكد من رقم الأوردر أو رقم هاتف العميل المسجل به الطلب."
        }

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
        "matched_by": "customer_phone" if (cleaned_phone and (phone_str or not query_str.startswith("DIY-"))) else "order_number",
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
            "driver": driver_info,
            "items": items_data,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M"),
        },
        "other_recent_orders": other_orders_summary,
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
            "branch": o.branch.name,
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
