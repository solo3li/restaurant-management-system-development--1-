import random
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Branch, Employee, MenuItem, InventoryItem, Customer, Order, OrderItem, UserProfile, BranchMenuAvailability

User = get_user_model()


class Command(BaseCommand):
    help = "Seed the database with initial restaurant data and superuser admin/admin123"

    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding...")

        # 1. Superuser
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
            defaults={"role": "owner", "branch": None},
        )
        self.stdout.write(self.style.SUCCESS("Superuser 'admin' (Owner) configured."))

        # Create branch manager and chef users for testing
        first_branch = Branch.objects.first()
        if first_branch:
            mgr_user, _ = User.objects.get_or_create(username="manager_olaya", defaults={"email": "mgr@diyafa.local"})
            mgr_user.set_password("admin123")
            mgr_user.save()
            UserProfile.objects.update_or_create(user=mgr_user, defaults={"role": "branch_manager", "branch": first_branch})

            chef_user, _ = User.objects.get_or_create(username="chef_olaya", defaults={"email": "chef@diyafa.local"})
            chef_user.set_password("admin123")
            chef_user.save()
            UserProfile.objects.update_or_create(user=chef_user, defaults={"role": "chef", "branch": first_branch})
            self.stdout.write(self.style.SUCCESS("Test branch users 'manager_olaya' and 'chef_olaya' configured."))

        # Populate BranchMenuAvailability for all branches and items
        for br in Branch.objects.all():
            for m in MenuItem.objects.all():
                BranchMenuAvailability.objects.get_or_create(
                    branch=br,
                    menu_item=m,
                    defaults={"is_available": m.available},
                )
        self.stdout.write(self.style.SUCCESS("Branch menu availability synchronized."))

        if Branch.objects.count() >= 3 and Order.objects.count() > 10:
            self.stdout.write(self.style.WARNING("Database already has branch & order data. Seeding complete."))
            return


        # 2. Branches
        br_data = [
            {"name": "الفرع الرئيسي — العليا", "city": "الرياض", "address": "شارع التحلية، حي العليا", "phone": "0112345678", "status": "active"},
            {"name": "فرع النرجس", "city": "الرياض", "address": "طريق أنس بن مالك، حي النرجس", "phone": "0119876543", "status": "active"},
            {"name": "فرع الياسمين", "city": "الرياض", "address": "شارع عثمان بن عفان، حي الياسمين", "phone": "0114567890", "status": "active"},
        ]
        branches = []
        for b in br_data:
            branches.append(Branch.objects.create(**b))
        self.stdout.write(f"Created {len(branches)} branches.")

        # 3. Employees
        emp_data = [
            {"name": "عبدالله الحربي", "phone": "0555001001", "role": "manager", "branch_idx": 0, "salary": Decimal("9500")},
            {"name": "سعود العتيبي", "phone": "0555001002", "role": "manager", "branch_idx": 1, "salary": Decimal("9000")},
            {"name": "ماجد القحطاني", "phone": "0555001003", "role": "manager", "branch_idx": 2, "salary": Decimal("9000")},
            {"name": "فهد الدوسري", "phone": "0555002001", "role": "cashier", "branch_idx": 0, "salary": Decimal("5200")},
            {"name": "خالد الشمري", "phone": "0555002002", "role": "cashier", "branch_idx": 1, "salary": Decimal("5000")},
            {"name": "محمد عبدالرحمن", "phone": "0555003001", "role": "chef", "branch_idx": 0, "salary": Decimal("7800")},
            {"name": "يوسف إدريس", "phone": "0555003002", "role": "chef", "branch_idx": 1, "salary": Decimal("7500")},
            {"name": "عادل نور", "phone": "0555003003", "role": "chef", "branch_idx": 2, "salary": Decimal("7200")},
            {"name": "أحمد السبيعي", "phone": "0555004001", "role": "driver", "branch_idx": 0, "salary": Decimal("4600")},
            {"name": "تركي المطيري", "phone": "0555004002", "role": "driver", "branch_idx": 0, "salary": Decimal("4500")},
            {"name": "ناصر الشهراني", "phone": "0555004003", "role": "driver", "branch_idx": 1, "salary": Decimal("4500")},
            {"name": "بدر الغامدي", "phone": "0555004004", "role": "driver", "branch_idx": 2, "salary": Decimal("4400")},
            {"name": "نورة العنزي", "phone": "0555005001", "role": "call_center", "branch_idx": 0, "salary": Decimal("5400")},
            {"name": "عبدالعزيز المالكي", "phone": "0555005002", "role": "call_center", "branch_idx": 0, "salary": Decimal("5200")},
            {"name": "مشعل الحارثي", "phone": "0555006001", "role": "waiter", "branch_idx": 0, "salary": Decimal("4200")},
            {"name": "رامي الزهراني", "phone": "0555006002", "role": "waiter", "branch_idx": 2, "salary": Decimal("4200")},
        ]
        employees = []
        today = timezone.now().date()
        for e in emp_data:
            hire = today - timedelta(days=random.randint(90, 400))
            emp = Employee.objects.create(
                name=e["name"],
                phone=e["phone"],
                role=e["role"],
                branch=branches[e["branch_idx"]],
                salary=e["salary"],
                hire_date=hire,
                status="active",
            )
            employees.append(emp)
        drivers = [emp for emp in employees if emp.role == "driver"]
        self.stdout.write(f"Created {len(employees)} employees ({len(drivers)} drivers).")

        # 4. Menu Items
        menu_items_data = [
            {"name": "كبسة لحم", "category": "أطباق رئيسية", "price": Decimal("58"), "cost": Decimal("26"), "emoji": "🍖"},
            {"name": "كبسة دجاج", "category": "أطباق رئيسية", "price": Decimal("42"), "cost": Decimal("17"), "emoji": "🍗"},
            {"name": "مندي لحم", "category": "أطباق رئيسية", "price": Decimal("62"), "cost": Decimal("28"), "emoji": "🥘"},
            {"name": "مندي دجاج", "category": "أطباق رئيسية", "price": Decimal("46"), "cost": Decimal("18"), "emoji": "🍛"},
            {"name": "مقلوبة لحم", "category": "أطباق رئيسية", "price": Decimal("52"), "cost": Decimal("23"), "emoji": "🍲"},
            {"name": "صيادية سمك", "category": "أطباق رئيسية", "price": Decimal("56"), "cost": Decimal("24"), "emoji": "🐟"},
            {"name": "مشاوي مشكلة", "category": "مشويات", "price": Decimal("68"), "cost": Decimal("30"), "emoji": "🥩"},
            {"name": "شيش طاووق", "category": "مشويات", "price": Decimal("38"), "cost": Decimal("15"), "emoji": "🍢"},
            {"name": "كفتة مشوية", "category": "مشويات", "price": Decimal("36"), "cost": Decimal("14"), "emoji": "🍡"},
            {"name": "ريش غنم", "category": "مشويات", "price": Decimal("74"), "cost": Decimal("36"), "emoji": "🍖"},
            {"name": "شاورما لحم", "category": "ساندويتشات", "price": Decimal("18"), "cost": Decimal("7"), "emoji": "🌯"},
            {"name": "شاورما دجاج", "category": "ساندويتشات", "price": Decimal("14"), "cost": Decimal("5"), "emoji": "🌯"},
            {"name": "برجر ضيافة", "category": "ساندويتشات", "price": Decimal("24"), "cost": Decimal("10"), "emoji": "🍔"},
            {"name": "فروج مشوي", "category": "ساندويتشات", "price": Decimal("34"), "cost": Decimal("15"), "emoji": "🍗"},
            {"name": "حمص", "category": "مقبلات", "price": Decimal("12"), "cost": Decimal("4"), "emoji": "🥣"},
            {"name": "متبل باذنجان", "category": "مقبلات", "price": Decimal("12"), "cost": Decimal("4"), "emoji": "🍆"},
            {"name": "سلطة فتوش", "category": "مقبلات", "price": Decimal("14"), "cost": Decimal("5"), "emoji": "🥗"},
            {"name": "شوربة عدس", "category": "مقبلات", "price": Decimal("10"), "cost": Decimal("3"), "emoji": "🥣"},
            {"name": "ماء صحي", "category": "مشروبات", "price": Decimal("2"), "cost": Decimal("0.5"), "emoji": "💧"},
            {"name": "عصير برتقال طازج", "category": "مشروبات", "price": Decimal("10"), "cost": Decimal("4"), "emoji": "🍊"},
            {"name": "شاي كرك", "category": "مشروبات", "price": Decimal("6"), "cost": Decimal("2"), "emoji": "☕"},
            {"name": "قهوة عربية", "category": "مشروبات", "price": Decimal("8"), "cost": Decimal("2.5"), "emoji": "☕"},
            {"name": "مشروب غازي", "category": "مشروبات", "price": Decimal("5"), "cost": Decimal("2"), "emoji": "🥤"},
            {"name": "كنافة", "category": "حلويات", "price": Decimal("16"), "cost": Decimal("6"), "emoji": "🧁"},
            {"name": "أم علي", "category": "حلويات", "price": Decimal("14"), "cost": Decimal("5"), "emoji": "🍮"},
            {"name": "لقيمات", "category": "حلويات", "price": Decimal("12"), "cost": Decimal("4"), "emoji": "🍩"},
        ]
        menu_map = {}
        for m in menu_items_data:
            item = MenuItem.objects.create(**m)
            menu_map[item.name] = item
        self.stdout.write(f"Created {len(menu_map)} menu items.")

        # 5. Inventory Items
        inv_specs = [
            {"name": "أرز بسمتي", "unit": "كجم", "min": 20, "supplier": "مؤسسة الريف للتموين"},
            {"name": "دجاج طازج", "unit": "كجم", "min": 15, "supplier": "شركة أنهار الغذائية"},
            {"name": "لحم غنم", "unit": "كجم", "min": 10, "supplier": "مورد اللحوم المركزي"},
            {"name": "طماطم", "unit": "كجم", "min": 8, "supplier": "سوق الخضار المركزي"},
            {"name": "بصل", "unit": "كجم", "min": 6, "supplier": "سوق الخضار المركزي"},
            {"name": "زيت طبخ", "unit": "لتر", "min": 12, "supplier": "مؤسسة الريف للتموين"},
            {"name": "بهارات مشكلة", "unit": "كجم", "min": 3, "supplier": "بيت التوابل"},
            {"name": "خبز صاج", "unit": "قطعة", "min": 50, "supplier": "مخبز التنور"},
            {"name": "مشروبات غازية", "unit": "علبة", "min": 24, "supplier": "شركة أنهار الغذائية"},
            {"name": "سكر", "unit": "كجم", "min": 5, "supplier": "مؤسسة الريف للتموين"},
        ]
        inv_overrides = {
            0: {"لحم غنم": Decimal("4"), "مشروبات غازية": Decimal("0")},
            1: {"دجاج طازج": Decimal("7")},
            2: {},
        }
        for b_idx, b in enumerate(branches):
            for spec in inv_specs:
                min_q = Decimal(str(spec["min"]))
                if spec["name"] in inv_overrides.get(b_idx, {}):
                    q = inv_overrides[b_idx][spec["name"]]
                else:
                    q = min_q * Decimal(str(random.randint(2, 4)))
                InventoryItem.objects.create(
                    branch=b,
                    name=spec["name"],
                    unit=spec["unit"],
                    quantity=q,
                    min_quantity=min_q,
                    supplier=spec["supplier"],
                )
        self.stdout.write("Created inventory records across all branches.")

        # 6. Customers
        cust_data = [
            {"name": "أبو سلطان", "phone": "0551234567", "address": "حي الياسمين، شارع 12، فيلا 8", "notes": "عميل مميز دائم"},
            {"name": "أم فيصل", "phone": "0559876543", "address": "حي النرجس، طريق أنس بن مالك، شقة 14", "notes": ""},
            {"name": "محمد العنزي", "phone": "0501112223", "address": "حي العليا، شارع التحلية، برج 3", "notes": ""},
            {"name": "لطيفة السالم", "phone": "0533445566", "address": "حي الملقا، شارع الأمير محمد، فيلا 22", "notes": ""},
            {"name": "خالد الراشد", "phone": "0567788990", "address": "حي الصحافة، شارع 7، عمارة 5", "notes": ""},
        ]
        customers = []
        for c in cust_data:
            customers.append(Customer.objects.create(**c))
        self.stdout.write(f"Created {len(customers)} customers.")

        # 7. Orders and OrderItems
        specs = [
            # Last 6 days
            {"d": 6, "h": 13, "b": 0, "ch": "cashier", "t": "dine_in", "st": "delivered", "items": [("كبسة لحم", 2), ("سلطة فتوش", 1), ("مشروب غازي", 2)], "pay": "card"},
            {"d": 6, "h": 20, "b": 1, "ch": "cashier", "t": "takeaway", "st": "delivered", "items": [("شاورما دجاج", 4), ("مشروب غازي", 2)]},
            {"d": 5, "h": 14, "b": 0, "ch": "call_center", "t": "delivery", "st": "delivered", "items": [("مندي لحم", 2), ("حمص", 1), ("كنافة", 1)], "ci": 0, "drv": 0},
            {"d": 5, "h": 19, "b": 2, "ch": "cashier", "t": "dine_in", "st": "delivered", "items": [("مشاوي مشكلة", 1), ("شوربة عدس", 2), ("شاي كرك", 2)], "pay": "card"},
            {"d": 4, "h": 12, "b": 1, "ch": "call_center", "t": "delivery", "st": "delivered", "items": [("كبسة دجاج", 3), ("متبل باذنجان", 1)], "ci": 1, "drv": 2, "pay": "cash"},
            {"d": 4, "h": 21, "b": 0, "ch": "cashier", "t": "takeaway", "st": "delivered", "items": [("برجر ضيافة", 2), ("مشروب غازي", 2)], "pay": "wallet"},
            {"d": 3, "h": 13, "b": 0, "ch": "cashier", "t": "dine_in", "st": "delivered", "items": [("صيادية سمك", 2), ("سلطة فتوش", 2), ("ماء صحي", 2)]},
            {"d": 3, "h": 18, "b": 2, "ch": "call_center", "t": "delivery", "st": "delivered", "items": [("شيش طاووق", 2), ("كفتة مشوية", 1), ("لقيمات", 1)], "ci": 3, "drv": 3, "pay": "card"},
            {"d": 2, "h": 14, "b": 1, "ch": "cashier", "t": "dine_in", "st": "delivered", "items": [("مقلوبة لحم", 1), ("حمص", 1), ("عصير برتقال طازج", 2)], "pay": "cash"},
            {"d": 2, "h": 20, "b": 0, "ch": "call_center", "t": "delivery", "st": "delivered", "items": [("ريش غنم", 1), ("مشاوي مشكلة", 1), ("أم علي", 2)], "ci": 4, "drv": 1, "pay": "cash"},
            {"d": 1, "h": 12, "b": 2, "ch": "cashier", "t": "takeaway", "st": "delivered", "items": [("فروج مشوي", 1), ("حمص", 1), ("مشروب غازي", 1)]},
            {"d": 1, "h": 15, "b": 0, "ch": "cashier", "t": "dine_in", "st": "delivered", "items": [("كبسة لحم", 1), ("كبسة دجاج", 1), ("شوربة عدس", 2)], "pay": "card"},
            {"d": 1, "h": 19, "b": 1, "ch": "call_center", "t": "delivery", "st": "delivered", "items": [("مندي دجاج", 2), ("سلطة فتوش", 1), ("كنافة", 1)], "ci": 2, "drv": 2},
            {"d": 1, "h": 21, "b": 0, "ch": "cashier", "t": "takeaway", "st": "delivered", "items": [("شاورما لحم", 5), ("مشروب غازي", 3)], "pay": "wallet"},
            # Today
            {"d": 0, "h": 9, "b": 0, "ch": "cashier", "t": "dine_in", "st": "delivered", "items": [("قهوة عربية", 2), ("كنافة", 1)]},
            {"d": 0, "h": 11, "b": 1, "ch": "cashier", "t": "takeaway", "st": "delivered", "items": [("شاورما دجاج", 3), ("عصير برتقال طازج", 1)], "pay": "card"},
            {"d": 0, "h": 12, "b": 0, "ch": "call_center", "t": "delivery", "st": "delivered", "items": [("كبسة لحم", 2), ("متبل باذنجان", 1), ("لقيمات", 1)], "ci": 1, "drv": 0},
            {"d": 0, "h": 13, "b": 0, "ch": "cashier", "t": "dine_in", "st": "delivered", "items": [("مشاوي مشكلة", 2), ("سلطة فتوش", 2), ("مشروب غازي", 3)], "pay": "card"},
            {"d": 0, "h": 13, "b": 2, "ch": "cashier", "t": "takeaway", "st": "delivered", "items": [("برجر ضيافة", 1), ("مشروب غازي", 1)]},
            {"d": 0, "h": 14, "b": 0, "ch": "call_center", "t": "delivery", "st": "out_for_delivery", "items": [("مندي لحم", 1), ("شيش طاووق", 2), ("أم علي", 1)], "ci": 3, "drv": 1},
            {"d": 0, "h": 14, "b": 1, "ch": "call_center", "t": "delivery", "st": "ready", "items": [("كبسة دجاج", 2), ("حمص", 1)], "ci": 4},
            {"d": 0, "h": 15, "b": 0, "ch": "cashier", "t": "takeaway", "st": "preparing", "items": [("شاورما لحم", 2), ("شاورما دجاج", 2)]},
            {"d": 0, "h": 15, "b": 1, "ch": "cashier", "t": "dine_in", "st": "new", "items": [("صيادية سمك", 1), ("شوربة عدس", 1), ("ماء صحي", 2)]},
        ]

        seq = 1000
        now = timezone.now()
        for s in specs:
            seq += 1
            ord_num = f"ORD-{seq}"
            valid_items = [(menu_map[name], qty) for name, qty in s["items"] if name in menu_map]
            if not valid_items:
                continue

            subtotal = sum(item.price * qty for item, qty in valid_items)
            delivery_fee = Decimal("8") if s["t"] == "delivery" else Decimal("0")
            total = subtotal + delivery_fee

            cust = customers[s["ci"]] if "ci" in s else None
            drv = drivers[s["drv"]] if "drv" in s and s["drv"] < len(drivers) else None
            cashier_name = "فهد الدوسري" if s["b"] == 0 else "خالد الشمري" if s["ch"] == "cashier" else ""

            # Target creation time
            order_time = now - timedelta(days=s["d"])
            order_time = order_time.replace(hour=s["h"], minute=random.randint(5, 55), second=0, microsecond=0)

            order = Order.objects.create(
                order_number=ord_num,
                order_type=s["t"],
                channel=s["ch"],
                branch=branches[s["b"]],
                customer=cust,
                customer_name=cust.name if cust else ("عميل توصيل" if s["t"] == "delivery" else "عميل نقدي"),
                customer_phone=cust.phone if cust else "",
                address=cust.address if cust else "",
                status=s["st"],
                pay_method=s.get("pay", "cash"),
                paid=True,
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                discount=Decimal("0"),
                total=total,
                cashier=cashier_name,
                driver=drv,
                created_at=order_time,
            )

            for item, qty in valid_items:
                OrderItem.objects.create(
                    order=order,
                    menu_item=item,
                    name=item.name,
                    price=item.price,
                    qty=qty,
                )

        self.stdout.write(self.style.SUCCESS("Database seeded successfully with all branches, menu, staff, and orders!"))
