import os
import sys
import django
from decimal import Decimal
from datetime import timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.utils import timezone
from core.models import SubscriptionPlan, Tenant

plans_data = [
    {
        "name": "الباقة التجريبية (Trial)",
        "code": "trial",
        "description": "تجربة مجانية لكافة أساسيات تشغيل المطعم ونقاط البيع",
        "price_monthly": Decimal("0.00"),
        "price_yearly": Decimal("0.00"),
        "max_branches": 1,
        "max_employees": 5,
        "features": ["pos", "kds", "menu_management"],
        "trial_days": 14,
        "is_active": True,
        "is_popular": False,
        "ordering": 1,
    },
    {
        "name": "الباقة الأساسية (Basic)",
        "code": "basic",
        "description": "مثالية للمطاعم الناشئة والكافيهات ذات الفروع المحدودة",
        "price_monthly": Decimal("299.00"),
        "price_yearly": Decimal("2990.00"),
        "max_branches": 2,
        "max_employees": 15,
        "features": ["pos", "kds", "menu_management", "delivery_management"],
        "trial_days": 0,
        "is_active": True,
        "is_popular": False,
        "ordering": 2,
    },
    {
        "name": "الباقة الاحترافية (Pro)",
        "code": "pro",
        "description": "شاملة الكول سنتر والمخزون وإدارة التوصيل المتقدمة والمسميات الوظيفية",
        "price_monthly": Decimal("599.00"),
        "price_yearly": Decimal("5990.00"),
        "max_branches": 5,
        "max_employees": 50,
        "features": ["pos", "kds", "menu_management", "delivery_management", "call_center", "inventory", "custom_roles"],
        "trial_days": 0,
        "is_active": True,
        "is_popular": True,
        "ordering": 3,
    },
    {
        "name": "باقة الشركات والفرانشايز (Enterprise)",
        "code": "enterprise",
        "description": "فروع وموظفين غير محدودين مع كافة الميزات والتحليلات المالية المتقدمة",
        "price_monthly": Decimal("1299.00"),
        "price_yearly": Decimal("12990.00"),
        "max_branches": 0,  # Unlimited
        "max_employees": 0,  # Unlimited
        "features": ["pos", "kds", "menu_management", "delivery_management", "call_center", "inventory", "custom_roles", "financial_analytics"],
        "trial_days": 0,
        "is_active": True,
        "is_popular": False,
        "ordering": 4,
    },
]

created_plans = {}
for p in plans_data:
    obj, created = SubscriptionPlan.objects.update_or_create(
        code=p["code"],
        defaults=p
    )
    created_plans[p["code"]] = obj
    print(f"Plan [{obj.name}] - Created: {created}, Max branches: {obj.max_branches}, Max employees: {obj.max_employees}")

# Link existing tenants to enterprise plan by default
now = timezone.now()
enterprise_plan = created_plans["enterprise"]
for t in Tenant.objects.all():
    if not t.subscription_plan:
        t.subscription_plan = enterprise_plan
        t.subscription_status = "active"
        t.billing_cycle = "yearly"
        t.subscription_start = now
        t.subscription_end = now + timedelta(days=365)
        t.save()
        print(f"Tenant [{t.name}] linked to Enterprise plan, expires: {t.subscription_end.date()}")

print("Seeding completed successfully!")
