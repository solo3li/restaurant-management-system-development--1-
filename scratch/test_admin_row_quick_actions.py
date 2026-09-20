import os
import sys
import django

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.append(r"c:\Users\solo\Downloads\restaurant-management-system-development (1)")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, SubscriptionPlan, UpgradeRequest

def test_row_quick_actions():
    print("================================================================")
    print("TEST: DJANGO ADMIN ROW QUICK ACTIONS (APPROVE / REJECT BUTTONS)")
    print("================================================================")

    client = Client()
    admin_user = User.objects.filter(is_superuser=True).first()
    assert admin_user is not None
    client.force_login(admin_user)

    tenant = Tenant.objects.get(id=2)  # برجر كلاسيك
    plan_starter = SubscriptionPlan.objects.get(code="starter")
    plan_growth = SubscriptionPlan.objects.get(code="growth")
    plan_pro = SubscriptionPlan.objects.get(code="pro")

    # Set tenant to starter
    tenant.subscription_plan = plan_starter
    tenant.save()

    # 1. Create a pending request
    req = UpgradeRequest.objects.create(
        tenant=tenant,
        requested_plan=plan_pro,
        billing_cycle="yearly",
        requested_by=admin_user,
        notes="طلب تجربة أزرار السطر السريعة",
        status="pending",
    )

    # 2. Verify changelist renders quick action buttons for this row
    resp = client.get("/admin/core/upgraderequest/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "إجراءات سريعة" in content, "Column 'إجراءات سريعة' not found"
    assert f"/admin/core/upgraderequest/{req.id}/approve/" in content, "Quick approve button URL not rendered"
    assert f"/admin/core/upgraderequest/{req.id}/reject/" in content, "Quick reject button URL not rendered"
    assert "onclick=\"return confirm(" in content, "Confirmation prompt not found on quick action button"
    print(f"✓ Changelist rendered quick action buttons for Request #{req.id} with confirmation prompt")

    # 3. Click the Quick Approve button (GET /admin/core/upgraderequest/<id>/approve/)
    approve_url = f"/admin/core/upgraderequest/{req.id}/approve/"
    resp = client.get(approve_url, follow=True)
    assert resp.status_code == 200
    redirect_content = resp.content.decode("utf-8")
    assert "تمت الموافقة بنجاح" in redirect_content, "Success message not found in changelist after quick approve"

    req.refresh_from_db()
    tenant.refresh_from_db()
    assert req.status == "approved"
    assert req.reviewed_at is not None
    assert tenant.subscription_plan == plan_pro, f"Tenant plan was not upgraded to {plan_pro.name}"
    assert tenant.subscription_status == "active"
    print(f"✓ Clicked Quick Approve: Request #{req.id} approved and Tenant '{tenant.name}' upgraded to '{tenant.subscription_plan.name}'!")

    # 4. Create another pending request and test Quick Reject button
    req2 = UpgradeRequest.objects.create(
        tenant=tenant,
        requested_plan=plan_growth,
        billing_cycle="monthly",
        requested_by=admin_user,
        notes="طلب تجربة زر الرفض السريع",
        status="pending",
    )

    reject_url = f"/admin/core/upgraderequest/{req2.id}/reject/"
    resp = client.get(reject_url, follow=True)
    assert resp.status_code == 200
    redirect_content = resp.content.decode("utf-8")
    assert "تم تسجيل رفض" in redirect_content

    req2.refresh_from_db()
    tenant.refresh_from_db()
    assert req2.status == "rejected"
    assert tenant.subscription_plan == plan_pro, "Tenant plan should remain unchanged after rejection"
    print(f"✓ Clicked Quick Reject: Request #{req2.id} rejected and Tenant remains on '{tenant.subscription_plan.name}'")

    print("\n================================================================")
    print("ALL ROW QUICK ACTION TESTS PASSED! 100% SUCCESS.")
    print("================================================================")

if __name__ == "__main__":
    test_row_quick_actions()
