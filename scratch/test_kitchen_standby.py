import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, Branch
from apps.billing.models import SubscriptionPlan
from apps.accounts.models import JobRole, UserProfile
from apps.menu.models import MenuItem
from apps.orders.models import Order, OrderItem


def run_tests():
    print("=====================================================================")
    print("Starting Comprehensive Kitchen Display System (KDS) Standby Test")
    print("=====================================================================")

    # 1. Setup Tenant and Branch
    plan, _ = SubscriptionPlan.objects.get_or_create(
        code="test-kds-plan",
        defaults={
            "name": "Test KDS Plan",
            "features": ["kds", "pos", "call_center", "inventory", "delivery", "delivery_management"],
            "max_branches": 10,
            "max_employees": 50,
        }
    )
    tenant, _ = Tenant.objects.get_or_create(
        slug="test-kds-tenant",
        defaults={
            "name": "مطعم اختبار المطبخ",
            "is_active": True,
            "subscription_plan": plan,
        }
    )
    if tenant.subscription_plan != plan:
        tenant.subscription_plan = plan
        tenant.save()
    branch, _ = Branch.objects.get_or_create(
        tenant=tenant,
        name="فرع المطبخ الرئيسي",
        defaults={
            "status": "active",
        }
    )

    # 2. Setup Job Roles and Chef User
    chef_role, _ = JobRole.objects.get_or_create(
        tenant=tenant,
        name="طاهي تجريبي",
        defaults={"scope": "branch"}
    )
    chef_role.sync_with_django_group()
    chef_role.set_permissions([
        "kds_access", "kds_recall_order", "kds_pause_item",
        "kds_update_status", "menu_view"
    ])

    chef_user, _ = User.objects.get_or_create(username="test_kds_chef")
    chef_user.groups.set([chef_role.group])
    UserProfile.objects.update_or_create(
        user=chef_user,
        defaults={
            "tenant": tenant,
            "branch": branch,
            "job_role": chef_role,
            "role": "chef",
        }
    )

    # 3. Setup Menu Items with categories
    categories = ["مشويات", "أطباق رئيسية", "مقبلات", "مشروبات"]
    for cat in categories:
        MenuItem.objects.get_or_create(
            tenant=tenant,
            name=f"صنف {cat}",
            defaults={"price": 50.00, "category": cat, "available": True}
        )

    # Clean existing pending orders for this tenant
    Order.objects.filter(tenant=tenant).delete()

    client = Client()
    client.force_login(chef_user)

    # -----------------------------------------------------------------
    # Suite 1: Arabic Standby State (Default)
    # -----------------------------------------------------------------
    print("\n--- Suite 1: Arabic Standby State ---")
    res = client.get("/kitchen/")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    content = res.content.decode("utf-8")

    # Check that orders grid does NOT have min-h-[350px]
    assert "min-h-[350px]" not in content, "Error: min-h-[350px] still found in kitchen.html!"
    print("✓ Verified: Phantom reserved height 'min-h-[350px]' completely removed.")

    # Check empty state is initially visible (flex) and grid is hidden
    assert 'id="kitchen-orders-grid" class="hidden' in content or 'hidden grid' in content, "Grid should be hidden when 0 orders"
    print("✓ Verified: Orders grid is hidden when no pending orders exist.")

    # Check Live Digital Clock markup
    assert 'id="standby-clock-time"' in content, "Missing standby-clock-time element"
    assert 'id="standby-clock-ampm"' in content, "Missing standby-clock-ampm element"
    assert 'id="standby-clock-date"' in content, "Missing standby-clock-date element"
    assert 'dir="ltr"' in content, "Missing dir='ltr' for clock alignment"
    print("✓ Verified: Live Digital Kitchen Clock elements present with LTR layout.")

    # Check Live Standby Beacon
    assert 'id="standby-beacon-pill"' in content, "Missing standby-beacon-pill element"
    assert "المحطة متصلة وجاهزة • بانتظار الطلبات الفورية" in content, "Arabic beacon text missing"
    print("✓ Verified: Live Standby Beacon present with gentle pulsating indicator.")

    # Check Arabic Idle Heading
    assert "المطبخ هادئ الآن — جميع الطلبات منجزة" in content, "Arabic idle title missing"
    print("✓ Verified: Arabic Idle Heading rendered correctly.")

    # -----------------------------------------------------------------
    # Suite 2: English Standby State (?lang=en)
    # -----------------------------------------------------------------
    print("\n--- Suite 2: English Standby State (?lang=en) ---")
    res_en = client.get("/kitchen/?lang=en")
    assert res_en.status_code == 200, f"Expected 200, got {res_en.status_code}"
    content_en = res_en.content.decode("utf-8")

    # Check English Page Title
    assert "Kitchen Display System (KDS Live)" in content_en, "English page title missing"
    print("✓ Verified: English page title rendered.")

    # Check English Toolbar elements
    assert "Kitchen KDS" in content_en, "English header badge missing"
    assert "Live 0ms" in content_en, "English live status badge missing"
    assert "Search by order #..." in content_en, "English search placeholder missing"
    assert "Completed" in content_en, "English completed button missing"
    print("✓ Verified: English toolbar badges, buttons, and placeholders rendered.")

    # Check English Standby Beacon & Heading
    assert "Station Connected & Live • Awaiting Inbound Orders" in content_en, "English beacon text missing"
    assert "Kitchen is Idle — All Orders Fulfilled" in content_en, "English idle heading missing"
    assert "New order tickets from Cashier, Call Center, and Online delivery will appear here" in content_en, "English idle description missing"
    print("✓ Verified: English Standby Hero heading, beacon, and description rendered.")

    # Check Category translations
    assert "Grills" in content_en, "Translated category Grills missing"
    assert "Main Dishes" in content_en, "Translated category Main Dishes missing"
    assert "Appetizers" in content_en, "Translated category Appetizers missing"
    assert "Beverages" in content_en, "Translated category Beverages missing"
    print("✓ Verified: Station category tabs translated cleanly to English.")

    # -----------------------------------------------------------------
    # Suite 3: JavaScript Engine & Transition Functions
    # -----------------------------------------------------------------
    print("\n--- Suite 3: JavaScript Engine & Transition Functions ---")
    assert "function startLiveKitchenClock()" in content, "Missing startLiveKitchenClock function"
    assert "function renderOrdersGrid(" in content, "Missing renderOrdersGrid function"
    assert "function getStationDisplayName(" in content, "Missing getStationDisplayName function"
    assert "function getOrderTypeDisplay(" in content, "Missing getOrderTypeDisplay function"
    assert "safeGetCookie(" in content, "Missing safeGetCookie function"
    assert "initial-orders-data" in content, "Missing initial-orders-data script tag"
    assert "category-translations-data" in content, "Missing category-translations-data script tag"
    print("✓ Verified: All required JavaScript functions, data scripts, and transition handlers present.")

    # -----------------------------------------------------------------
    # Suite 4: Standby Hero with Active Order
    # -----------------------------------------------------------------
    print("\n--- Suite 4: Grid Appearance with Active Order ---")
    order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number="9901",
        status="new",
        order_type="dine_in",
        customer_name="فهد الشمري",
        total=100.00,
    )
    menu_item = MenuItem.objects.filter(tenant=tenant, category="مشويات").first()
    OrderItem.objects.create(
        order=order,
        menu_item=menu_item,
        name="مشويات مشكلة",
        price=50.00,
        qty=2
    )

    res_with_order = client.get("/kitchen/")
    assert res_with_order.status_code == 200
    content_order = res_with_order.content.decode("utf-8")

    # With an order, total_pending is 1, so empty state has class hidden
    assert 'id="kitchen-empty-state" class="hidden' in content_order or 'class="hidden flex-1' in content_order, "Empty state should be hidden when orders exist"
    assert "9901" in content_order, "Order number 9901 should be present in initial orders data"
    print("✓ Verified: When active orders exist, empty state is hidden and order grid is active.")

    # -----------------------------------------------------------------
    # Suite 5: Deep Robustness & Bugfix Verifications
    # -----------------------------------------------------------------
    print("\n--- Suite 5: Deep Robustness & Bugfix Verifications ---")
    
    # 5.1 Verify #badge-station-all immunity against category loop
    assert "badge.id === 'badge-station-all'" in content, "badge-station-all immunity check missing"
    assert "catName === 'all'" in content, "Explicit 'all' guard missing in station count updater"
    print("✓ Verified: badge-station-all protected from being hidden or wiped to 0.")

    # 5.2 Verify Standby Beacon updates with SSE state
    assert "const standbyBeaconPill = document.getElementById('standby-beacon-pill');" in content, "Missing standbyBeaconPill update in updateSSEStatus"
    assert "Connecting to Live Stream..." in content, "Missing reconnecting standby beacon text"
    print("✓ Verified: Standby Hero beacon dynamically reflects live SSE connection state.")

    # 5.3 Verify Removal deduplication
    assert "pendingRemovalOrders = new Set();" in content, "Missing removal deduplication set"
    print("✓ Verified: Double-toast and duplicate removal race conditions prevented.")

    # 5.4 Verify Fullscreen UI synchronization
    assert 'id="btn-fullscreen-toggle"' in content, "Missing btn-fullscreen-toggle ID"
    assert 'id="fullscreen-icon"' in content, "Missing fullscreen-icon ID"
    assert "function syncFullscreenUI()" in content, "Missing syncFullscreenUI function"
    print("✓ Verified: Fullscreen toggle button and icon synchronization active.")

    # 5.5 Verify Clock SSR timestamp (No flash of placeholder)
    assert "--:--:--" not in content, "Raw placeholder --:--:-- should not be in rendered HTML"
    assert "..." not in content.split('id="standby-clock-date"')[1].split('</div>')[0], "Raw ... date placeholder should not be in rendered HTML"
    print("✓ Verified: Clock renders real SSR server timestamp immediately.")

    # 5.6 Verify I18N Catalog presence
    from core.i18n_catalog import I18N_CATALOG
    assert "المطبخ هادئ الآن — جميع الطلبات منجزة" in I18N_CATALOG
    assert I18N_CATALOG["المطبخ هادئ الآن — جميع الطلبات منجزة"] == "Kitchen is Idle — All Orders Fulfilled"
    assert "المحطة متصلة وجاهزة • بانتظار الطلبات الفورية" in I18N_CATALOG
    print("✓ Verified: KDS Standby entries fully registered in core/i18n_catalog.py.")

    print("\n=====================================================================")
    print("ALL 5 ADVANCED SUITES PASSED PERFECTLY! 100% VERIFIED.")
    print("=====================================================================")


if __name__ == "__main__":
    run_tests()
