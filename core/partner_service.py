import urllib.request
import urllib.parse
import json
import ssl
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

PARTNER_API_BASE_URL = "https://app.169.58.32.179.nip.io/api/partner/v1"
PARTNER_API_KEY = "sk_live_prt_RwTTVvzpzrGbWRmxklS8BC3qm_3djMVxxD1UVom0cfA"

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
        with urllib.request.urlopen(req, timeout=10.0, context=_SSL_CONTEXT) as response:
            resp_body = response.read().decode("utf-8")
            return json.loads(resp_body)
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8", errors="ignore")
        logger.error(f"Partner API HTTPError [{e.code}] on {method} {path}: {error_msg}")
        try:
            return json.loads(error_msg)
        except Exception:
            return {"status": "error", "code": e.code, "message": error_msg}
    except Exception as ex:
        logger.error(f"Partner API Request Exception on {method} {path}: {ex}", exc_info=True)
        return {"status": "error", "message": str(ex)}


def get_client_id_for_tenant(tenant) -> int:
    """Return mapped partner client_id for given restaurant tenant."""
    if tenant and getattr(tenant, "voice_client_id", None):
        return tenant.voice_client_id
    return 49


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

    # Register sub-client on the partner platform
    res = register_sub_client(
        name=tenant.name,
        external_reference=tenant.slug,
        email=tenant.email,
        password=password or tenant.voice_password or "",
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


def update_profile(client_id: int, profile_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/profiles/{profile_id}/", method="PATCH", data=data)


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
    return _request(f"/clients/{client_id}/documents/{doc_id}/", method="DELETE")


def get_employees(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/employees/")


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
    return _request(f"/clients/{client_id}/employees/", method="POST", data=payload)


def delete_employee(client_id: int, employee_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/employees/{employee_id}/", method="DELETE")


def get_queues(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/queues/")


def add_or_update_queue(client_id: int, name: str, code: str = "200", strategy: str = "least_recent", ring_timeout_seconds: int = 20, total_timeout_seconds: int = 60, fallback_action: str = "ai_assistant") -> Dict[str, Any]:
    payload = {
        "name": name.strip(),
        "code": str(code).strip(),
        "strategy": strategy.strip(),
        "ring_timeout_seconds": int(ring_timeout_seconds),
        "total_timeout_seconds": int(total_timeout_seconds),
        "fallback_action": fallback_action.strip(),
    }
    return _request(f"/clients/{client_id}/queues/", method="POST", data=payload)


def delete_queue(client_id: int, queue_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/queues/{queue_id}/", method="DELETE")


def get_calls(client_id: int) -> Dict[str, Any]:
    return _request(f"/clients/{client_id}/calls/")


def get_wallet() -> Dict[str, Any]:
    return _request("/wallet/")
