# Community 7

> 62 nodes

## Key Concepts

- **orders/views.py** (60 connections) — `apps/orders/views.py`
- **Order** (40 connections) — `apps/orders/models.py`
- **api_create_order()** (19 connections) — `apps/orders/views.py`
- **notify_delivery_order_event()** (18 connections) — `apps/orders/events.py`
- **order_edit_view()** (17 connections) — `apps/orders/views.py`
- **DeliveryArea** (16 connections) — `apps/tenants/models.py`
- **notify_kitchen_order_event()** (16 connections) — `apps/kitchen/events.py`
- **api_digital_menu_place_order()** (16 connections) — `apps/menu/views.py`
- **kitchen/events.py** (15 connections) — `apps/kitchen/events.py`
- **orders/models.py** (15 connections) — `apps/orders/models.py`
- **Customer** (14 connections) — `apps/orders/models.py`
- **OrderItem** (14 connections) — `apps/orders/models.py`
- **api_delivery_live()** (12 connections) — `apps/orders/views.py`
- **api_update_order()** (12 connections) — `apps/orders/views.py`
- **delivery_view()** (12 connections) — `apps/orders/views.py`
- **login_required** (11 connections)
- **api_cancel_order()** (10 connections) — `apps/orders/views.py`
- **api_delete_order()** (10 connections) — `apps/orders/views.py`
- **pos_view()** (10 connections) — `apps/orders/views.py`
- **kitchen_live_view()** (9 connections) — `apps/kitchen/views.py`
- **serialize_delivery_order()** (9 connections) — `apps/orders/events.py`
- **delivery_stream_view()** (9 connections) — `apps/orders/views.py`
- **run_tests()** (9 connections) — `scratch/test_delivery_realtime_sse.py`
- **serialize_kitchen_order()** (8 connections) — `apps/kitchen/events.py`
- **hq_orders_view()** (8 connections) — `apps/orders/views.py`
- *... and 37 more nodes in this community*

## Relationships

- [Community 2](Community_2.md) (85 shared connections)
- [Community 3](Community_3.md) (45 shared connections)
- [Community 4](Community_4.md) (32 shared connections)
- [Community 12](Community_12.md) (23 shared connections)
- [Community 45](Community_45.md) (4 shared connections)
- [Community 20](Community_20.md) (4 shared connections)
- [Community 13](Community_13.md) (4 shared connections)
- [Community 26](Community_26.md) (3 shared connections)
- [Community 117](Community_117.md) (3 shared connections)
- [Community 8](Community_8.md) (3 shared connections)
- [Community 36](Community_36.md) (2 shared connections)
- [Community 90](Community_90.md) (1 shared connections)

## Source Files

- `apps/kitchen/events.py`
- `apps/kitchen/views.py`
- `apps/menu/views.py`
- `apps/orders/admin.py`
- `apps/orders/events.py`
- `apps/orders/models.py`
- `apps/orders/views.py`
- `apps/tenants/models.py`
- `core/kitchen_events.py`
- `scratch/test_delivery_realtime_sse.py`

## Audit Trail

- EXTRACTED: 270 (79%)
- INFERRED: 70 (21%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*