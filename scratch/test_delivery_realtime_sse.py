import os
import sys
import json
import asyncio
import django

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client, RequestFactory
from django.contrib.auth.models import User
from core.models import Branch, Employee, MenuItem, Customer, Order, OrderItem
from apps.orders.events import (
    serialize_delivery_order,
    delivery_broadcaster,
    notify_delivery_order_event,
)
from apps.orders.views import delivery_stream_view, api_delivery_live

async def test_broadcaster_queue():
    print("Testing DeliveryEventBroadcaster pub/sub...")
    tenant_id = 9999
    branch_id = 8888
    
    q = await delivery_broadcaster.register(tenant_id, branch_id)
    assert q in delivery_broadcaster._subscribers[tenant_id]
    
    test_data = {"id": 123, "order_number": "DEL-101", "status": "new"}
    delivery_broadcaster.broadcast(
        tenant_id=tenant_id,
        event_type="delivery_new_order",
        data=test_data,
        branch_id=branch_id
    )
    
    received = await asyncio.wait_for(q.get(), timeout=2.0)
    assert received["type"] == "delivery_new_order"
    assert received["data"]["order_number"] == "DEL-101"
    
    # Test branch-filtering: broadcast to branch 7777 should not arrive if q is for branch 8888
    delivery_broadcaster.broadcast(
        tenant_id=tenant_id,
        event_type="delivery_other_branch",
        data={"order_number": "DEL-OTHER"},
        branch_id=7777
    )
    # The queue should be empty
    assert q.empty(), "Should not receive event from different branch"
    
    # Broadcast with branch_id=None (all branches) should be received
    delivery_broadcaster.broadcast(
        tenant_id=tenant_id,
        event_type="delivery_all_branches",
        data={"order_number": "DEL-GLOBAL"},
        branch_id=None
    )
    received_global = await asyncio.wait_for(q.get(), timeout=2.0)
    assert received_global["type"] == "delivery_all_branches"
    
    await delivery_broadcaster.unregister(q)
    assert q not in delivery_broadcaster._subscribers.get(tenant_id, set())
    print("   DeliveryEventBroadcaster pub/sub: OK")


def run_tests():
    print("=== STARTING DELIVERY SSE REAL-TIME SYSTEM TESTS ===")
    
    # 1. Broadcaster async test
    asyncio.run(test_broadcaster_queue())
    
    # 2. Setup test tenant, branch, user
    client = Client()
    admin_user = User.objects.get(username="admin")
    profile = getattr(admin_user, "profile", None)
    tenant = profile.tenant
    
    branch = Branch.objects.filter(tenant=tenant, status="active").first()
    if not branch:
        branch = Branch.objects.create(tenant=tenant, name="الفرع الرئيسي", status="active")
        
    driver = Employee.objects.filter(tenant=tenant, role="driver").first()
    if not driver:
        driver = Employee.objects.create(
            tenant=tenant,
            branch=branch,
            name="كابتن توصيل تجريبي",
            role="driver",
            phone="0501112233",
            status="active"
        )
        
    menu_item = MenuItem.objects.filter(tenant=tenant, available=True).first()
    if not menu_item:
        menu_item = MenuItem.objects.create(tenant=tenant, name="برجر تجريبي", price=35, available=True)

    # 3. Test serialize_delivery_order
    print("\nTesting serialize_delivery_order...")
    import uuid
    test_ord_num = f"DEL-TST-{uuid.uuid4().hex[:6].upper()}"
    order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number=test_ord_num,
        order_type="delivery",
        status="new",
        total=70,
        subtotal=70,
        delivery_fee=15,
        driver=driver,
        address="حي الملقا - شارع أنس بن مالك",
        notes="يرجى عدم رن الجرس"
    )
    OrderItem.objects.create(
        order=order,
        menu_item=menu_item,
        name=menu_item.name,
        qty=2,
        price=35
    )
    
    serialized = serialize_delivery_order(order)
    assert serialized["id"] == order.id
    assert serialized["order_number"] == order.order_number
    assert serialized["status"] == "new"
    assert serialized["driver"]["id"] == driver.id
    assert serialized["driver"]["name"] == driver.name
    assert serialized["address"] == "حي الملقا - شارع أنس بن مالك"
    assert serialized["notes"] == "يرجى عدم رن الجرس"
    assert len(serialized["items"]) == 1
    assert serialized["items"][0]["name"] == menu_item.name
    assert serialized["items"][0]["qty"] == 2
    print("   serialize_delivery_order: OK")

    # 4. Test notify_delivery_order_event helper
    print("\nTesting notify_delivery_order_event...")
    async def check_event_emission():
        q = await delivery_broadcaster.register(tenant.id, branch.id)
        
        # Call synchronous helper
        notify_delivery_order_event(order, "delivery_new_order")
        
        msg = await asyncio.wait_for(q.get(), timeout=3.0)
        assert msg["type"] == "delivery_new_order"
        assert msg["data"]["id"] == order.id
        
        await delivery_broadcaster.unregister(q)

    asyncio.run(check_event_emission())
    print("   notify_delivery_order_event: OK")

    # 5. Test Live Snapshot Endpoint
    print("\nTesting /api/delivery/live/ endpoint...")
    client.force_login(admin_user)
    session = client.session
    session["tenant_id"] = tenant.id
    session["branch_id"] = branch.id
    session.save()
    
    resp = client.get("/api/delivery/live/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    live_data = resp.json()
    assert live_data["ok"] is True
    assert "orders" in live_data
    assert "orders_by_status" in live_data
    assert "driver_stats" in live_data
    assert "active_count" in live_data
    
    order_ids = [o["id"] for o in live_data["orders"]]
    assert order.id in order_ids, f"Created delivery order {order.id} should be in live orders"
    print(f"   /api/delivery/live/ snapshot: OK ({len(live_data['orders'])} orders found)")

    # 6. Test Unauthenticated & Authenticated SSE Stream Access
    print("\nTesting /api/delivery/stream/ security & headers...")
    unauth_client = Client()
    resp_unauth = unauth_client.get("/api/delivery/stream/")
    assert resp_unauth.status_code in (403, 302), f"Unauthenticated access should be blocked, got {resp_unauth.status_code}"
    print(f"   Unauthenticated blocked: OK ({resp_unauth.status_code})")

    # Check authenticated access using RequestFactory and async view call
    factory = RequestFactory()
    req = factory.get("/api/delivery/stream/")
    req.user = admin_user
    req.session = session
    
    # Ensure profile has delivery_access
    profile.role = "admin"
    profile.save()
    
    response = asyncio.run(delivery_stream_view(req))
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert response["Content-Type"] == "text/event-stream"
    assert "no-cache" in response["Cache-Control"]
    assert response["X-Accel-Buffering"] == "no"
    print("   Authenticated SSE stream response: OK (text/event-stream)")

    # 7. Test API Create Order with order_type == 'delivery' triggers broadcast
    print("\nTesting Order Creation API with delivery type...")
    from asgiref.sync import sync_to_async
    async_post = sync_to_async(client.post, thread_sensitive=False)

    async def check_api_create_and_update():
        q = await delivery_broadcaster.register(tenant.id, branch.id)
        
        payload = {
            "type": "delivery",
            "channel": "call_center",
            "branchId": branch.id,
            "payMethod": "cash",
            "cashier": "admin",
            "customerName": "عميل توصيل تجريبي",
            "customerPhone": "0551234567",
            "address": "الرياض - حي النرجس",
            "deliveryFee": 20,
            "items": [{"menuItemId": menu_item.id, "qty": 1}]
        }
        res = await async_post("/api/orders/", data=json.dumps(payload), content_type="application/json")
        assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.content}"
        new_order_data = res.json()["order"]
        new_order_id = new_order_data["id"]
        
        # Verify broadcast event received
        event_new = await asyncio.wait_for(q.get(), timeout=3.0)
        assert event_new["type"] == "delivery_new_order"
        assert event_new["data"]["id"] == new_order_id
        assert event_new["data"]["order_type"] == "delivery"
        assert event_new["data"]["address"] == "الرياض - حي النرجس"
        
        # Update driver assignment
        res_assign = await async_post(
            f"/api/orders/{new_order_id}/",
            data=json.dumps({"driver_id": driver.id}),
            content_type="application/json"
        )
        assert res_assign.status_code == 200
        event_assign = await asyncio.wait_for(q.get(), timeout=3.0)
        assert event_assign["type"] == "delivery_driver_assigned"
        assert event_assign["data"]["driver"]["id"] == driver.id

        # Update status to ready
        res_status = await async_post(
            f"/api/orders/{new_order_id}/",
            data=json.dumps({"status": "ready"}),
            content_type="application/json"
        )
        assert res_status.status_code == 200
        event_status = await asyncio.wait_for(q.get(), timeout=3.0)
        assert event_status["type"] == "delivery_status_changed"
        assert event_status["data"]["status"] == "ready"

        # Cancel order
        res_cancel = await async_post(f"/api/orders/{new_order_id}/cancel/")
        assert res_cancel.status_code == 200, f"Expected 200, got {res_cancel.status_code}: {res_cancel.content}"
        event_cancel = await asyncio.wait_for(q.get(), timeout=3.0)
        assert event_cancel["type"] == "delivery_order_cancelled"
        assert event_cancel["data"]["id"] == new_order_id

        await delivery_broadcaster.unregister(q)

    asyncio.run(check_api_create_and_update())
    print("   API Create, Assign, Advance, Cancel with SSE Broadcast: OK")

    print("\nALL DELIVERY REAL-TIME TESTS PASSED WITH 100% SUCCESS!")

if __name__ == "__main__":
    run_tests()
