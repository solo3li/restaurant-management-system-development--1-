import os
import urllib.request
import urllib.parse
import json
import ssl
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

PARTNER_API_BASE_URL = os.getenv("PARTNER_API_BASE_URL", "https://app.169.58.32.179.nip.io/api/partner/v1").rstrip("/")
PARTNER_API_KEY = os.getenv("PARTNER_API_KEY", "sk_live_prt_RwTTVvzpzrGbWRmxklS8BC3qm_3djMVxxD1UVom0cfA")

# SSL Context to allow local self-signed or wildcard certs
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def _request(path: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{PARTNER_API_BASE_URL}{path}"
    headers = {
        "X-Partner-Key": PARTNER_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30.0, context=_SSL_CONTEXT) as response:
            resp_body = response.read().decode("utf-8")
            return json.loads(resp_body)
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8", errors="ignore")
        logger.error(f"Partner API HTTPError [{e.code}] on {method} {path}: {error_msg}")
        try:
            parsed = json.loads(error_msg)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        clean_msg = "حدث خطأ أثناء معالجة الطلب في خادم الاتصالات."
        if e.code in (400, 409):
            clean_msg = "رقم التحويلة مسجل بالفعل لهذا المطعم أو أن البيانات غير صحيحة."
        return {"status": "error", "code": e.code, "message": clean_msg}
    except Exception as ex:
        logger.error(f"Partner API Request Exception on {method} {path}: {ex}", exc_info=True)
        return {"status": "error", "message": str(ex)}


def get_client_id_for_tenant(tenant) -> int:
    """Return mapped partner client_id for given restaurant tenant, auto-registering if needed."""
    if not tenant:
        return 49
    if getattr(tenant, "voice_client_id", None):
        return tenant.voice_client_id

    # Tenant 1 (سلسلة مطاعم كُـورَا / diyafa) is client 49 on the partner platform
    if getattr(tenant, "id", None) == 1 or getattr(tenant, "slug", "") in ("diyafa", "kura"):
        tenant.voice_client_id = 49
        tenant.save(update_fields=["voice_client_id"])
        return 49

    # Dynamically auto-register tenant if not registered yet
    try:
        reg = ensure_tenant_registered(tenant)
        cid = reg.get("client_id")
        if cid:
            return cid
    except Exception as e:
        logger.warning(f"Could not auto-register tenant {getattr(tenant, 'name', '')}: {e}")

    cid = getattr(tenant, "voice_client_id", None)
    if not cid:
        raise ValueError(f"تعذر العثور على حساب سنترال صوتي مربوط بالمنشأة «{getattr(tenant, 'name', '')}». يرجى مراجعة إعدادات الكول سنتر.")
    return cid


DEFAULT_PLAN_VOICE_CAPS = {
    "trial": {"minute_cap": 50, "spending_cap": 5.0},
    "starter": {"minute_cap": 150, "spending_cap": 15.0},
    "basic": {"minute_cap": 150, "spending_cap": 15.0},
    "standard": {"minute_cap": 150, "spending_cap": 15.0},
    "growth": {"minute_cap": 500, "spending_cap": 40.0},
    "pro": {"minute_cap": 500, "spending_cap": 40.0},
    "premium": {"minute_cap": 500, "spending_cap": 40.0},
    "enterprise": {"minute_cap": 1500, "spending_cap": 100.0},
}
DEFAULT_VOICE_CAPS = {"minute_cap": 150, "spending_cap": 15.0}


def get_plan_voice_caps(tenant_or_plan=None) -> Dict[str, Any]:
    """
    Resolve minute and spending caps based on tenant subscription plan tier.
    Default distribution:
      - Trial: 50 mins, $5.00
      - Starter / Basic / Standard: 150 mins, $15.00
      - Pro / Growth / Premium: 500 mins, $40.00
      - Enterprise: 1500 mins, $100.00
    """
    plan_code = "standard"
    if tenant_or_plan:
        if hasattr(tenant_or_plan, "subscription_plan") and tenant_or_plan.subscription_plan:
            plan_code = (tenant_or_plan.subscription_plan.code or "").lower()
        elif hasattr(tenant_or_plan, "plan"):
            plan_code = (tenant_or_plan.plan or "").lower()
        elif hasattr(tenant_or_plan, "code"):
            plan_code = (tenant_or_plan.code or "").lower()
        elif isinstance(tenant_or_plan, str):
            plan_code = tenant_or_plan.strip().lower()

    caps = DEFAULT_PLAN_VOICE_CAPS.get(plan_code)
    if not caps:
        # Fallback keyword matching
        if any(k in plan_code for k in ("trial", "free", "تجريب")):
            caps = DEFAULT_PLAN_VOICE_CAPS["trial"]
        elif any(k in plan_code for k in ("enter", "corp", "شركات")):
            caps = DEFAULT_PLAN_VOICE_CAPS["enterprise"]
        elif any(k in plan_code for k in ("pro", "growth", "prem", "متقدم", "نمو", "احتراف")):
            caps = DEFAULT_PLAN_VOICE_CAPS["pro"]
        else:
            caps = DEFAULT_PLAN_VOICE_CAPS["standard"]

    return dict(caps)


def update_client_cap(client_id: int, minute_cap: Optional[int] = None, spending_cap: Optional[float] = None, is_active: Optional[bool] = None) -> Dict[str, Any]:
    """
    Direct Partner API call to update call minute and spending caps for a client.
    Target: POST /api/partner/v1/clients/<client_id>/cap/
    """
    payload = {"client_id": int(client_id)}
    if minute_cap is not None:
        payload["minute_cap"] = int(minute_cap)
    if spending_cap is not None:
        payload["spending_cap"] = float(spending_cap)
    if is_active is not None:
        payload["is_active"] = bool(is_active)

    return _request(f"/clients/{client_id}/cap/", method="POST", data=payload)


def get_client_usage(client_id: int) -> Dict[str, Any]:
    """
    Fetch live usage statistics, consumption, and cap limits for a sub-client
    from the Partner API.
    Target: GET /api/partner/v1/clients/<client_id>/
    Fallback: GET /api/partner/v1/clients/ (matching by client_id)
    """
    resp = _request(f"/clients/{client_id}/")
    if resp.get("status") == "success" and "client" in resp:
        return resp

    # Fallback to list search if direct detail endpoint fails
    list_resp = _request("/clients/")
    if list_resp.get("status") == "success":
        for c in list_resp.get("clients", []):
            if c.get("client_id") == client_id or c.get("id") == client_id:
                return {"status": "success", "client": c}
    return resp


def sync_tenant_voice_caps(tenant, reset_to_plan: bool = True, minute_cap: Optional[int] = None, spending_cap: Optional[float] = None, is_active: Optional[bool] = None) -> Dict[str, Any]:
    """
    Synchronize call minute and spending caps to the Voice AI partner platform for a tenant.
    If caps are not explicitly passed and reset_to_plan is True, caps are determined by the
    tenant's active subscription plan tier:
      - Trial: 50 mins, $5.00
      - Starter / Basic / Standard: 150 mins, $15.00
      - Pro / Growth / Premium: 500 mins, $40.00
      - Enterprise: 1500 mins, $100.00
    """
    if not tenant:
        return {"status": "error", "message": "No tenant provided"}

    client_id = getattr(tenant, "voice_client_id", None)
    if not client_id:
        try:
            reg = ensure_tenant_registered(tenant)
            client_id = reg.get("client_id")
        except Exception as e:
            logger.warning(f"Could not auto-register tenant for voice cap sync: {e}")

    if not client_id:
        return {"status": "error", "message": f"المنشأة «{tenant.name}» غير مسجلة في السنترال الصوتي بعد."}

    if minute_cap is None and spending_cap is None:
        plan_caps = get_plan_voice_caps(tenant)
        minute_cap = plan_caps["minute_cap"]
        spending_cap = plan_caps["spending_cap"]

    resp = update_client_cap(
        client_id=client_id,
        minute_cap=minute_cap,
        spending_cap=spending_cap,
        is_active=is_active if is_active is not None else tenant.is_active,
    )
    logger.info(f"Synced voice caps for tenant '{tenant.slug}' (client_id={client_id}): minute_cap={minute_cap}, spending_cap={spending_cap}, result={resp.get('status')}")
    return resp


def register_sub_client(name: str, external_reference: str, email: str = "", password: str = "", spending_cap: float = 25.0, minute_cap: int = 300) -> Dict[str, Any]:
    """Register a new sub-client tenant on the Voice AI partner platform."""
    import secrets
    if not password:
        password = f"Diyafa@{secrets.token_hex(4)}!"

    payload = {
        "external_reference": external_reference.strip(),
        "name": name.strip(),
        "email": email.strip() if email else f"{external_reference}@saas-partner.local",
        "password": password.strip(),
        "spending_cap": float(spending_cap),
        "minute_cap": int(minute_cap),
    }
    resp = _request("/clients/register/", method="POST", data=payload)
    if resp.get("status") == "success":
        resp["password_used"] = password.strip()
    return resp


def ensure_tenant_registered(tenant, password: str = "") -> Dict[str, Any]:
    """Ensure a tenant has a registered voice client and owner credentials saved."""
    if not tenant:
        return {"status": "error", "message": "No tenant provided"}

    if tenant.voice_client_id and tenant.voice_username:
        return {
            "status": "success",
            "client_id": tenant.voice_client_id,
            "username": tenant.voice_username,
            "password": tenant.voice_password,
        }

    caps = get_plan_voice_caps(tenant)
    # Register sub-client on the partner platform with tier caps
    res = register_sub_client(
        name=tenant.name,
        external_reference=tenant.slug,
        email=tenant.email,
        password=password or tenant.voice_password or "",
        minute_cap=caps["minute_cap"],
        spending_cap=caps["spending_cap"],
    )
    if res.get("status") == "success":
        client_data = res.get("client") or {}
        creds = res.get("credentials") or {}
        
        cid = client_data.get("client_id") or res.get("client_id")
        uname = client_data.get("username") or creds.get("username", "")
        pwd = res.get("password_used") or creds.get("password", "")

        tenant.voice_client_id = cid
        tenant.voice_username = uname
        tenant.voice_password = pwd
        tenant.voice_is_active = True
        tenant.save(update_fields=["voice_client_id", "voice_username", "voice_password", "voice_is_active"])

        return {
            "status": "success",
            "client_id": cid,
            "username": uname,
            "password": pwd,
        }
    return res


def get_profile(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/profiles/")


def get_studio_metadata(client_id: int) -> Dict[str, Any]:
    """Fetch studio customization metadata (30 Google voices, 11 languages, 29 dialects, roles)."""
    return _request(f"/clients/{client_id}/profiles/studio/")


def create_profile(client_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new AI voice profile via POST /clients/{client_id}/profiles/"""
    dialect = data.get("dialect", "egyptian")
    if dialect == "modern_standard":
        dialect = "fusha"

    language = data.get("language") or "arabic"

    payload = {
        "name": (data.get("name") or "مساعد صوتي جديد").strip(),
        "language": language,
        "voice_name": data.get("voice_name", "Aoede"),
        "gender": data.get("gender", "female"),
        "dialect": dialect,
        "persona_role": data.get("persona_role", "restaurant_orders"),
        "speaking_style": data.get("speaking_style", "friendly"),
        "custom_instructions": (data.get("custom_instructions") or "").strip(),
        "off_topic_response": (data.get("off_topic_response") or "").strip(),
        "welcome_message": (data.get("welcome_message") or "").strip(),
        "is_welcome_message_enabled": data.get("is_welcome_message_enabled", True),
        "is_active": data.get("is_active", True),
    }
    if "verbosity" in data:
        payload["verbosity"] = data["verbosity"]
    res = _request(f"/clients/{client_id}/profiles/", method="POST", data=payload)
    prof_id = (res.get("profile") or {}).get("id") or res.get("id")
    if prof_id and payload.get("off_topic_response"):
        try:
            patch_res = update_profile(client_id, prof_id, {"off_topic_response": payload["off_topic_response"]})
            if patch_res.get("status") == "success" and patch_res.get("profile"):
                res["profile"] = patch_res["profile"]
        except Exception:
            pass
    return res


def update_profile(client_id: int, profile_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    clean_data = dict(data)
    if clean_data.get("dialect") == "modern_standard":
        clean_data["dialect"] = "fusha"
    return _request(f"/clients/{client_id}/profiles/{profile_id}/", method="PATCH", data=clean_data)


def activate_profile(client_id: int, profile_id: int) -> Dict[str, Any]:
    """Activate a specific AI voice profile as current for the client."""
    return _request(f"/clients/{client_id}/profiles/{profile_id}/", method="PATCH", data={"is_active": True})


def delete_profile(client_id: int, profile_id: int) -> Dict[str, Any]:
    """Delete an AI voice profile via DELETE /clients/{client_id}/profiles/{profile_id}/"""
    return _request(f"/clients/{client_id}/profiles/{profile_id}/", method="DELETE")


def get_business_hours(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/business-hours/")


def update_business_hours(client_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/business-hours/", method="PUT", data=data)


def get_documents(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/documents/")


def add_document(client_id: int, title: str, content: str = "", file_url: str = "") -> Dict[str, Any]:
    payload = {
        "title": title.strip(),
        "content": content.strip(),
        "file_url": file_url.strip(),
    }
    return _request(f"/clients/{client_id}/documents/", method="POST", data=payload)


def delete_document(client_id: int, doc_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/documents/?document_id={doc_id}", method="DELETE")


def get_employees(client_id: int) -> Dict[str, Any]:
    resp = _request(f"/clients/{client_id}/employees/")
    emps = resp.get("employees")
    if isinstance(emps, list):
        for emp in emps:
            port = emp.get("sip_port") or 5070
            emp["sip_server_display"] = f"uggu.space:{port}"
            emp["sip_domain"] = "uggu.space"
    return resp


def add_employee(client_id: int, display_name: str, extension: str, department: str = "خدمة العملاء", status: str = "ready", username: str = "", password: str = "") -> Dict[str, Any]:
    payload = {
        "display_name": display_name.strip(),
        "extension": str(extension).strip(),
        "department": department.strip(),
        "status": status.strip(),
    }
    if username:
        payload["username"] = username.strip()
    if password:
        payload["password"] = password.strip()
    resp = _request(f"/clients/{client_id}/employees/", method="POST", data=payload)
    emp = resp.get("employee")
    if emp and isinstance(emp, dict):
        port = emp.get("sip_port") or 5070
        emp["sip_server_display"] = f"uggu.space:{port}"
        emp["sip_domain"] = "uggu.space"
    return resp


def delete_employee(client_id: int, employee_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/employees/{employee_id}/", method="DELETE")


def get_employee(client_id: int, employee_id: int) -> Dict[str, Any]:
    """Retrieve full details of an employee including SIP credentials and queue memberships."""
    resp = _request(f"/clients/{client_id}/employees/{employee_id}/")
    emp = resp.get("employee")
    if emp and isinstance(emp, dict):
        # White-label SIP server to domain with port
        port = emp.get("sip_port") or 5070
        emp["sip_server_display"] = f"uggu.space:{port}"
        emp["sip_domain"] = "uggu.space"
    return resp


def update_employee(client_id: int, employee_id: int, **fields) -> Dict[str, Any]:
    """Update employee details or reset password."""
    return _request(f"/clients/{client_id}/employees/{employee_id}/", method="PATCH", data=fields)


def reset_employee_password(client_id: int, employee_id: int, password: Optional[str] = None) -> Dict[str, Any]:
    """Generate and set a new SIP password for an employee."""
    import secrets
    new_password = password.strip() if password else f"Pass_{secrets.token_hex(4)}"
    resp = update_employee(client_id, employee_id, password=new_password)
    if resp.get("status") == "success" and "employee" in resp:
        resp["employee"]["temporary_password"] = new_password
        resp["temporary_password"] = new_password
    return resp


def get_queues(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/queues/")


def add_or_update_queue(client_id: int, name: str, code: str = "200", description: str = "", strategy: str = "round_robin", ring_timeout_seconds: int = 20, total_timeout_seconds: int = 60, fallback_action: str = "ai_assistant") -> Dict[str, Any]:
    strat_clean = strategy.strip() if strategy.strip() in ("round_robin", "ring_all") else "round_robin"
    payload = {
        "name": name.strip(),
        "code": str(code).strip(),
        "description": description.strip(),
        "strategy": strat_clean,
        "ring_timeout_seconds": int(ring_timeout_seconds),
        "total_timeout_seconds": int(total_timeout_seconds),
        "fallback_action": fallback_action.strip(),
    }
    return _request(f"/clients/{client_id}/queues/", method="POST", data=payload)


def update_queue(client_id: int, queue_id: int, **fields) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/queues/{queue_id}/", method="PATCH", data=fields)


def delete_queue(client_id: int, queue_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/queues/{queue_id}/", method="DELETE")


def get_queue_members(client_id: int, queue_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/queues/{queue_id}/members/")


def add_queue_member(client_id: int, queue_id: int, employee_id: int, order: int = 1) -> Dict[str, Any]:
    payload = {
        "action": "add",
        "employee_id": int(employee_id),
        "order": int(order),
    }
    return _request(f"/clients/{client_id}/queues/{queue_id}/members/", method="POST", data=payload)


def remove_queue_member(client_id: int, queue_id: int, employee_id: int) -> Dict[str, Any]:
    payload = {
        "action": "remove",
        "employee_id": int(employee_id),
    }
    return _request(f"/clients/{client_id}/queues/{queue_id}/members/", method="POST", data=payload)


def get_calls(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/calls/")


def get_wallet() -> Dict[str, Any]:
    return _request("/wallet/")


def get_client_mcp_servers(client_id: int) -> Dict[str, Any]:
    """Fetch registered FastMCP servers and cached tools for client."""
    return _request(f"/clients/{client_id}/mcp/")


def create_client_mcp_server(client_id: int, server_url: str, name: str = "خادم أدوات المطعم (FastMCP)", auth_token: str = "", is_active: bool = True, sync_now: bool = True) -> Dict[str, Any]:
    """Register a new external FastMCP SSE tool server for this client."""
    payload = {
        "name": name,
        "server_url": server_url,
        "auth_token": auth_token,
        "is_active": is_active,
        "sync_now": sync_now
    }
    return _request(f"/clients/{client_id}/mcp/", method="POST", data=payload)


def update_client_mcp_server(client_id: int, mcp_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update MCP server details (e.g., server_url, auth_token, is_active)."""
    return _request(f"/clients/{client_id}/mcp/{mcp_id}/", method="PATCH", data=data)


def sync_client_mcp_tools(client_id: int, mcp_id: int) -> Dict[str, Any]:
    """Trigger live SSE synchronization of tools from FastMCP server to Partner PBX."""
    return _request(f"/clients/{client_id}/mcp/{mcp_id}/sync/", method="POST")


# =========================================================================
# Client Live Context (Redis Working Memory / Atomic Overwrite)
# =========================================================================

def get_client_live_context(client_id: int) -> Dict[str, Any]:
    """Fetch current structured live context and Redis cache status for client."""
    return _request(f"/clients/{client_id}/context/")


def update_client_live_context(client_id: int, context_data: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically overwrite structured live context in DB and Redis cache (<2ms)."""
    return _request(f"/clients/{client_id}/context/", method="PUT", data=context_data)


def clear_client_live_context(client_id: int) -> Dict[str, Any]:
    """Clear structured live context from DB and Redis cache."""
    return _request(f"/clients/{client_id}/context/", method="DELETE")


def build_tenant_live_context_payload(tenant) -> Dict[str, Any]:
    """
    Build a comprehensive, clean JSON payload representing restaurant branches,
    delivery coverage, categorized menus with prices, and out-of-stock items.
    """
    from core.models import Branch, MenuItem, DeliveryArea

    branches = []
    for b in Branch.objects.filter(tenant=tenant, status="active"):
        branches.append({
            "id": b.id,
            "name": b.name,
            "city": b.city or "الرياض",
            "phone": b.phone or "",
            "status": "مفتوح",
            "address": b.address or ""
        })

    areas = []
    for a in DeliveryArea.objects.filter(branch__tenant=tenant, is_active=True).select_related("branch"):
        areas.append({
            "id": a.id,
            "zone": a.name,
            "branch_id": a.branch.id if a.branch else None,
            "branch_name": a.branch.name if a.branch else "",
            "fee": float(a.delivery_fee or 0),
            "estimated_time": f"{a.estimated_time_minutes} دقيقة" if a.estimated_time_minutes else "35 دقيقة"
        })

    menu = {}
    for item in MenuItem.objects.filter(tenant=tenant, available=True).order_by("category", "name"):
        cat = item.category or "أطباق عامة"
        if cat not in menu:
            menu[cat] = []
        menu[cat].append({
            "id": item.id,
            "name": item.name,
            "price": float(item.price),
        })

    out_of_stock = list(MenuItem.objects.filter(tenant=tenant, available=False).values_list("name", flat=True))

    return {
        "restaurant_name": tenant.name,
        "branches": branches,
        "delivery_zones": areas,
        "menu": menu,
        "out_of_stock": out_of_stock,
        "policies": {
            "tax_rate": "15% ضريبة القيمة المضافة شاملة بالأسعار",
            "cancellation": "يُسمح بإلغاء الطلب فقط طالما لا يزال جديداً ولم يدخل مرحلة التحضير بالمطبخ",
            "payment_methods": ["الدفع عند الاستلام كاش أو مدى"]
        },
        "system_instruction_for_agent": (
            "استخدم هذه الذاكرة اللحظية (الفروع، المنيو، الأسعار، مناطق التوصيل) للإجابة الفورية المباشرة على "
            "استفسارات العميل دون استدعاء أي أداة MCP للأسئلة المرجعية. "
            "استخدم أدوات MCP فقط عند طلب العميل: البحث عن بياناته السابقة (lookup_customer)، "
            "معاينة الفاتورة قبل التأكيد (preview_order)، إنشاء الطلب النهائي (create_callcenter_order)، "
            "أو تتبع وإلغاء أوردر جاري (track_order / cancel_order)."
        )
    }


def sync_tenant_live_context(tenant, client_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Generate the complete live context payload for the tenant and push it
    atomically to the Partner PBX via PUT /clients/{client_id}/context/.
    """
    if client_id is None:
        client_id = get_client_id_for_tenant(tenant)

    payload = build_tenant_live_context_payload(tenant)
    resp = update_client_live_context(client_id, payload)
    
    # Add summary counts
    resp["items_count"] = sum(len(v) for v in payload.get("menu", {}).values())
    resp["branches_count"] = len(payload.get("branches", []))
    resp["zones_count"] = len(payload.get("delivery_zones", []))
    resp["out_of_stock_count"] = len(payload.get("out_of_stock", []))
    return resp


# =========================================================================
# Outbound AI Calling & Dialing API
# =========================================================================

def dial_outbound_call(client_id: int, phone_number: str, call_goal: str = "", customer_name: str = "") -> Dict[str, Any]:
    """Trigger an autonomous outbound AI call to customer (e.g. order confirmation or feedback)."""
    payload = {
        "phone_number": str(phone_number).strip(),
        "call_goal": str(call_goal).strip(),
        "customer_name": str(customer_name).strip(),
    }
    return _request(f"/clients/{client_id}/calls/dial/", method="POST", data=payload)


# =========================================================================
# WhatsApp & Omnichannel Partner API
# =========================================================================

def get_whatsapp_status(client_id: int) -> Dict[str, Any]:
    """Fetch live WhatsApp Baileys connection status for sub-client."""
    return _request(f"/clients/{client_id}/whatsapp/status/")


def get_whatsapp_qr(client_id: int) -> Dict[str, Any]:
    """Fetch QR code for pairing restaurant WhatsApp instance."""
    return _request(f"/clients/{client_id}/whatsapp/connect/", method="POST")


def disconnect_whatsapp(client_id: int) -> Dict[str, Any]:
    """Disconnect restaurant WhatsApp session."""
    return _request(f"/clients/{client_id}/whatsapp/disconnect/", method="POST")


def send_whatsapp_message(client_id: int, phone_number: str, message: str) -> Dict[str, Any]:
    """Send WhatsApp message/invoice/tracking link to customer."""
    payload = {
        "phone_number": str(phone_number).strip(),
        "message": str(message).strip(),
    }
    return _request(f"/clients/{client_id}/whatsapp/send/", method="POST", data=payload)


def get_whatsapp_conversations(client_id: int, query: str = "", page: int = 1, page_size: int = 30) -> Dict[str, Any]:
    """Fetch omnichannel WhatsApp conversation list for client."""
    params = []
    if query:
        params.append(f"q={urllib.parse.quote(query)}")
    if page > 1:
        params.append(f"page={page}")
    if page_size != 30:
        params.append(f"page_size={page_size}")
    qs = f"?{'&'.join(params)}" if params else ""
    return _request(f"/clients/{client_id}/whatsapp/conversations/{qs}")


def get_whatsapp_conversation_messages(client_id: int, phone: str, limit: int = 50) -> Dict[str, Any]:
    """Fetch message history for specific customer phone conversation."""
    clean_phone = urllib.parse.quote(str(phone).strip())
    return _request(f"/clients/{client_id}/whatsapp/conversations/{clean_phone}/messages/?limit={limit}")


def reply_whatsapp_conversation(client_id: int, phone: str, message: str) -> Dict[str, Any]:
    """Send human cashier reply to customer on WhatsApp."""
    clean_phone = urllib.parse.quote(str(phone).strip())
    payload = {"message": str(message).strip()}
    return _request(f"/clients/{client_id}/whatsapp/conversations/{clean_phone}/reply/", method="POST", data=payload)


def toggle_whatsapp_conversation_ai(client_id: int, phone: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
    """Toggle AI auto-reply for customer conversation."""
    clean_phone = urllib.parse.quote(str(phone).strip())
    payload = {}
    if enabled is not None:
        payload["ai_active"] = bool(enabled)
    return _request(f"/clients/{client_id}/whatsapp/conversations/{clean_phone}/toggle-ai/", method="POST", data=payload)


def trigger_whatsapp_followup(client_id: int, phone: str, customer_name: str = "", trigger_type: str = "manual_followup") -> Dict[str, Any]:
    """Trigger an automated WhatsApp post-call follow-up message."""
    payload = {
        "phone": str(phone).strip(),
        "customer_name": str(customer_name).strip(),
        "trigger_type": str(trigger_type).strip(),
    }
    return _request(f"/clients/{client_id}/whatsapp/followup/", method="POST", data=payload)


def sync_whatsapp_chats(client_id: int, clean_old: bool = False, max_messages: int = 40) -> Dict[str, Any]:
    """Sync all genuine WhatsApp chats and messages directly from phone/evolution_db."""
    payload = {
        "clean_old": bool(clean_old),
        "max_messages": int(max_messages),
    }
    return _request(f"/clients/{client_id}/whatsapp/sync/", method="POST", data=payload)


# =========================================================================
# Telephony DID Numbers & PBX Trunks API
# =========================================================================

def get_telephony_numbers(client_id: int) -> Dict[str, Any]:
    """Fetch assigned direct inward dialing (DID) numbers for sub-client."""
    return _request(f"/clients/{client_id}/telephony/numbers/")


def get_pbx_trunks(client_id: int) -> Dict[str, Any]:
    """Fetch SIP trunks and PBX routing configurations for sub-client."""
    return _request(f"/clients/{client_id}/telephony/pbx-trunks/")



