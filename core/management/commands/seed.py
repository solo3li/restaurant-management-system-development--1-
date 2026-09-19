import random
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import (
    Tenant,
    Branch,
    Employee,
    MenuItem,
    InventoryItem,
    Customer,
    Order,
    OrderItem,
    UserProfile,
    BranchMenuAvailability,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Seed database with Multi-Tenant structure, employee PINs, and test accounts"

    def handle(self, *args, **options):
        self.stdout.write("Configuring Multi-Tenancy & Employee PINs...")

        # -------------------------------------------------------------
        # 1. Platform Super Admin (SaaS Level)
        # -------------------------------------------------------------
        super_admin, _ = User.objects.get_or_create(
            username="superadmin",
            defaults={"email": "superadmin@saas.local", "is_staff": True, "is_superuser": True},
        )
        super_admin.set_password("admin123")
        super_admin.is_staff = True
        super_admin.is_superuser = True
        super_admin.save()
        UserProfile.objects.update_or_create(
            user=super_admin,
            defaults={"role": "platform_admin", "is_platform_admin": True, "tenant": None, "branch": None},
        )
        self.stdout.write(self.style.SUCCESS("Platform Super Admin 'superadmin' (SaaS Level) created."))

        # -------------------------------------------------------------
        # 2. Tenant 1: مطاعم ضيافة (Diyafa Restaurants)
        # -------------------------------------------------------------
        tenant1, _ = Tenant.objects.get_or_create(
            slug="diyafa",
            defaults={
                "name": "مطاعم ضيافة",
                "logo_emoji": "🔥",
                "phone": "0112345678",
                "email": "contact@diyafa.local",
                "address": "الرياض، طريق الملك فهد",
                "plan": "enterprise",
                "is_active": True,
            },
        )

        # Diyafa Owner (admin)
        admin_user, _ = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@diyafa.local", "is_staff": True, "is_superuser": True},
        )
        admin_user.set_password("admin123")
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.save()
        UserProfile.objects.update_or_create(
            user=admin_user,
            defaults={"tenant": tenant1, "role": "owner", "branch": None, "is_platform_admin": False},
        )

        # Assign existing records without tenant to Tenant 1
        Branch.objects.filter(tenant__isnull=True).update(tenant=tenant1)
        MenuItem.objects.filter(tenant__isnull=True).update(tenant=tenant1)
        InventoryItem.objects.filter(tenant__isnull=True).update(tenant=tenant1)
        Customer.objects.filter(tenant__isnull=True).update(tenant=tenant1)
        Order.objects.filter(tenant__isnull=True).update(tenant=tenant1)
        Employee.objects.filter(tenant__isnull=True).update(tenant=tenant1)

        # Set employee codes & PINs for Tenant 1 employees
        # Cashier: PIN 1234
        # Chef: PIN 5678
        # Manager: PIN 1111
        # Driver: PIN 9999
        # Waiter: PIN 0000
        pin_map = {
            "manager": "1111",
            "cashier": "1234",
            "chef": "5678",
            "driver": "9999",
            "waiter": "0000",
            "call_center": "1234",
        }

        first_branch = Branch.objects.filter(tenant=tenant1).first()

        # Specific test branch manager user
        mgr_user, _ = User.objects.get_or_create(username="manager_olaya", defaults={"email": "mgr@diyafa.local"})
        mgr_user.set_password("admin123")
        mgr_user.save()
        UserProfile.objects.update_or_create(user=mgr_user, defaults={"tenant": tenant1, "role": "branch_manager", "branch": first_branch})

        # Specific test chef user
        chef_user, _ = User.objects.get_or_create(username="chef_olaya", defaults={"email": "chef@diyafa.local"})
        chef_user.set_password("admin123")
        chef_user.save()
        UserProfile.objects.update_or_create(user=chef_user, defaults={"tenant": tenant1, "role": "chef", "branch": first_branch})

        # Setup PINs and auto-created User accounts for all Tenant 1 employees
        diyafa_employees = Employee.objects.filter(tenant=tenant1).order_by("id")
        code_counter = 101
        for emp in diyafa_employees:
            emp.employee_code = str(code_counter)
            raw_pin = pin_map.get(emp.role, "1234")
            emp.set_pin(raw_pin)

            # Auto-link or create User account for employee
            if not emp.user:
                emp_username = f"emp_{tenant1.slug}_{code_counter}"
                user_obj, _ = User.objects.get_or_create(username=emp_username, defaults={"first_name": emp.name})
                user_obj.set_password("admin123")
                user_obj.save()
                emp.user = user_obj
                UserProfile.objects.update_or_create(
                    user=user_obj,
                    defaults={"tenant": tenant1, "role": emp.role, "branch": emp.branch}
                )

            emp.save()
            code_counter += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {diyafa_employees.count()} employees in Diyafa with codes 101+ and hashed PINs."))

        # -------------------------------------------------------------
        # 3. Tenant 2: برجر كلاسيك (Burger Classic)
        # -------------------------------------------------------------
        tenant2, created = Tenant.objects.get_or_create(
            slug="burger-classic",
            defaults={
                "name": "برجر كلاسيك",
                "logo_emoji": "🍔",
                "phone": "0126543210",
                "email": "hello@burgerclassic.local",
                "address": "جدة، طريق الأندلس",
                "plan": "premium",
                "is_active": True,
            },
        )

        # Burger Classic Owner
        owner_burger, _ = User.objects.get_or_create(
            username="owner_burger",
            defaults={"email": "owner@burgerclassic.local"},
        )
        owner_burger.set_password("admin123")
        owner_burger.save()
        UserProfile.objects.update_or_create(
            user=owner_burger,
            defaults={"tenant": tenant2, "role": "owner", "branch": None},
        )

        # Branches for Tenant 2
        b_tahliya, _ = Branch.objects.get_or_create(
            tenant=tenant2,
            name="فرع التحلية — جدة",
            defaults={"city": "جدة", "address": "شارع التحلية، حي الروضة", "phone": "0126001001", "status": "active"},
        )
        b_rawdah, _ = Branch.objects.get_or_create(
            tenant=tenant2,
            name="فرع الروضة — جدة",
            defaults={"city": "جدة", "address": "شارع الكيال، حي الروضة", "phone": "0126002002", "status": "active"},
        )

        # Menu for Tenant 2
        burger_menu = [
            {"name": "كلاسيك برجر لحم", "category": "برجر", "price": Decimal("32"), "cost": Decimal("14"), "emoji": "🍔"},
            {"name": "دبل تشيز برجر", "category": "برجر", "price": Decimal("44"), "cost": Decimal("19"), "emoji": "🍔"},
            {"name": "سموكي بيكون برجر", "category": "برجر", "price": Decimal("48"), "cost": Decimal("22"), "emoji": "🥓"},
            {"name": "كرسبي تشيكن حار", "category": "دجاج", "price": Decimal("35"), "cost": Decimal("15"), "emoji": "🍗"},
            {"name": "بطاطس بالجبن والهلابينو", "category": "مقبلات", "price": Decimal("18"), "cost": Decimal("6"), "emoji": "🍟"},
            {"name": "أصابع الموزاريلا المقرمشة", "category": "مقبلات", "price": Decimal("20"), "cost": Decimal("8"), "emoji": "🧀"},
            {"name": "ميلك شيك شوكولاتة", "category": "مشروبات", "price": Decimal("16"), "cost": Decimal("5"), "emoji": "🥤"},
            {"name": "كولا مثلج", "category": "مشروبات", "price": Decimal("6"), "cost": Decimal("2"), "emoji": "🥤"},
        ]
        for bm in burger_menu:
            m_obj, _ = MenuItem.objects.get_or_create(
                tenant=tenant2,
                name=bm["name"],
                defaults={"category": bm["category"], "price": bm["price"], "cost": bm["cost"], "emoji": bm["emoji"], "available": True},
            )
            # Sync branch availability
            for br in [b_tahliya, b_rawdah]:
                BranchMenuAvailability.objects.get_or_create(branch=br, menu_item=m_obj, defaults={"is_available": True})

        # Employees for Tenant 2
        burger_staff = [
            {"name": "عمرو باقادر", "phone": "0540001001", "role": "manager", "branch": b_tahliya, "code": "201", "pin": "1111", "salary": Decimal("8500")},
            {"name": "حمزة الغامدي", "phone": "0540001002", "role": "cashier", "branch": b_tahliya, "code": "202", "pin": "1234", "salary": Decimal("4800")},
            {"name": "أنس الجحدلي", "phone": "0540001003", "role": "chef", "branch": b_tahliya, "code": "203", "pin": "5678", "salary": Decimal("6800")},
            {"name": "سالم العمودي", "phone": "0540001004", "role": "driver", "branch": b_tahliya, "code": "204", "pin": "9999", "salary": Decimal("4200")},
        ]
        for bs in burger_staff:
            emp_obj, _ = Employee.objects.get_or_create(
                tenant=tenant2,
                employee_code=bs["code"],
                defaults={
                    "name": bs["name"],
                    "phone": bs["phone"],
                    "role": bs["role"],
                    "branch": bs["branch"],
                    "salary": bs["salary"],
                },
            )
            emp_obj.set_pin(bs["pin"])
            if not emp_obj.user:
                emp_u, _ = User.objects.get_or_create(username=f"emp_burger_{bs['code']}", defaults={"first_name": bs["name"]})
                emp_u.set_password("admin123")
                emp_u.save()
                emp_obj.user = emp_u
                UserProfile.objects.update_or_create(
                    user=emp_u,
                    defaults={"tenant": tenant2, "role": bs["role"], "branch": bs["branch"]}
                )
            emp_obj.save()

        # Seed Inventory for Tenant 2
        inv_items = [
            {"name": "لحم أنجوس مفروم", "unit": "كجم", "quantity": Decimal("85"), "min_quantity": Decimal("20"), "branch": b_tahliya},
            {"name": "خبز بريوش طازج", "unit": "حبة", "quantity": Decimal("350"), "min_quantity": Decimal("100"), "branch": b_tahliya},
            {"name": "جبن شيدر طبيعي", "unit": "كجم", "quantity": Decimal("40"), "min_quantity": Decimal("10"), "branch": b_tahliya},
            {"name": "صوص البرجر الخاص", "unit": "لتر", "quantity": Decimal("30"), "min_quantity": Decimal("8"), "branch": b_tahliya},
        ]
        for inv in inv_items:
            InventoryItem.objects.get_or_create(
                tenant=tenant2,
                branch=inv["branch"],
                name=inv["name"],
                defaults={"unit": inv["unit"], "quantity": inv["quantity"], "min_quantity": inv["min_quantity"]},
            )

        # Seed initial orders for Tenant 2 to demonstrate isolation
        if Order.objects.filter(tenant=tenant2).count() == 0:
            cust, _ = Customer.objects.get_or_create(tenant=tenant2, phone="0541112233", defaults={"name": "طارق فيصل", "address": "حي الروضة"})
            menu_burger = MenuItem.objects.filter(tenant=tenant2).first()
            ord1 = Order.objects.create(
                tenant=tenant2,
                order_number="BC-101",
                order_type="dine_in",
                channel="cashier",
                branch=b_tahliya,
                customer=cust,
                customer_name=cust.name,
                status="new",
                subtotal=Decimal("76"),
                total=Decimal("76"),
                cashier="حمزة الغامدي",
            )
            if menu_burger:
                OrderItem.objects.create(order=ord1, menu_item=menu_burger, name=menu_burger.name, price=menu_burger.price, qty=2)

        self.stdout.write(self.style.SUCCESS("Successfully configured Tenant 2 'Burger Classic' with branches and menu."))
        self.stdout.write(self.style.SUCCESS("All Multi-Tenancy Seeding Completed!"))
