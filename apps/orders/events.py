"""
Delivery Real-Time SSE (Server-Sent Events) Broadcaster & Serializer.
Handles live push event-driven updates for the Delivery Management & Dispatch Screen.
"""
import asyncio
import json
import logging
from typing import Dict, Set, Optional, Any
from django.utils import timezone

logger = logging.getLogger(__name__)


def serialize_delivery_order(order) -> Dict[str, Any]:
    """
    Serializes a delivery Order instance with items, customer, driver, and financials.
    """
    now = timezone.now()
    created_at = order.created_at or now
    elapsed_minutes = max(0, int((now - created_at).total_seconds() // 60))

    items_data = []
    for item in order.items.all().select_related("menu_item"):
        items_data.append({
            "id": item.id,
            "name": item.name,
            "qty": item.qty,
            "price": float(item.price),
            "notes": item.notes or "",
        })

    driver_info = None
    if order.driver:
        driver_info = {
            "id": order.driver.id,
            "name": order.driver.name,
            "phone": order.driver.phone or "",
        }

    area_name = order.delivery_area.name if order.delivery_area else ""

    return {
        "id": order.id,
        "order_number": order.order_number,
        "order_type": order.order_type,
        "order_type_display": order.get_order_type_display(),
        "channel": order.channel,
        "channel_display": order.get_channel_display(),
        "status": order.status,
        "status_display": order.get_status_display(),
        "customer_name": order.customer_name or "عميل نقدي",
        "customer_phone": order.customer_phone or "",
        "address": order.address or "",
        "delivery_area": area_name,
        "driver": driver_info,
        "driver_id": order.driver_id,
        "driver_name": order.driver.name if order.driver else "",
        "pay_method": order.pay_method,
        "pay_method_display": order.get_pay_method_display(),
        "paid": order.paid,
        "subtotal": float(order.subtotal or 0),
        "delivery_fee": float(order.delivery_fee or 0),
        "discount": float(order.discount or 0),
        "tax": float(order.tax or 0),
        "total": float(order.total or 0),
        "notes": order.notes or "",
        "created_at_iso": created_at.isoformat(),
        "created_at_time": created_at.strftime("%H:%M"),
        "elapsed_minutes": elapsed_minutes,
        "branch_id": order.branch_id,
        "branch_name": order.branch.name if order.branch else "الفرع الرئيسي",
        "tenant_id": order.tenant_id,
        "items": items_data,
        "items_count": sum(it["qty"] for it in items_data),
    }


class DeliveryEventBroadcaster:
    """
    In-memory async Pub/Sub event broadcaster for Delivery Server-Sent Events.
    Maintains subscriber queues per tenant and branch.
    """
    def __init__(self):
        # tenant_id -> Set of asyncio.Queue
        self._subscribers: Dict[int, Set[asyncio.Queue]] = {}
        # queue -> dict with metadata (tenant_id, branch_id)
        self._queue_meta: Dict[asyncio.Queue, Dict[str, Any]] = {}
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def register(self, tenant_id: int, branch_id: Optional[int] = None) -> asyncio.Queue:
        """Registers a new listener queue for a delivery SSE client."""
        lock = self._get_lock()
        async with lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=100)
            if tenant_id not in self._subscribers:
                self._subscribers[tenant_id] = set()
            self._subscribers[tenant_id].add(queue)
            self._queue_meta[queue] = {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
            }
            logger.info("Registered delivery SSE client for tenant=%s, branch=%s (total: %s)",
                        tenant_id, branch_id, len(self._subscribers[tenant_id]))
            return queue

    async def unregister(self, queue: asyncio.Queue):
        """Unregisters and removes a listener queue."""
        lock = self._get_lock()
        async with lock:
            meta = self._queue_meta.pop(queue, None)
            if meta:
                tenant_id = meta["tenant_id"]
                if tenant_id in self._subscribers:
                    self._subscribers[tenant_id].discard(queue)
                    if not self._subscribers[tenant_id]:
                        del self._subscribers[tenant_id]
            logger.info("Unregistered delivery SSE client")

    @staticmethod
    def _safe_put(q: asyncio.Queue, payload: Dict[str, Any]):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                pass
        except Exception:
            pass

    def broadcast(self, tenant_id: int, event_type: str, data: Dict[str, Any], branch_id: Optional[int] = None):
        """
        Broadcasts a delivery event payload to all active listener queues for the given tenant/branch.
        Thread-safe: can be called from synchronous Django views or async contexts.
        """
        payload = {
            "type": event_type,
            "data": data,
            "timestamp": timezone.now().isoformat(),
        }

        queues_for_tenant = list(self._subscribers.get(tenant_id, []))
        if not queues_for_tenant:
            return

        for q in queues_for_tenant:
            meta = self._queue_meta.get(q, {})
            target_branch = meta.get("branch_id")
            if target_branch and branch_id and target_branch != branch_id:
                continue

            loop = getattr(q, "_loop", None)
            if loop and loop.is_running():
                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_loop = None

                if current_loop is loop:
                    self._safe_put(q, payload)
                else:
                    loop.call_soon_threadsafe(self._safe_put, q, payload)
            else:
                self._safe_put(q, payload)


# Global singleton broadcaster instance for delivery
delivery_broadcaster = DeliveryEventBroadcaster()


def notify_delivery_order_event(order, event_type: str):
    """
    Helper function to broadcast order events to the delivery screen.
    Only orders with order_type == 'delivery' are dispatched to the delivery stream.
    event_type: 'delivery_new_order' | 'delivery_status_changed' | 'delivery_driver_assigned' | 'delivery_order_cancelled'
    """
    if not order or getattr(order, "order_type", "") != "delivery":
        return

    def _sync_serialize_and_broadcast():
        try:
            data = serialize_delivery_order(order)
            delivery_broadcaster.broadcast(
                tenant_id=order.tenant_id,
                event_type=event_type,
                data=data,
                branch_id=order.branch_id,
            )
        except Exception as e:
            logger.error("Failed to broadcast delivery order event: %s", e)

    try:
        # Check if running in an active event loop thread
        asyncio.get_running_loop()
        import threading
        t = threading.Thread(target=_sync_serialize_and_broadcast)
        t.start()
        t.join(timeout=5.0)
    except RuntimeError:
        # Normal synchronous execution
        _sync_serialize_and_broadcast()
