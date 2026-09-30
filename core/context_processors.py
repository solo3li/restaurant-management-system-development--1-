from django.utils import translation
from .models import Tenant, Branch, UserProfile


def branch_context(request):
    if not request.user.is_authenticated:
        return {}

    tenant = getattr(request, "tenant", None)
    profile = getattr(request.user, "profile", None)
    is_platform_admin = getattr(request, "is_platform_admin", False)

    # Scoped branches for the active tenant
    if tenant:
        all_branches = Branch.objects.filter(tenant=tenant, status="active").order_by("id")
    else:
        all_branches = Branch.objects.filter(status="active").order_by("id")

    is_owner = request.user.is_superuser or is_platform_admin or (profile and profile.role == "owner")

    if not is_owner and profile and profile.branch:
        # Branch staff are locked to their assigned branch
        current_branch = profile.branch
        can_switch = False
    else:
        can_switch = True
        active_id = request.session.get("active_branch_id")
        if active_id and tenant:
            current_branch = Branch.objects.filter(id=active_id, tenant=tenant).first()
        elif active_id:
            current_branch = Branch.objects.filter(id=active_id).first()
        else:
            current_branch = None

    is_hq_mode = current_branch is None

    all_tenants = Tenant.objects.filter(is_active=True).order_by("name") if is_platform_admin else None

    user_perms = set()
    if is_owner:
        user_perms = {
            "view_hq_dashboard", "view_branch_dashboard", "view_financials",
            "pos_access", "view_orders", "edit_orders", "cancel_orders", "delete_orders",
            "kds_access", "call_center_access", "delivery_access",
            "manage_menu", "manage_inventory", "manage_branches", "manage_employees", "manage_roles"
        }
    elif profile:
        if profile.job_role and profile.job_role.permissions:
            user_perms = set(profile.job_role.permissions)
        elif hasattr(request.user, "employee_profile") and request.user.employee_profile and request.user.employee_profile.job_role:
            user_perms = set(request.user.employee_profile.job_role.permissions)
        else:
            if profile.role == "branch_manager":
                user_perms = {"view_branch_dashboard", "pos_access", "view_orders", "edit_orders", "cancel_orders", "kds_access", "delivery_access", "manage_menu", "manage_inventory", "manage_employees"}
            elif profile.role == "cashier":
                user_perms = {"pos_access", "view_orders"}
            elif profile.role == "chef":
                user_perms = {"kds_access"}
            elif profile.role == "driver":
                user_perms = {"delivery_access"}
            elif profile.role == "call_center":
                user_perms = {"call_center_access", "view_orders"}

    tenant_subscription = None
    if tenant and tenant.subscription_plan:
        plan_features = set(tenant.subscription_plan.features or [])
        # If tenant plan does not include certain modules, filter them from user perms unless platform superadmin
        if not is_platform_admin:
            if "call_center" not in plan_features:
                user_perms.discard("call_center_access")
            if "inventory" not in plan_features:
                user_perms.discard("manage_inventory")
            if "custom_roles" not in plan_features:
                user_perms.discard("manage_roles")
            if "delivery_management" not in plan_features:
                user_perms.discard("delivery_access")

        tenant_subscription = {
            "plan": tenant.subscription_plan,
            "plan_name": tenant.subscription_plan.name,
            "status": tenant.subscription_status,
            "status_display": tenant.get_subscription_status_display(),
            "billing_cycle": tenant.get_billing_cycle_display(),
            "end_date": tenant.subscription_end,
            "days_left": tenant.days_until_expiry(),
            "is_active": tenant.is_subscription_active(),
            "is_expiring_soon": (tenant.days_until_expiry() <= 7) if tenant.subscription_end else False,
            "max_branches": tenant.subscription_plan.max_branches,
            "branches_count": tenant.branches.count(),
            "max_employees": tenant.subscription_plan.max_employees,
            "employees_count": tenant.employees.count(),
            "features": plan_features,
        }

    return {
        "active_tenant": tenant,
        "tenant_name": tenant.name if tenant else ("منصة إدارة المطاعم" if (translation.get_language() or "ar").startswith("ar") else "Restaurant Management System"),
        "tenant_logo": tenant.logo_emoji if tenant else "🍽️",
        "all_tenants": all_tenants,
        "is_platform_admin": is_platform_admin,
        "is_owner": is_owner,
        "current_branch": current_branch,
        "is_hq_mode": is_hq_mode,
        "can_switch_branches": can_switch,
        "all_branches": all_branches,
        "user_profile": profile,
        "user_perms": user_perms,
        "tenant_subscription": tenant_subscription,
    }


def i18n_context(request):
    """
    Comprehensive context processor providing language, layout direction,
    and a rich bilingual translation dictionary (Arabic & English 100%).
    """
    lang = None
    if hasattr(request, "LANGUAGE_CODE") and request.LANGUAGE_CODE:
        lang = request.LANGUAGE_CODE
    elif hasattr(request, "session") and request.session.get("django_language"):
        lang = request.session.get("django_language")
    elif request.COOKIES.get("django_language"):
        lang = request.COOKIES.get("django_language")
    else:
        lang = translation.get_language() or "ar"

    if "-" in lang:
        lang = lang.split("-")[0]
    if lang not in ["ar", "en"]:
        lang = "ar"

    is_rtl = (lang == "ar")

    t = {
        # App & Brand
        "app_title": "نظام مطاعم ضيافة" if is_rtl else "Diyafa Restaurant Management",
        "brand_name": "ضِيَافَة" if is_rtl else "DIYAFA",
        "brand_hq": "HQ",
        "brand_subtitle": "نظام إدارة المطاعم" if is_rtl else "Restaurant Management System",
        "brand_tagline": "نظام التشغيل السحابي للمطاعم والضيافة" if is_rtl else "Cloud Operating System for Hospitality & Dining",
        "online_system": "متصل بالنظام السحابي" if is_rtl else "Connected to Cloud OS",
        "all_branches_label": "الإدارة العامة (كافة الفروع)" if is_rtl else "Central HQ (All Branches)",
        "branch_prefix": "فرع" if is_rtl else "Branch",

        # Navigation
        "nav_dashboard": "لوحة الإدارة العامة (HQ)" if is_rtl else "HQ Central Dashboard",
        "nav_branch_dashboard": "لوحة تشغيل الفرع" if is_rtl else "Branch Operations",
        "nav_branches": "إدارة الفروع والمواقع" if is_rtl else "Branches & Locations",
        "nav_all_branches": "كافة الفروع والمدن" if is_rtl else "All Branches & Cities",
        "nav_switch_hq": "التحويل للإدارة العامة (HQ)" if is_rtl else "Switch to HQ Mode",
        "nav_pos_menu": "نقاط البيع وقائمة الطعام" if is_rtl else "POS & Menu",
        "nav_pos": "كاشير نقطة البيع (POS)" if is_rtl else "Cashier Point of Sale (POS)",
        "nav_menu": "قائمة الأطباق والأسعار" if is_rtl else "Menu Dishes & Pricing",
        "nav_kitchen": "شاشات المطبخ (KDS)" if is_rtl else "Kitchen Displays (KDS)",
        "nav_ai_callcenter": "كول سنتر الذكاء الاصطناعي" if is_rtl else "AI Call Center",
        "nav_callcenter_live": "مركز الاتصالات المباشر" if is_rtl else "Live Call Center",
        "nav_callcenter_mgmt": "إدارة المساعد الذكي وFastMCP" if is_rtl else "AI Agent & FastMCP",
        "nav_inventory": "المستودعات والمخزون" if is_rtl else "Inventory & Warehouses",
        "nav_stock_audit": "جرد المواد والمستودعات" if is_rtl else "Stock Audit & Materials",
        "nav_delivery": "أسطول التوصيل والمناديب" if is_rtl else "Delivery Fleet & Drivers",
        "nav_orders": "سجل كافة الطلبات والفواتير" if is_rtl else "All Orders & Invoices",
        "nav_branch_orders": "طلبات وفواتير الفرع" if is_rtl else "Branch Orders & Invoices",
        "nav_employees": "الموظفون والرواتب" if is_rtl else "Staff & Payroll",
        "nav_subscription": "الاشتراك والتقارير المالية" if is_rtl else "Subscription & Financials",
        "nav_platform": "إدارة منصة SaaS العامة" if is_rtl else "SaaS Platform Admin",
        "nav_django_admin": "لوحة Django Admin" if is_rtl else "Django Admin Console",

        # Header & User Actions
        "profile": "الملف الشخصي" if is_rtl else "User Profile",
        "logout": "تسجيل الخروج" if is_rtl else "Sign Out",
        "login": "تسجيل الدخول" if is_rtl else "Sign In",
        "register": "إنشاء حساب منشأة" if is_rtl else "Register Restaurant",
        "notifications": "الإشعارات" if is_rtl else "Notifications",
        "collapse_sidebar": "تصغير / توسيع القائمة الجانبية (Ctrl + B)" if is_rtl else "Collapse / Expand Sidebar (Ctrl + B)",
        "open_menu": "فتح القائمة الرئيسية" if is_rtl else "Open Main Menu",
        "live": "مباشر" if is_rtl else "LIVE",

        # Common Actions
        "save": "حفظ" if is_rtl else "Save",
        "cancel": "إلغاء" if is_rtl else "Cancel",
        "delete": "حذف" if is_rtl else "Delete",
        "edit": "تعديل" if is_rtl else "Edit",
        "create": "إضافة جديد" if is_rtl else "Add New",
        "search": "بحث..." if is_rtl else "Search...",
        "filter": "تصفية" if is_rtl else "Filter",
        "all": "الكل" if is_rtl else "All",
        "close": "إغلاق" if is_rtl else "Close",
        "back": "رجوع" if is_rtl else "Back",
        "confirm": "تأكيد" if is_rtl else "Confirm",
        "print": "طباعة" if is_rtl else "Print",
        "export": "تصدير" if is_rtl else "Export",
        "refresh": "تحديث" if is_rtl else "Refresh",
        "details": "التفاصيل" if is_rtl else "Details",
        "actions": "الإجراءات" if is_rtl else "Actions",

        # Common Statuses & Financials
        "status": "الحالة" if is_rtl else "Status",
        "active": "نشط" if is_rtl else "Active",
        "inactive": "معطل" if is_rtl else "Inactive",
        "pending": "قيد المراجعة" if is_rtl else "Pending",
        "approved": "تمت الموافقة" if is_rtl else "Approved",
        "rejected": "مرفوض" if is_rtl else "Rejected",
        "completed": "مكتمل" if is_rtl else "Completed",
        "cancelled": "ملغي" if is_rtl else "Cancelled",
        "currency": "ر.س" if is_rtl else "SAR",
        "total": "الإجمالي" if is_rtl else "Total",
        "subtotal": "المجموع الفرعي" if is_rtl else "Subtotal",
        "vat": "ضريبة القيمة المضافة (15%)" if is_rtl else "VAT (15%)",
        "discount": "الخصم" if is_rtl else "Discount",
        "quantity": "الكمية" if is_rtl else "Qty",
        "price": "السعر" if is_rtl else "Price",
        "date": "التاريخ" if is_rtl else "Date",
        "notes": "الملاحظات" if is_rtl else "Notes",

        # POS & KDS
        "cashier": "الكاشير" if is_rtl else "Cashier",
        "dine_in": "محلي" if is_rtl else "Dine-In",
        "takeaway": "سفري" if is_rtl else "Takeaway",
        "delivery_type": "توصيل" if is_rtl else "Delivery",
        "cash": "نقداً" if is_rtl else "Cash",
        "card": "شبكة / مدى" if is_rtl else "Card / Mada",
        "order_num": "طلب رقم" if is_rtl else "Order #",
        "cooking": "قيد الطهي" if is_rtl else "Cooking",
        "ready": "جاهز للاستلام" if is_rtl else "Ready",
        "on_the_way": "في الطريق" if is_rtl else "On The Way",

        # Languages
        "language_arabic": "العربية",
        "language_english": "English",
        "switch_to_arabic": "التبديل إلى العربية",
        "switch_to_english": "Switch to English",
    }

    return {
        "CURRENT_LANG": lang,
        "IS_RTL": is_rtl,
        "DIR": "rtl" if is_rtl else "ltr",
        "OPPOSITE_DIR": "ltr" if is_rtl else "rtl",
        "ALIGN_START": "right" if is_rtl else "left",
        "ALIGN_END": "left" if is_rtl else "right",
        "t": t,
    }
