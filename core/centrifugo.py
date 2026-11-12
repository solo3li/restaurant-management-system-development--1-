"""
Centrifugo Real-Time Messaging Client & Token Generator
-------------------------------------------------------
Provides high-performance, decoupled real-time pub/sub capabilities for Motaem Cloud OS:
- HMAC SHA-256 Connection JWT generation (Centrifugo v5)
- HMAC SHA-256 Channel Subscription JWT generation
- Resilient HTTP publish_event with automatic reachability detection & fallback
- Multi-tenant channel naming helpers
"""
import os
import time
import json
import logging
from typing import Optional, Dict, Any
import requests
from django.conf import settings
import jwt

logger = logging.getLogger(__name__)


def get_centrifugo_api_url() -> str:
    """Returns the configured Centrifugo HTTP API URL."""
    if settings.configured:
        val = getattr(settings, "CENTRIFUGO_API_URL", None)
        if val:
            return val
    return os.getenv("CENTRIFUGO_API_URL", "http://centrifugo:8000/api")


def get_centrifugo_api_key() -> str:
    """Returns the configured Centrifugo HTTP API key."""
    if settings.configured:
        val = getattr(settings, "CENTRIFUGO_API_KEY", None)
        if val:
            return val
    return os.getenv("CENTRIFUGO_API_KEY", "motaem-centrifugo-api-key-2026-very-secure")


def get_centrifugo_hmac_secret() -> str:
    """Returns the HMAC SHA-256 secret key for signing JWTs."""
    if settings.configured:
        val = getattr(settings, "CENTRIFUGO_HMAC_SECRET", None)
        if val:
            return val
    return os.getenv("CENTRIFUGO_HMAC_SECRET", "motaem-cloud-centrifugo-hmac-secret-key-32chars-min-secure-2026")


def get_centrifugo_ws_url() -> str:
    """Returns WebSocket connection path."""
    if settings.configured:
        val = getattr(settings, "CENTRIFUGO_WS_URL", None)
        if val:
            return val
    return os.getenv("CENTRIFUGO_WS_URL", "/connection/websocket")


def generate_connection_token(
    user_id: Any,
    exp_seconds: int = 86400,
    info: Optional[Dict[str, Any]] = None,
    secret: Optional[str] = None
) -> str:
    """
    Generates a Centrifugo v5 connection JWT signed with HMAC SHA-256.
    Payload:
      - sub: user ID (string)
      - exp: expiration timestamp
      - iat: issued at timestamp
      - info (optional): user connection metadata
    """
    key = secret or get_centrifugo_hmac_secret()
    now = int(time.time())
    payload = {
        "sub": str(user_id) if user_id is not None else "",
        "exp": now + exp_seconds,
        "iat": now,
    }
    if info:
        payload["info"] = info

    return jwt.encode(payload, key, algorithm="HS256")


def generate_subscription_token(
    user_id: Any,
    channel: str,
    exp_seconds: int = 86400,
    info: Optional[Dict[str, Any]] = None,
    secret: Optional[str] = None
) -> str:
    """
    Generates a Centrifugo v5 channel subscription JWT signed with HMAC SHA-256.
    Payload:
      - sub: user ID (string, must match connection token)
      - channel: target channel name (e.g. 'kds:tenant_1_branch_2')
      - exp: expiration timestamp
      - iat: issued at timestamp
      - info (optional): channel membership metadata
    """
    key = secret or get_centrifugo_hmac_secret()
    now = int(time.time())
    payload = {
        "sub": str(user_id) if user_id is not None else "",
        "channel": str(channel),
        "exp": now + exp_seconds,
        "iat": now,
    }
    if info:
        payload["info"] = info

    return jwt.encode(payload, key, algorithm="HS256")


def publish_event(
    channel: str,
    data: Dict[str, Any],
    timeout: float = 1.0,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None
) -> bool:
    """
    Publish an event to a Centrifugo channel via HTTP API.
    Sends POST {"method": "publish", "params": {"channel": ..., "data": ...}}.
    Includes automatic fallback to host port (127.0.0.1:9300) when running outside docker.
    Gracefully catches any connection errors / offline container without raising exceptions.
    """
    target_api_url = api_url or get_centrifugo_api_url()
    target_api_key = api_key or get_centrifugo_api_key()

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": target_api_key,
    }
    payload = {
        "method": "publish",
        "params": {
            "channel": channel,
            "data": data,
        }
    }

    # If running outside container, resolve docker internal host to local loopback port
    candidate_urls = [target_api_url]
    if "centrifugo:8000" in target_api_url:
        candidate_urls.append(target_api_url.replace("centrifugo:8000", "127.0.0.1:9300"))
    elif "localhost:8000" in target_api_url or "127.0.0.1:8000" in target_api_url:
        candidate_urls.append("http://127.0.0.1:9300/api")

    for url in candidate_urls:
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                body = resp.json()
                if "error" in body and body["error"]:
                    logger.warning("Centrifugo API error publishing to %s via %s: %s", channel, url, body["error"])
                    return False
                return True
            else:
                logger.warning("Centrifugo API HTTP %s for %s via %s: %s", resp.status_code, channel, url, resp.text)
        except (requests.exceptions.RequestException, OSError) as e:
            logger.debug("Centrifugo unreachable at %s: %s", url, e)
            continue
        except Exception as e:
            logger.warning("Unexpected error publishing to Centrifugo at %s: %s", url, e)
            continue

    logger.warning("Centrifugo offline or unreachable; skipping real-time event for channel '%s'", channel)
    return False


def build_kds_channel(tenant_id: int, branch_id: Optional[int] = None) -> str:
    """Builds standard KDS channel string."""
    if branch_id:
        return f"kds:tenant_{tenant_id}_branch_{branch_id}"
    return f"kds:tenant_{tenant_id}_all"


def build_delivery_channel(tenant_id: int, branch_id: Optional[int] = None) -> str:
    """Builds standard Delivery channel string."""
    if branch_id:
        return f"delivery:tenant_{tenant_id}_branch_{branch_id}"
    return f"delivery:tenant_{tenant_id}_all"


def build_pos_channel(tenant_id: int, branch_id: Optional[int] = None) -> str:
    """Builds standard POS channel string."""
    if branch_id:
        return f"pos:tenant_{tenant_id}_branch_{branch_id}"
    return f"pos:tenant_{tenant_id}_all"


def build_callcenter_channel(tenant_id: int) -> str:
    """Builds standard Call Center channel string."""
    return f"callcenter:tenant_{tenant_id}"
