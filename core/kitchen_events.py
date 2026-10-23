"""
Core Kitchen Events Facade.
Re-exported from apps.kitchen.events for 100% backward compatibility.
"""
from apps.kitchen.events import (
    KitchenEventBroadcaster,
    kitchen_broadcaster,
    serialize_kitchen_order,
    notify_kitchen_order_event,
)

__all__ = [
    "KitchenEventBroadcaster",
    "kitchen_broadcaster",
    "serialize_kitchen_order",
    "notify_kitchen_order_event",
]
