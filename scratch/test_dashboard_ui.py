import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, UserProfile, Branch, Order, OrderItem

def test_dashboard():
    print("=== Testing Luxury Sidebar & Dashboard Implementation ===")
    
    # Check if there is an owner user
    owner_profile = UserProfile.objects.filter(role="owner").first()
    if not owner_profile:
        print("No owner profile found, creating test owner...")
        tenant = Tenant.objects.first()
        user = User.objects.create_user(username="test_hq_owner", password="password123")
        owner_profile = UserProfile.objects.create(user=user, tenant=tenant, role="owner")
    else:
        user = owner_profile.user
    
    c = Client()
    # Force login
    c.force_login(user)
    
    # Ensure session is in HQ mode (no active_branch_id)
    session = c.session
    if "active_branch_id" in session:
        del session["active_branch_id"]
    if owner_profile and owner_profile.tenant:
        session["active_tenant_id"] = owner_profile.tenant.id
    session.save()

    response = c.get("/dashboard/")
    print(f"GET /dashboard/ Status Code: {response.status_code}")
    if response.status_code == 302:
        print(f"Redirecting to: {response.headers.get('Location')}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    html = response.content.decode("utf-8")
    
    # Verification checks
    checks = [
        ("Sidebar ID", 'id="app-sidebar"'),
        ("Dallah Logo", '/static/img/diyafa_symbol.png'),
        ("Brand Name", 'ضِيَافَة'),
        ("Branches Accordion", 'toggleAccordion(\'acc-branches\')'),
        ("POS Accordion", 'toggleAccordion(\'acc-pos\')'),
        ("AI Call Center Accordion", 'toggleAccordion(\'acc-ai\')'),
        ("Inventory Accordion", 'toggleAccordion(\'acc-inventory\')'),
        ("KPI: Total Revenue", 'إجمالي مبيعات السلسلة اليوم'),
        ("KPI: Total Orders", 'الطلبات المسجلة اليوم'),
        ("KPI: Active Branches", 'الفروع النشطة العاملة'),
        ("KPI: AI Call Center", 'كول سنتر الذكاء الاصطناعي'),
        ("Tier 2: 7 Days Sales", 'تحليلات حركة المبيعات لآخر 7 أيام'),
        ("Tier 2: Live Branch Ranking", 'تصنيف الفروع الحية اليوم'),
        ("Tier 3: Live Orders Stream", 'تدفق الطلبات الحية عبر كافة الفروع'),
        ("Top Dishes Section", 'أكثر الأطباق طلباً بالسلسلة'),
        ("Stock Alerts Section", 'تنبيهات المخزون والتوريد'),
        ("Top Utility Header", 'طلب جديد'),
        ("Mobile Backdrop", 'id="sidebar-backdrop"'),
    ]
    
    all_passed = True
    for name, pattern in checks:
        if pattern in html:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name} NOT found in HTML!")
            all_passed = False
            
    if all_passed:
        print("\n>>> ALL 18 LUXURY UI & DASHBOARD CHECKS PASSED PERFECTLY! <<<")
    else:
        print("\n>>> SOME CHECKS FAILED! <<<")
        exit(1)

if __name__ == "__main__":
    test_dashboard()
