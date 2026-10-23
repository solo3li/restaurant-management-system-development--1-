# Community 118

> 14 nodes

## Key Concepts

- **DeliveryEventBroadcaster** (8 connections) — `apps/orders/events.py`
- **.broadcast()** (4 connections) — `apps/orders/events.py`
- **._get_lock()** (4 connections) — `apps/orders/events.py`
- **.register()** (4 connections) — `apps/orders/events.py`
- **._safe_put()** (4 connections) — `apps/orders/events.py`
- **.unregister()** (4 connections) — `apps/orders/events.py`
- **Any** (3 connections)
- **Queue** (3 connections)
- **.__init__()** (1 connections) — `apps/orders/events.py`
- **Lock** (1 connections)
- **Unregisters and removes a listener queue.** (1 connections) — `apps/orders/events.py`
- **Broadcasts a delivery event payload to all active listener queues for the given…** (1 connections) — `apps/orders/events.py`
- **In-memory async Pub/Sub event broadcaster for Delivery Server-Sent Events.…** (1 connections) — `apps/orders/events.py`
- **Registers a new listener queue for a delivery SSE client.** (1 connections) — `apps/orders/events.py`

## Relationships

- [Community 4](Community_4.md) (1 shared connections)
- [Community 7](Community_7.md) (1 shared connections)

## Source Files

- `apps/orders/events.py`

## Audit Trail

- EXTRACTED: 21 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*