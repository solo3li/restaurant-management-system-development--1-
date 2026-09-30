"""
Kitchen Real-Time SSE (Server-Sent Events) Broadcaster & Serializer for KDS.
Handles true push event-driven updates for kitchen displays with zero polling latency.
"""
import asyncio
import json
import logging
from typing import Dict, Set, Optional, Any
from django.utils import timezone

logger = logging.getLogger(__name__)


def serialize_kitchen_order(order) -> Dict[str, Any]:
    """
    Serializes an Order model instance with its items and categories for the Kitchen Display.
    """
    now = timezone.now()
    created_at = order.created_at or now
    elapsed_minutes = max(0, int((now - created_at).total_seconds() // 60))

    items_data = []
    categories = set()

    for item in order.items.all().select_related("menu_item"):
        cat = "عام"
        emoji = "🍽️"
        if item.menu_item and item.menu_item.category:
            cat = item.menu_item.category
            emoji = item.menu_item.emoji or emoji

        categories.add(cat)
        items_data.append({
            "id": item.id,
            "name": item.name,
            "qty": item.qty,
            "price": float(item.price),
            "category": cat,
            "emoji": emoji,
        })

    return {
        "id": order.id,
        "order_number": order.order_number,
        "order_type": order.order_type,
        "order_type_display": order.get_order_type_display(),
        "channel": order.channel,
        "status": order.status,
        "status_display": order.get_status_display(),
        "customer_name": order.customer_name or "عميل نقدي",
        "customer_phone": order.customer_phone or "",
        "address": order.address or "",
        "notes": order.notes or "",
        "created_at_iso": created_at.isoformat(),
        "created_at_time": created_at.strftime("%H:%M"),
        "elapsed_minutes": elapsed_minutes,
        "branch_id": order.branch_id,
        "branch_name": order.branch.name if order.branch else "الفرع الرئيسي",
        "tenant_id": order.tenant_id,
        "items": items_data,
        "categories": sorted(list(categories)),
        "total_items_count": sum(it["qty"] for it in items_data),
    }


class KitchenEventBroadcaster:
    """
    In-memory async Pub/Sub event broadcaster for Server-Sent Events.
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
        """Registers a new listener queue for an SSE client."""
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
            logger.info("Registered kitchen SSE client for tenant=%s, branch=%s (total: %s)",
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
            logger.info("Unregistered kitchen SSE client")

    def broadcast(self, tenant_id: int, event_type: str, data: Dict[str, Any], branch_id: Optional[int] = None):
        """
        Broadcasts an event payload to all active listener queues for the given tenant/branch.
        Thread-safe: can be called from synchronous Django views or async context.
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
            # If the client is scoped to a specific branch and this event is for another branch, skip
            target_branch = meta.get("branch_id")
            if target_branch and branch_id and target_branch != branch_id:
                continue

            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Discard oldest to make room
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass
            except Exception as e:
                logger.warning("Error putting event to kitchen queue: %s", e)


# Global singleton broadcaster instance
kitchen_broadcaster = KitchenEventBroadcaster()


def notify_kitchen_order_event(order, event_type: str):
    """
    Convenience helper function to notify the kitchen broadcaster of order events.
    event_type: 'new_order' | 'order_updated' | 'order_status_changed' | 'order_cancelled'
    """
    try:
        data = serialize_kitchen_order(order)
        kitchen_broadcaster.broadcast(
            tenant_id=order.tenant_id,
            event_type=event_type,
            data=data,
            branch_id=order.branch_id,
        )
    except Exception as e:
        logger.error("Failed to broadcast kitchen order event: %s", e)
