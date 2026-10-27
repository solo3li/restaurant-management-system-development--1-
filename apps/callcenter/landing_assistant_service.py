"""
Landing Assistant Service:
Provides isolated partner client management, live Redis context synchronization,
and knowledge base synchronization for the Platform Voice Assistant.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Optional
from django.utils import timezone
from django.core.cache import cache

from apps.callcenter.models import PlatformVoiceAssistantConfig, LandingKnowledgeDocument, LandingVoiceLead
from core import partner_service as ps

logger = logging.getLogger(__name__)

LANDING_SALES_CLIENT_NAME = "Landing-Sales-Client"
LANDING_SALES_EXTERNAL_REF = "landing-sales-client"
REDIS_LIVE_CONTEXT_KEY = "landing_assistant:live_context"
REDIS_LAST_SYNCED_KEY = "landing_assistant:last_synced_at"


def get_redis_client():
    """Return configured Redis client or None if unreachable."""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        client = redis.from_url(redis_url, socket_timeout=2)
        client.ping()
        return client
    except Exception as e:
        logger.debug(f"Redis not reachable directly: {e}")
        return None


def ensure_landing_sales_client(config: Optional[PlatformVoiceAssistantConfig] = None) -> Dict[str, Any]:
    """
    Ensure dedicated isolated client account exists on Partner Service named 'Landing-Sales-Client'
    and bound to config.partner_client_id.
    """
    if config is None:
        config = PlatformVoiceAssistantConfig.get_config()

    try:
        # Check existing clients on Partner Service
        list_resp = ps._request("/clients/")
        clients_list = []
        if isinstance(list_resp, list):
            clients_list = list_resp
        elif isinstance(list_resp, dict):
            clients_list = list_resp.get("clients") or []

        for c in clients_list:
            if not isinstance(c, dict):
                continue
            if c.get("name") == LANDING_SALES_CLIENT_NAME or c.get("external_reference") == LANDING_SALES_EXTERNAL_REF:
                cid = str(c.get("client_id") or c.get("id"))
                if config.partner_client_id != cid:
                    config.partner_client_id = cid
                    config.save(update_fields=["partner_client_id", "updated_at"])
                return {
                    "status": "success",
                    "client_id": cid,
                    "client_name": LANDING_SALES_CLIENT_NAME,
                    "action": "linked_existing",
                    "details": c,
                }

        # If not found, register new client
        reg_resp = ps.register_sub_client(
            name=LANDING_SALES_CLIENT_NAME,
            external_reference=LANDING_SALES_EXTERNAL_REF,
            email="landing-sales@motaem.local",
            spending_cap=100.0,
            minute_cap=1000,
        )
        if isinstance(reg_resp, dict) and reg_resp.get("status") == "success":
            client_dict = reg_resp.get("client") if isinstance(reg_resp.get("client"), dict) else {}
            cid = str(reg_resp.get("client_id") or client_dict.get("client_id") or client_dict.get("id") or "")
            if cid:
                config.partner_client_id = cid
                config.save(update_fields=["partner_client_id", "updated_at"])
                return {
                    "status": "success",
                    "client_id": cid,
                    "client_name": LANDING_SALES_CLIENT_NAME,
                    "action": "registered_new",
                    "details": reg_resp,
                }
    except Exception as e:
        logger.warning(f"Error checking/registering Landing-Sales-Client: {e}")

    # Fallback to current config ID or default '49'
    if not config.partner_client_id:
        config.partner_client_id = "49"
        config.save(update_fields=["partner_client_id", "updated_at"])

    return {
        "status": "success",
        "client_id": config.partner_client_id,
        "client_name": LANDING_SALES_CLIENT_NAME,
        "action": "fallback",
    }


def sync_knowledge_doc_to_partner(doc: LandingKnowledgeDocument, action: str = "add") -> Dict[str, Any]:
    """
    Sync a LandingKnowledgeDocument to central Partner Service (add, update, or delete).
    """
    config = doc.config
    try:
        client_id = int(config.partner_client_id or 49)
    except (ValueError, TypeError):
        client_id = 49

    if action == "add":
        content_to_send = doc.content
        if not content_to_send and doc.file:
            content_to_send = f"Uploaded knowledge document: {doc.title} ({doc.file_type})"

        file_url = ""
        if doc.file and hasattr(doc.file, "url"):
            raw_url = str(doc.file.url or "")
            if raw_url.startswith("http://") or raw_url.startswith("https://"):
                file_url = raw_url
            elif raw_url.startswith("/"):
                file_url = f"https://uggu.space{raw_url}"

        resp = ps.add_document(
            client_id=client_id,
            title=doc.title,
            content=content_to_send or doc.title,
            file_url=file_url,
        )
        if resp.get("status") == "success":
            doc_id = resp.get("document_id") or (resp.get("document") or {}).get("id")
            if doc_id:
                doc.partner_doc_id = doc_id
                doc.save(update_fields=["partner_doc_id", "updated_at"])
        return resp

    elif action == "update":
        if doc.partner_doc_id:
            try:
                ps.delete_document(client_id=client_id, doc_id=doc.partner_doc_id)
            except Exception as e:
                logger.warning(f"Failed deleting old doc #{doc.partner_doc_id} on partner: {e}")

        content_to_send = doc.content or doc.title
        file_url = ""
        if doc.file and hasattr(doc.file, "url"):
            raw_url = str(doc.file.url or "")
            if raw_url.startswith("http://") or raw_url.startswith("https://"):
                file_url = raw_url
            elif raw_url.startswith("/"):
                file_url = f"https://uggu.space{raw_url}"

        resp = ps.add_document(
            client_id=client_id,
            title=doc.title,
            content=content_to_send,
            file_url=file_url,
        )
        if resp.get("status") == "success":
            new_id = resp.get("document_id") or (resp.get("document") or {}).get("id")
            if new_id:
                doc.partner_doc_id = new_id
                doc.save(update_fields=["partner_doc_id", "updated_at"])
        return resp

    elif action == "delete":
        if doc.partner_doc_id:
            return ps.delete_document(client_id=client_id, doc_id=doc.partner_doc_id)
        return {"status": "success", "message": "No partner_doc_id to delete"}

    return {"status": "error", "message": f"Unknown action: {action}"}


def build_landing_assistant_live_context(config: Optional[PlatformVoiceAssistantConfig] = None) -> Dict[str, Any]:
    """
    Compile rich, structured live context for the Landing Voice Assistant.
    Combines Assistant identity, Isolated Knowledge Base documents & FAQs,
    Platform Subscription Plans, and Visitor Stats.
    """
    from apps.billing.models import SubscriptionPlan

    if config is None:
        config = PlatformVoiceAssistantConfig.get_config()

    # 1. Documents & FAQs
    docs = []
    for d in config.knowledge_documents.all():
        docs.append({
            "id": d.id,
            "title": d.title,
            "source_type": d.source_type,
            "file_type": d.file_type,
            "file_size": d.file_size,
            "content": d.content,
            "partner_doc_id": d.partner_doc_id,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M:%S") if d.created_at else "",
        })

    # 2. Subscription Plans
    plans = []
    for p in SubscriptionPlan.objects.filter(is_active=True).order_by("ordering", "price_monthly"):
        plans.append({
            "code": p.code,
            "name": p.name,
            "description": p.description,
            "price_monthly": float(p.price_monthly),
            "price_yearly": float(p.price_yearly),
            "features": p.features,
            "max_branches": p.max_branches,
            "max_employees": p.max_employees,
            "trial_days": p.trial_days,
            "is_popular": p.is_popular,
        })

    # 3. Quick Stats
    leads_count = LandingVoiceLead.objects.count()
    connected_calls = LandingVoiceLead.objects.filter(call_status__in=["connected", "completed"]).count()

    context_payload = {
        "platform_name": "منظومة كُـورَا (KURA Cloud Restaurant OS)",
        "assistant": {
            "name": config.assistant_name,
            "is_active": config.is_active,
            "voice_name": config.voice_name,
            "language": config.language,
            "accent": config.accent,
            "system_prompt": config.system_prompt,
            "welcome_message": config.welcome_message,
            "max_call_duration_seconds": config.max_call_duration_seconds,
            "max_daily_calls_per_ip": config.max_daily_calls_per_ip,
            "partner_client_id": config.partner_client_id,
        },
        "knowledge_documents": docs,
        "subscription_plans": plans,
        "system_kpis": {
            "total_landing_leads": leads_count,
            "connected_voice_calls": connected_calls,
        },
        "synced_at": timezone.now().isoformat(),
    }
    return context_payload


def sync_landing_assistant_live_context(config: Optional[PlatformVoiceAssistantConfig] = None) -> Dict[str, Any]:
    """
    Compile and atomically push smart live context into:
    1. Redis Cache
    2. Django DB Cache
    3. Central Partner Telephony Service (PUT /clients/{partner_client_id}/context/)
    """
    if config is None:
        config = PlatformVoiceAssistantConfig.get_config()

    context_payload = build_landing_assistant_live_context(config)
    now_iso = context_payload["synced_at"]
    payload_json = json.dumps(context_payload, ensure_ascii=False, indent=2)
    payload_bytes = len(payload_json.encode("utf-8"))

    # 1. Direct Redis Sync
    r = get_redis_client()
    redis_keys_count = 1
    redis_connected = False
    if r:
        try:
            r.set(REDIS_LIVE_CONTEXT_KEY, payload_json)
            r.set(REDIS_LAST_SYNCED_KEY, now_iso)
            r.set(f"{REDIS_LIVE_CONTEXT_KEY}:size_bytes", payload_bytes)
            # Count keys matching landing_assistant:*
            redis_keys = r.keys("landing_assistant:*")
            redis_keys_count = len(redis_keys) if redis_keys else 1
            redis_connected = True
        except Exception as e:
            logger.warning(f"Direct Redis set error: {e}")

    # 2. Django Cache Sync (Always fallback safe)
    cache.set(REDIS_LIVE_CONTEXT_KEY, payload_json, timeout=None)
    cache.set(REDIS_LAST_SYNCED_KEY, now_iso, timeout=None)
    cache.set(f"{REDIS_LIVE_CONTEXT_KEY}:size_bytes", payload_bytes, timeout=None)
    cache.set(f"{REDIS_LIVE_CONTEXT_KEY}:keys_count", redis_keys_count, timeout=None)

    # 3. Central Partner Service Sync
    partner_resp = {}
    try:
        cid = int(config.partner_client_id or 49)
        partner_resp = ps.update_client_live_context(cid, context_payload)
    except Exception as e:
        logger.warning(f"Partner context sync error: {e}")
        partner_resp = {"status": "error", "message": str(e)}

    return {
        "status": "success",
        "redis_connected": redis_connected,
        "synced_at": now_iso,
        "size_bytes": payload_bytes,
        "size_formatted": f"{payload_bytes / 1024:.2f} KB" if payload_bytes >= 1024 else f"{payload_bytes} B",
        "keys_count": redis_keys_count,
        "context": context_payload,
        "partner_sync": partner_resp,
    }


def get_landing_assistant_redis_status(config: Optional[PlatformVoiceAssistantConfig] = None) -> Dict[str, Any]:
    """
    Inspect live memory cache metrics and content from Redis / Django Cache.
    """
    if config is None:
        config = PlatformVoiceAssistantConfig.get_config()

    r = get_redis_client()
    redis_connected = bool(r)

    raw_json = None
    last_synced = None
    keys_count = 0
    size_bytes = 0

    if r:
        try:
            val = r.get(REDIS_LIVE_CONTEXT_KEY)
            if val:
                raw_json = val.decode("utf-8") if isinstance(val, bytes) else str(val)
            ls = r.get(REDIS_LAST_SYNCED_KEY)
            if ls:
                last_synced = ls.decode("utf-8") if isinstance(ls, bytes) else str(ls)
            keys = r.keys("landing_assistant:*")
            keys_count = len(keys) if keys else 0
            if raw_json:
                size_bytes = len(raw_json.encode("utf-8"))
        except Exception as e:
            logger.debug(f"Redis get error: {e}")

    # Fallback to Django Cache
    if not raw_json:
        raw_json = cache.get(REDIS_LIVE_CONTEXT_KEY)
    if not last_synced:
        last_synced = cache.get(REDIS_LAST_SYNCED_KEY)
    if not keys_count:
        keys_count = cache.get(f"{REDIS_LIVE_CONTEXT_KEY}:keys_count") or (1 if raw_json else 0)
    if not size_bytes and raw_json:
        size_bytes = len(raw_json.encode("utf-8"))

    # If never synced yet, auto-generate default
    if not raw_json:
        ctx = build_landing_assistant_live_context(config)
        raw_json = json.dumps(ctx, ensure_ascii=False, indent=2)
        size_bytes = len(raw_json.encode("utf-8"))
        last_synced = "لم تتم المزامنة بعد"
        keys_count = 1
    else:
        try:
            ctx = json.loads(raw_json)
        except Exception:
            ctx = {}

    size_formatted = f"{size_bytes / 1024:.2f} KB" if size_bytes >= 1024 else f"{size_bytes} B"

    return {
        "status": "success",
        "redis_connected": redis_connected,
        "redis_host": "127.0.0.1:6379" if redis_connected else "Django Database Cache",
        "size_bytes": size_bytes,
        "size_formatted": size_formatted,
        "keys_count": keys_count,
        "last_synced_at": last_synced or "لم تتم المزامنة بعد",
        "context": ctx,
        "raw_json": raw_json,
    }
