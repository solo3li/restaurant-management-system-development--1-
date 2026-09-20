import os
import sys
import json
import random
from decimal import Decimal
from typing import List, Dict, Any, Optional

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

            # Transparently alias /sse or /messages to /mcp for backward/cross compatibility
            if path in ("/sse", "/messages") or path.startswith("/sse/") or path.startswith("/messages/"):
                scope["path"] = "/mcp"
                path = "/mcp"

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

                # If request has NO session id (or had empty one), but an active session exists for this key:
                # Auto-inject the active session ID so stateful endpoints (like subscriptions/listen) succeed!
                active_sid = KEY_LATEST_SESSION.get(key)
                has_valid_sid = any(k.lower() == b"mcp-session-id" and v.strip() for k, v in cleaned_headers)
                
                # For GET requests (subscriptions/listen) or POST calls after initialization:
                if not has_valid_sid and active_sid:
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


def get_mcp_asgi_app():
    """Return the FastMCP Streamable-HTTP app wrapped with access key authentication."""
    raw_app = mcp.http_app()  # Default transport = streamable-http in FastMCP 4.x
    return FastMCPAuthMiddleware(raw_app)


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


@mcp.tool
def get_menu(branch_id: int, category: Optional[str] = None, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    استعراض أصناف قائمة الطعام (Menu) المتوفرة في فرع محدد وأسعارها وتصنيفاتها.
    
    Args:
        branch_id: معرف الفرع المراد جلب المنيو الخاص به.
        category: (اختياري) تصفية حسب القسم مثل 'وجبات', 'برجر', 'مشروبات'.
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, MenuItem, BranchMenuAvailability

    branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
    if not branch:
        return {"ok": False, "error": f"الفرع برقم #{branch_id} غير موجود أو غير تابع للمنشأة."}

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
    branch_id: int,
    customer_phone: str,
    customer_name: str,
    customer_address: str,
    items: List[Dict[str, Any]],
    order_type: str = "delivery",
    delivery_area_id: Optional[int] = None,
    notes: str = "",
    access_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    إنشاء (ضرب) أوردر جديد من الكول سنتر مع تسجيل العميل تلقائياً واحتساب الحسابات المالية بالسيرفر.
    
    Args:
        branch_id: معرف الفرع الذي سينفذ الطلب.
        customer_phone: رقم هاتف العميل.
        customer_name: اسم العميل (سيتم حفظه وتحديثه تلقائياً).
        customer_address: عنوان التوصيل بالتفصيل (الحي، الكومبوند، العمارة، الشقة).
        items: قائمة الأصناف المطلوبة، كل صنف بصيغة {'item_id': 1, 'quantity': 2, 'notes': 'بدون بصل'}.
        order_type: نوع الطلب ('delivery' أو 'takeaway' أو 'dine_in'). الافتراضي هو 'delivery'.
        delivery_area_id: (اختياري) معرف منطقة التوصيل لتطبيق رسوم التوصيل المخصصة.
        notes: أي ملاحظات خاصة بالطلب مقدمة من العميل.
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Branch, Customer, MenuItem, Order, OrderItem, DeliveryArea, BranchMenuAvailability

    branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
    if not branch:
        return {"ok": False, "error": f"الفرع برقم #{branch_id} غير موجود."}

    if key_obj.assigned_branch and key_obj.assigned_branch_id != branch.id:
        return {"ok": False, "error": f"مفتاح الـ API مقيد بفرع «{key_obj.assigned_branch.name}» فقط."}

    clean_phone = str(customer_phone).strip().replace(" ", "").replace("-", "")
    if not clean_phone:
        return {"ok": False, "error": "رقم هاتف العميل مطلوب."}

    if not items or not isinstance(items, list):
        return {"ok": False, "error": "يجب تمرير قائمة أصناف صالحة في المعامل items."}

    # 1. Customer registration or update
    clean_name = str(customer_name).strip() or f"عميل هاتف ({clean_phone[-4:]})"
    clean_addr = str(customer_address).strip()
    customer, _ = Customer.objects.get_or_create(
        tenant=tenant,
        phone=clean_phone,
        defaults={"name": clean_name, "address": clean_addr}
    )
    if clean_name and customer.name != clean_name:
        customer.name = clean_name
    if clean_addr and customer.address != clean_addr:
        customer.address = clean_addr
    customer.save()

    # 2. Delivery fee calculation
    delivery_fee = Decimal("0.00")
    matched_area = None
    if order_type == "delivery":
        if delivery_area_id:
            matched_area = DeliveryArea.objects.filter(branch=branch, id=delivery_area_id, is_active=True).first()
            if matched_area:
                delivery_fee = matched_area.delivery_fee
        elif clean_addr:
            # Try to auto-match area from address
            for area in DeliveryArea.objects.filter(branch=branch, is_active=True):
                if area.name.lower() in clean_addr.lower():
                    matched_area = area
                    delivery_fee = area.delivery_fee
                    break

        # Fallback default delivery fee if none matched
        if not matched_area and delivery_fee == 0:
            delivery_fee = Decimal("10.00")

    # 3. Item validation & Server-side price calculation
    subtotal = Decimal("0.00")
    order_items_prepared = []
    disabled_items = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )

    for item_spec in items:
        m_id = item_spec.get("item_id")
        try:
            qty = int(item_spec.get("quantity", 1))
        except (ValueError, TypeError):
            qty = 1

        if qty <= 0:
            continue

        menu_item = MenuItem.objects.filter(tenant=tenant, id=m_id, available=True).first()
        if not menu_item:
            return {"ok": False, "error": f"الصنف رقم #{m_id} غير موجود في منيو المنشأة."}

        if menu_item.id in disabled_items:
            return {"ok": False, "error": f"الصنف «{menu_item.name}» غير متوفر حالياً في فرع {branch.name}."}

        line_total = menu_item.price * qty
        subtotal += line_total
        item_notes = str(item_spec.get("notes", "")).strip()
        order_items_prepared.append({
            "menu_item": menu_item,
            "quantity": qty,
            "price": menu_item.price,
            "total": line_total,
            "notes": item_notes,
        })

    if not order_items_prepared:
        return {"ok": False, "error": "لم يتم تحديد أي أصناف صالحة في الطلب."}

    # Tax & Total
    tax = (subtotal * Decimal("0.14")).quantize(Decimal("0.01"))
    total = subtotal + delivery_fee

    # Unique Order Number
    while True:
        order_number = f"DIY-{random.randint(1000, 9999)}"
        if not Order.objects.filter(tenant=tenant, order_number=order_number).exists():
            break

    full_notes = f"[بوت الكول سنتر: {key_obj.name}] {notes}".strip()

    # Create Order
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

    # Create Order Items
    for oi in order_items_prepared:
        OrderItem.objects.create(
            order=order,
            menu_item=oi["menu_item"],
            name=oi["menu_item"].name,
            price=oi["price"],
            qty=oi["quantity"],
        )

    # Record API key usage
    key_obj.record_usage(placed_order=True)

    return {
        "ok": True,
        "message": f"تم إنشاء الأوردر بنجاح برقم {order.order_number}",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "branch_name": branch.name,
            "customer_name": customer.name,
            "customer_phone": customer.phone,
            "delivery_address": clean_addr,
            "order_type": order.get_order_type_display(),
            "status": order.get_status_display(),
            "subtotal": float(subtotal),
            "delivery_fee": float(delivery_fee),
            "total": float(total),
            "items_count": len(order_items_prepared),
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
    }


@mcp.tool
def track_order(order_number: str, access_key: Optional[str] = None) -> Dict[str, Any]:
    """
    تتبع حالة الأوردر للرد على العميل المتصل ومعرفة موقفه (في المطبخ / مع الدليفري / تم التسليم).
    
    Args:
        order_number: رقم الأوردر (مثال: 'DIY-1041' أو معرف الأوردر الرقمي).
        access_key: (اختياري) مفتاح الدخول (يُقرأ تلقائياً من البيئة RESTAURANT_ACCESS_KEY إن لم يُمرر).
    """
    key_obj, tenant = _authenticate(access_key)
    from core.models import Order

    query = str(order_number).strip()
    order = Order.objects.filter(tenant=tenant, order_number__iexact=query).select_related("branch", "customer", "driver").first()

    if not order and query.isdigit():
        order = Order.objects.filter(tenant=tenant, id=int(query)).select_related("branch", "customer", "driver").first()

    if not order:
        key_obj.record_usage(placed_order=False)
        return {"ok": False, "error": f"الأوردر «{query}» غير موجود في سجل المنشأة."}

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

    key_obj.record_usage(placed_order=False)
    return {
        "ok": True,
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "branch_name": order.branch.name,
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
        }
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
        print(f"Starting Restaurant FastMCP Server on SSE {host}:{port}...", file=sys.stderr)
        mcp.run(transport="sse", host=host, port=port)
    else:
        # In stdio mode, stdout is reserved strictly for JSON-RPC messages
        mcp.run(transport="stdio")



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Restaurant Call Center FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="Transport mode")
    parser.add_argument("--host", default="127.0.0.1", help="Host for SSE server")
    parser.add_argument("--port", type=int, default=8002, help="Port for SSE server")
    args = parser.parse_args()
    run_server(transport=args.transport, host=args.host, port=args.port)
