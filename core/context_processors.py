from django.utils import translation
from .models import Tenant, Branch, UserProfile, RESTAURANT_PERMISSIONS


def normalize_plan_features(features):
    f_set = set(features or [])
    if f_set & {"inventory", "inventory_mgmt"}:
        f_set.add("inventory")
        f_set.add("inventory_mgmt")
    if f_set & {"delivery", "delivery_management", "delivery_zones"}:
        f_set.add("delivery")
        f_set.add("delivery_management")
        f_set.add("delivery_zones")
    if f_set & {"pos", "pos_billing"}:
        f_set.add("pos")
        f_set.add("pos_billing")
    if f_set & {"kds", "kds_kitchen"}:
        f_set.add("kds")
        f_set.add("kds_kitchen")
    if f_set & {"menu", "menu_management"}:
        f_set.add("menu")
        f_set.add("menu_management")
    return f_set


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

    # 1. Resolve user permissions strictly according to Django Groups & JobRole
    user_perms = set()
    effective_job_role = None
    if profile and profile.job_role:
        effective_job_role = profile.job_role
    elif hasattr(request.user, "employee_profile") and request.user.employee_profile and request.user.employee_profile.job_role:
        effective_job_role = request.user.employee_profile.job_role

    if is_owner:
        user_perms = {p[0] for p in RESTAURANT_PERMISSIONS}
    else:
        # Django built-in permissions from User.groups and User.user_permissions
        native_perms = {p.split(".")[-1] for p in request.user.get_all_permissions()}
        if effective_job_role is not None:
            user_perms = set(effective_job_role.get_permissions_list()) | native_perms
        else:
            user_perms = native_perms

    # Filter by subscription plan features
    if tenant and tenant.subscription_plan and not is_platform_admin:
        plan_features = normalize_plan_features(tenant.subscription_plan.features)
        if "call_center" not in plan_features:
            user_perms.discard("call_center_access")
            user_perms.discard("call_center_create_order")
        if "inventory" not in plan_features:
            user_perms.discard("manage_inventory")
            user_perms.discard("inventory_view")
            user_perms.discard("inventory_add_stock")
            user_perms.discard("inventory_adjust_stock")
        if "custom_roles" not in plan_features:
            user_perms.discard("manage_roles")
        if "delivery_management" not in plan_features and "delivery_zones" not in plan_features:
            user_perms.discard("delivery_access")

    # 2. Branch Scoping:
    # Cross-branch scope is allowed ONLY for owners, managers with manage_branches,
    # or centralized call center / HQ roles. Operational staff (cashier, kitchen, driver) are branch-locked.
    can_operate_cross_branches = (
        is_owner
        or ("manage_branches" in user_perms)
        or ("call_center_access" in user_perms)
        or (effective_job_role and effective_job_role.scope in ["hq", "both"])
    )

    if can_operate_cross_branches:
        can_switch = True
        active_id = request.session.get("active_branch_id")
        if active_id and tenant:
            current_branch = Branch.objects.filter(id=active_id, tenant=tenant).first()
        elif active_id:
            current_branch = Branch.objects.filter(id=active_id).first()
        else:
            current_branch = profile.branch if (profile and profile.branch) else None
    else:
        can_switch = False
        if profile and profile.branch:
            current_branch = profile.branch
        elif tenant:
            current_branch = tenant.branches.filter(status="active").first() or tenant.branches.first()
        else:
            current_branch = None

    is_hq_mode = (current_branch is None) and can_operate_cross_branches

    all_tenants = Tenant.objects.filter(is_active=True).order_by("name") if is_platform_admin else None

    tenant_subscription = None
    if tenant and tenant.subscription_plan:
        plan_features = normalize_plan_features(tenant.subscription_plan.features)
        # If tenant plan does not include certain modules, filter them from user perms unless platform superadmin
        if not is_platform_admin:
            if "call_center" not in plan_features:
                user_perms.discard("call_center_access")
                user_perms.discard("call_center_create_order")
            if "inventory" not in plan_features:
                user_perms.discard("manage_inventory")
                user_perms.discard("inventory_view")
                user_perms.discard("inventory_add_stock")
                user_perms.discard("inventory_adjust_stock")
            if "custom_roles" not in plan_features:
                user_perms.discard("manage_roles")
            if "delivery_management" not in plan_features and "delivery_zones" not in plan_features:
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
        "can_operate_cross_branches": can_operate_cross_branches,
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

    from .i18n_catalog import I18N_CATALOG

    is_rtl = (lang == "ar")

    base_t = {
        # App & Brand
        "app_title": "منظومة كُـورَا لإدارة المطاعم" if is_rtl else "KURA Restaurant Management OS",
        "brand_name": "كُـورَا" if is_rtl else "KURA",
        "brand_hq": "HQ",
        "brand_subtitle": "نظام إدارة المطاعم" if is_rtl else "Restaurant Management System",
        "brand_tagline": "النظام السحابي لإدارة سلاسل المطاعم والضيافة العريقة" if is_rtl else "Cloud Operating System for Hospitality & Dining",
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

        # Operational Domains
        "dash_command_center": "مركز القيادة والعمليات" if is_rtl else "Command & Operations Center",
        "dash_subtitle": "متابعة حية للتدفق المالي، توزيع الطلبات، أداء الفروع، وكول سنتر الذكاء الاصطناعي في شاشة موحدة." if is_rtl else "Live monitoring of cash flow, order distribution, branch performance, and AI Call Center.",
        "dash_unified_system": "النظام الموحد للإدارة العليا" if is_rtl else "Unified Executive Management System",
        "dash_live_monitoring": "متابعة فورية ومباشرة لكافة الفروع" if is_rtl else "Live Real-Time Monitoring of All Branches",
        "dash_chain_sales_today": "إجمالي مبيعات السلسلة اليوم" if is_rtl else "Total Chain Revenue Today",
        "dash_net_revenue": "صافي الإيراد المحصل" if is_rtl else "Net Collected Revenue",
        "dash_completed_orders": "عدد الطلبات المكتملة" if is_rtl else "Completed Orders Count",
        "dash_active_orders": "الطلبات النشطة حالياً" if is_rtl else "Currently Active Orders",
        "dash_branches_performance": "أداء الفروع المباشر" if is_rtl else "Live Branch Performance",
        "dash_sales_by_channel": "توزيع المبيعات حسب القنوات" if is_rtl else "Sales Distribution by Channel",
        "dash_top_dishes": "أكثر الأطباق طلباً بالسلسلة" if is_rtl else "Top Selling Dishes Across Chain",
        "dash_sales_last_7_days": "مبيعات آخر 7 أيام" if is_rtl else "Sales - Last 7 Days",

        "pos_title": "الكاشير — نقطة البيع الذكية" if is_rtl else "Smart Cashier & POS Terminal",
        "pos_subtitle": "تسجيل الطلبات، إصدار الفواتير الفورية، والتحصيل المباشر" if is_rtl else "Fast order entry, instant receipt printing, and live checkout",
        "pos_manage_menu": "إدارة أصناف القائمة" if is_rtl else "Manage Menu Items",
        "pos_search_ph": "ابحث عن وجبة أو مشروب…" if is_rtl else "Search meal or beverage…",
        "pos_cart_details": "تفاصيل الفاتورة والحساب" if is_rtl else "Invoice & Bill Details",
        "pos_checkout_btn": "إتمام الطلب والدفع" if is_rtl else "Complete Order & Checkout",

        "kds_title": "شاشات المطبخ الذكية (KDS)" if is_rtl else "Smart Kitchen Display System (KDS)",
        "kds_subtitle": "تتبع فوري لأوامر الطهي والتحضير بالمطابخ والأقسام" if is_rtl else "Real-time kitchen order tickets, timers, and cooking workflow",

        "branch_title": "إدارة الفروع والمواقع" if is_rtl else "Manage Branches & Locations",
        "branch_subtitle": "شبكة الفروع والمواقع التشغيلية" if is_rtl else "Operational Branches & Locations Network",

        "inv_title": "المستودعات والمخزون" if is_rtl else "Inventory & Warehouses",
        "inv_subtitle": "إدارة المخزون والمستودعات" if is_rtl else "Inventory & Stock Management",

        "emp_title": "الموظفون والرواتب" if is_rtl else "Staff & Payroll",
        "emp_subtitle": "إدارة الكادر والمسميات الوظيفية والصلاحيات" if is_rtl else "Manage Staff, Job Roles & Permissions",

        "sub_title": "الاشتراك والتقارير المالية" if is_rtl else "Subscription & Financial Reports",
        "sub_subtitle": "إدارة الاشتراك واستهلاك الحساب" if is_rtl else "Manage Subscription & Account Consumption",

        "plat_title": "لوحة الإدارة المركزية للمنصة (SaaS Superadmin)" if is_rtl else "SaaS Platform Central Management",
        "plat_subtitle": "إدارة المطاعم المشتركة، الباقات والاشتراكات، والتحكم بالمنظومة" if is_rtl else "Manage subscribed restaurants, plans & subscriptions, and platform controls",

        "cc_title": "الكول سنتر — منظومة كورا" if is_rtl else "Call Center — KURA Dining OS",
        "cc_heading": "الكول سنتر وخدمة العملاء" if is_rtl else "Call Center & Customer Care",
        "cc_subtitle": "استقبال اتصالات الزبائن، البحث الفوري عن العملاء، وتسجيل طلبات التوصيل" if is_rtl else "Incoming customer calls, rapid customer lookup, and delivery order dispatch",
        "cc_lines_ready": "الخطوط جاهزة لاستقبال الاتصالات" if is_rtl else "Lines Ready for Inbound Calls",

        "deliv_title": "إدارة التوصيل — منظومة كورا" if is_rtl else "Delivery Fleet — KURA Dining OS",
        "deliv_heading": "إدارة وتوزيع طلبات التوصيل" if is_rtl else "Delivery Dispatch & Fleet Management",
        "deliv_subtitle": "متابعة مسار الطلبات خطوة بخطوة وتوزيعها على أسطول السائقين" if is_rtl else "Step-by-step order tracking and live driver fleet dispatching",

        "hq_orders_title": "سجل كافة الطلبات والفواتير — الإدارة العامة" if is_rtl else "Chain Orders & Invoices — Central HQ",
        "hq_orders_heading": "سجل كافة الطلبات والفواتير الموحد" if is_rtl else "Unified Orders & Invoices Record",
        "hq_orders_subtitle": "متابعة مباشرة لتدفق طلبات وفواتير كافة الفروع في شاشة واحدة" if is_rtl else "Live monitoring of incoming orders and bills across all branches in one screen",
    }

    # Safe lookup dictionary that provides translations for any string
    class SafeI18nDict(dict):
        def __init__(self, data, rtl):
            super().__init__(data)
            self._is_rtl = rtl

        def __getitem__(self, key):
            if key in self:
                return super().__getitem__(key)
            if self._is_rtl:
                return key
            return I18N_CATALOG.get(key, key)

        def get(self, key, default=None):
            if key in self:
                return super().get(key, default)
            if self._is_rtl:
                return key
            return I18N_CATALOG.get(key, default if default is not None else key)

    t = SafeI18nDict(base_t, is_rtl)

    return {
        "CURRENT_LANG": lang,
        "IS_RTL": is_rtl,
        "DIR": "rtl" if is_rtl else "ltr",
        "OPPOSITE_DIR": "ltr" if is_rtl else "rtl",
        "ALIGN_START": "right" if is_rtl else "left",
        "ALIGN_END": "left" if is_rtl else "right",
        "t": t,
    }
