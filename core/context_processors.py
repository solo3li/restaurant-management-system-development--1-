from django.utils import translation
from .models import Tenant, Branch, UserProfile, RESTAURANT_PERMISSIONS
from .i18n_catalog import I18N_CATALOG


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
    if f_set & {"call_center", "ai_call_center"}:
        f_set.add("call_center")
        f_set.add("ai_call_center")
    if f_set & {"custom_roles", "manage_roles"}:
        f_set.add("custom_roles")
        f_set.add("manage_roles")
    return f_set


def branch_context(request):
    if not request.user.is_authenticated:
        return {}

    profile = getattr(request.user, "profile", None)
    tenant = getattr(request, "tenant", None) or (profile.tenant if profile else None)
    is_platform_admin = getattr(request, "is_platform_admin", False)

    # Scoped branches for the active tenant
    if tenant:
        all_branches = Branch.objects.filter(tenant=tenant, status="active").order_by("id")
    elif is_platform_admin:
        all_branches = Branch.objects.filter(status="active").order_by("id")
    else:
        all_branches = Branch.objects.none()

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

        # Expand synonyms for seamless template access across granular and legacy keys
        expanded = set(user_perms)
        synonyms = [
            ("manage_branches", "branch_manage_branches"),
            ("manage_roles", "system_manage_roles"),
            ("view_hq_dashboard", "hq_view_master_dashboard"),
            ("view_branch_dashboard", "branch_view_dashboard"),
            ("cancel_orders", "pos_cancel_order"),
        ]
        for a, b in synonyms:
            if a in user_perms:
                expanded.add(b)
            if b in user_perms:
                expanded.add(a)
        # Implied read access
        if "manage_menu" in user_perms:
            expanded.add("menu_view")
        if "manage_inventory" in user_perms:
            expanded.add("inventory_view")
        if "manage_employees" in user_perms:
            expanded.add("hr_view_employees")
        if (
            "finance_view_sales" in user_perms
            or "finance_view_reports" in user_perms
            or "finance_view_profit_loss" in user_perms
        ):
            expanded.add("view_financials")
        user_perms = expanded

    # Filter by subscription plan features
    if tenant and tenant.subscription_plan and not is_platform_admin:
        plan_features = normalize_plan_features(tenant.subscription_plan.features)
        if "call_center" not in plan_features:
            user_perms.discard("call_center_access")
            user_perms.discard("call_center_create_order")
            user_perms.discard("call_center_manage_ai")
            user_perms.discard("call_center_view_logs")
            user_perms.discard("call_center_view_customers")
        if "inventory" not in plan_features:
            user_perms.discard("manage_inventory")
            user_perms.discard("inventory_view")
            user_perms.discard("inventory_add_stock")
            user_perms.discard("inventory_adjust_stock")
            user_perms.discard("inventory_record_waste")
            user_perms.discard("inventory_transfer_stock")
            user_perms.discard("inventory_manage_suppliers")
        if "custom_roles" not in plan_features and "manage_roles" not in plan_features:
            user_perms.discard("manage_roles")
            user_perms.discard("system_manage_roles")
        if "delivery_management" not in plan_features and "delivery_zones" not in plan_features and "delivery" not in plan_features:
            user_perms.discard("delivery_access")
            user_perms.discard("delivery_assign_driver")
            user_perms.discard("delivery_track_drivers")
            user_perms.discard("delivery_manage_zones")
            user_perms.discard("delivery_override_status")
        if "kds" not in plan_features and "kds_kitchen" not in plan_features:
            user_perms.discard("kds_access")
            user_perms.discard("kds_update_status")
            user_perms.discard("kds_recall_order")
            user_perms.discard("kds_pause_item")

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
        active_id = request.session.get("active_branch_id") if hasattr(request, "session") else None
        if active_id in ["all", "0", 0, None]:
            current_branch = None
        elif active_id and tenant:
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

        plan_code = tenant.subscription_plan.code if tenant.subscription_plan else ""
        plan_name = tenant.subscription_plan.name if tenant.subscription_plan else ""
        plan_name_en_map = {
            "starter": "Starter Plan",
            "growth": "Growth Plan",
            "enterprise": "Enterprise Plan",
            "trial": "Free Trial Plan",
            "basic": "Basic Plan",
            "pro": "Pro Plan",
        }
        plan_name_en = plan_name_en_map.get(plan_code, I18N_CATALOG.get(plan_name, plan_name))

        tenant_subscription = {
            "plan": tenant.subscription_plan,
            "subscription_plan": tenant.subscription_plan,
            "plan_name": plan_name,
            "plan_name_en": plan_name_en,
            "status": tenant.subscription_status,
            "status_display": tenant.get_subscription_status_display(),
            "billing_cycle": tenant.get_billing_cycle_display(),
            "end_date": tenant.subscription_end,
            "days_left": tenant.days_until_expiry(),
            "is_active": tenant.is_subscription_active(),
            "is_expiring_soon": (tenant.days_until_expiry() <= 7) if tenant.subscription_end else False,
            "max_branches": tenant.subscription_plan.max_branches if tenant.subscription_plan else 1,
            "branches_count": tenant.branches.filter(status="active").count(),
            "max_employees": tenant.subscription_plan.max_employees if tenant.subscription_plan else 5,
            "employees_count": tenant.employees.filter(status__in=["active", "vacation"]).count(),
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
    and a rich multi-language translation dictionary (Arabic, English, French, Turkish, German).
    """
    lang = None
    query_lang = request.GET.get("lang") if hasattr(request, "GET") else None
    supported_langs = ["ar", "en", "fr", "tr", "de"]
    if query_lang in supported_langs:
        lang = query_lang
        if hasattr(request, "session"):
            request.session["django_language"] = lang
            request.session["_language"] = lang
        translation.activate(lang)
    elif hasattr(request, "LANGUAGE_CODE") and request.LANGUAGE_CODE:
        lang = request.LANGUAGE_CODE
    elif hasattr(request, "session") and request.session.get("django_language"):
        lang = request.session.get("django_language")
    elif request.COOKIES.get("django_language"):
        lang = request.COOKIES.get("django_language")
    else:
        lang = translation.get_language() or "ar"

    if "-" in lang:
        lang = lang.split("-")[0]
    if lang not in supported_langs:
        lang = "ar"

    from .i18n_catalog import I18N_CATALOG, get_translation

    is_rtl = (lang == "ar")

    # Dynamic currency resolution based on active branch or active tenant
    currency_sym = "ر.س" if is_rtl else "SAR"
    try:
        t_obj = getattr(request, "tenant", None)
        b_obj = None
        if hasattr(request, "user") and request.user.is_authenticated:
            profile = getattr(request.user, "profile", None)
            if not t_obj and profile:
                t_obj = profile.tenant
            if not t_obj and hasattr(request, "session"):
                t_id = request.session.get("active_tenant_id")
                if t_id:
                    t_obj = Tenant.objects.filter(id=t_id).first()

            if hasattr(request, "session"):
                b_id = request.session.get("active_branch_id")
                if b_id:
                    b_obj = Branch.objects.filter(id=b_id).first()
            if not b_obj and profile:
                b_obj = profile.branch
            if not b_obj and hasattr(request.user, "employee_profile") and request.user.employee_profile:
                b_obj = request.user.employee_profile.branch

        if b_obj and hasattr(b_obj, "get_currency_symbol_ar"):
            currency_sym = b_obj.get_currency_symbol_ar() if is_rtl else b_obj.get_currency_symbol_en()
        elif t_obj and hasattr(t_obj, "get_currency_symbol_ar"):
            currency_sym = t_obj.get_currency_symbol_ar() if is_rtl else t_obj.get_currency_symbol_en()
    except Exception:
        pass

    def pick_lang(ar_text, en_text, fr_text=None, tr_text=None, de_text=None):
        if lang == "ar":
            return ar_text
        if lang == "fr":
            return fr_text or en_text
        if lang == "tr":
            return tr_text or en_text
        if lang == "de":
            return de_text or en_text
        return en_text

    base_t = {
        # App & Brand
        "app_title": pick_lang("منظومة مطاعم السحابية", "Motaem Restaurant OS", "Système d'exploitation Motaem Restaurant", "Motaem Restoran Bulut İşletim Sistemi", "Motaem Restaurant Cloud-Betriebssystem"),
        "brand_name": pick_lang("مطاعم", "Motaem", "Motaem", "Motaem", "Motaem"),
        "brand_hq": "HQ",
        "brand_subtitle": pick_lang("نظام إدارة المطاعم", "Restaurant Management System", "Système de gestion de restaurant", "Restoran Yönetim Sistemi", "Restaurant-Management-System"),
        "brand_tagline": pick_lang("النظام السحابي لإدارة سلاسل المطاعم والضيافة الحديثة", "Cloud Operating System for Hospitality & Dining", "Système d'exploitation cloud pour la restauration et l'hôtellerie", "Restoran ve Ağırlama İçin Bulut İşletim Sistemi", "Cloud-Betriebssystem für Gastronomie & Restaurants"),
        "online_system": pick_lang("متصل بالنظام السحابي", "Connected to Cloud OS", "Connecté au système cloud", "Bulut Sistemine Bağlı", "Mit Cloud-System verbunden"),
        "all_branches_label": pick_lang("الإدارة العامة (كافة الفروع)", "Central HQ (All Branches)", "Siège central (Toutes les succursales)", "Genel Merkez (Tüm Şubeler)", "Hauptsitz (Alle Filialen)"),
        "branch_prefix": pick_lang("فرع", "Branch", "Succursale", "Şube", "Filiale"),

        # Navigation
        "nav_dashboard": pick_lang("لوحة الإدارة العامة (HQ)", "HQ Central Dashboard", "Tableau de bord central HQ", "Genel Merkez Paneli", "HQ-Zentral-Dashboard"),
        "nav_branch_dashboard": pick_lang("لوحة تشغيل الفرع", "Branch Operations", "Opérations de succursale", "Şube Operasyonları", "Filialbetrieb"),
        "nav_branches": pick_lang("إدارة الفروع والمواقع", "Branches & Locations", "Succursales & Emplacements", "Şubeler ve Konumlar", "Filialen & Standorte"),
        "nav_all_branches": pick_lang("كافة الفروع والمدن", "All Branches & Cities", "Toutes les succursales", "Tüm Şubeler ve Şehirler", "Alle Filialen & Städte"),
        "nav_switch_hq": pick_lang("التحويل للإدارة العامة (HQ)", "Switch to HQ Mode", "Passer au mode HQ", "Genel Merkez Moduna Geç", "In den HQ-Modus wechseln"),
        "nav_pos_menu": pick_lang("نقاط البيع وقائمة الطعام", "POS & Menu", "PDV & Menu", "POS ve Menü", "POS & Speisekarte"),
        "nav_pos": pick_lang("كاشير نقطة البيع (POS)", "Cashier Point of Sale (POS)", "Caisse point de vente (PDV)", "Kasiyer Satış Noktası (POS)", "Kasse & POS"),
        "nav_menu": pick_lang("قائمة الأطباق والأسعار", "Menu Dishes & Pricing", "Menu et tarifs", "Menü ve Fiyatlandırma", "Speisekarte & Preise"),
        "nav_kitchen": pick_lang("شاشات المطبخ (KDS)", "Kitchen Displays (KDS)", "Écrans de cuisine (KDS)", "Mutfak Ekranları (KDS)", "Küchenanzeigen (KDS)"),
        "nav_ai_callcenter": pick_lang("كول سنتر الذكاء الاصطناعي", "AI Call Center", "Centre d'appels IA", "Yapay Zeka Çağrı Merkezi", "KI-Call-Center"),
        "nav_callcenter_live": pick_lang("مركز الاتصالات المباشر", "Live Call Center", "Centre d'appels en direct", "Canlı Çağrı Merkezi", "Live-Call-Center"),
        "nav_callcenter_mgmt": pick_lang("إعدادات المساعد الصوتي", "AI Voice Assistant Settings", "Paramètres de l'assistant vocal IA", "Yapay Zeka Sesli Asistan Ayarları", "KI-Sprachassistent-Einstellungen"),
        "nav_callcenter_overview": pick_lang("نظرة عامة وإحصائيات", "Overview & Stats", "Aperçu et statistiques", "Genel Bakış ve İstatistikler", "Übersicht & Statistiken"),
        "nav_callcenter_persona": pick_lang("شخصية المساعد واللهجة", "Persona & Voice", "Personnalité et voix", "Kişilik ve Ses", "Persönlichkeit & Stimme"),
        "nav_callcenter_hours": pick_lang("مواعيد العمل والاعتذار", "Working Hours", "Heures de travail", "Çalışma Saatleri", "Öffnungszeiten"),
        "nav_callcenter_knowledge": pick_lang("قاعدة المعرفة (RAG)", "Knowledge Base", "Base de connaissances (RAG)", "Bilgi Tabanı (RAG)", "Wissensdatenbank (RAG)"),
        "nav_callcenter_queues": pick_lang("طوابير وموظفو التحويل", "Queues & Agents", "Files d'attente et agents", "Kuyruklar ve Temsilciler", "Warteschlangen & Mitarbeiter"),
        "nav_callcenter_calls": pick_lang("سجل المكالمات والتسجيلات", "Call Logs & Audio", "Historique des appels", "Çağrı Kayıtları", "Anrufliste & Aufnahmen"),
        "nav_callcenter_capabilities": pick_lang("صلاحيات وقدرات الذكاء", "AI Capabilities & MCP", "Capacités de l'IA & MCP", "Yapay Zeka Yetenekleri ve MCP", "KI-Fähigkeiten & MCP"),
        "nav_callcenter_omnichannel": pick_lang("قنوات الاتصال والواتساب", "Omnichannel & WhatsApp", "Omnicanal & WhatsApp", "Çok Kanallı ve WhatsApp", "Omnichannel & WhatsApp"),
        "nav_inventory": pick_lang("المستودعات والمخزون", "Inventory & Warehouses", "Inventaire et stocks", "Envanter ve Depolar", "Warenlager & Inventar"),
        "nav_stock_audit": pick_lang("جرد المواد والمستودعات", "Stock Audit & Materials", "Inventaire des stocks", "Stok Sayımı ve Malzemeler", "Bestandsprüfung & Materialien"),
        "nav_delivery": pick_lang("أسطول التوصيل والمناديب", "Delivery Fleet & Drivers", "Flotte de livraison et livreurs", "Teslimat Filosu ve Kuryeler", "Lieferflotte & Fahrer"),
        "nav_orders": pick_lang("سجل كافة الطلبات والفواتير", "All Orders & Invoices", "Toutes les commandes et factures", "Tüm Siparişler ve Faturalar", "Alle Bestellungen & Rechnungen"),
        "nav_branch_orders": pick_lang("طلبات وفواتير الفرع", "Branch Orders & Invoices", "Commandes de la succursale", "Şube Siparişleri ve Faturaları", "Filialbestellungen & Rechnungen"),
        "nav_employees": pick_lang("الموظفون والرواتب", "Staff & Payroll", "Personnel et paie", "Personel ve Maaşlar", "Personal & Gehaltsabrechnung"),
        "nav_subscription": pick_lang("الاشتراك والتقارير المالية", "Subscription & Financials", "Abonnement et finances", "Abonelik ve Finansal Raporlar", "Abonnement & Finanzen"),
        "nav_general_admin": pick_lang("الإدارة العامة", "General Admin", "Administration générale", "Genel Yönetim", "Hauptverwaltung"),
        "nav_platform": pick_lang("إدارة منصة SaaS العامة", "SaaS Platform Admin", "Administration de la plateforme SaaS", "SaaS Platform Yöneticisi", "SaaS-Plattform-Administration"),
        "nav_django_admin": pick_lang("لوحة Django Admin", "Django Admin Console", "Console Django Admin", "Django Yönetici Paneli", "Django Admin-Konsole"),

        # Header & User Actions
        "profile": pick_lang("الملف الشخصي", "User Profile", "Profil utilisateur", "Kullanıcı Profili", "Benutzerprofil"),
        "logout": pick_lang("تسجيل الخروج", "Sign Out", "Déconnexion", "Çıkış Yap", "Abmelden"),
        "login": pick_lang("تسجيل الدخول", "Sign In", "Connexion", "Giriş Yap", "Anmelden"),
        "register": pick_lang("إنشاء حساب منشأة", "Register Restaurant", "Inscrire un restaurant", "Restoran Kaydet", "Restaurant registrieren"),
        "notifications": pick_lang("الإشعارات", "Notifications", "Notifications", "Bildirimler", "Benachrichtigungen"),
        "collapse_sidebar": pick_lang("تصغير / توسيع القائمة الجانبية (Ctrl + B)", "Collapse / Expand Sidebar (Ctrl + B)", "Réduire / Agrandir la barre latérale", "Kenar Çubuğunu Daralt / Genişlet", "Seitenleiste ein-/ausklappen"),
        "open_menu": pick_lang("فتح القائمة الرئيسية", "Open Main Menu", "Ouvrir le menu principal", "Ana Menüyü Aç", "Hauptmenü öffnen"),
        "live": pick_lang("مباشر", "LIVE", "EN DIRECT", "CANLI", "LIVE"),

        # Common Actions
        "save": pick_lang("حفظ", "Save", "Enregistrer", "Kaydet", "Speichern"),
        "cancel": pick_lang("إلغاء", "Cancel", "Annuler", "İptal", "Abbrechen"),
        "delete": pick_lang("حذف", "Delete", "Supprimer", "Sil", "Löschen"),
        "edit": pick_lang("تعديل", "Edit", "Modifier", "Düzenle", "Bearbeiten"),
        "create": pick_lang("إضافة جديد", "Add New", "Ajouter nouveau", "Yeni Ekle", "Neu hinzufügen"),
        "search": pick_lang("بحث...", "Search...", "Rechercher...", "Ara...", "Suchen..."),
        "filter": pick_lang("تصفية", "Filter", "Filtrer", "Filtrele", "Filtern"),
        "all": pick_lang("الكل", "All", "Tous", "Tümü", "Alle"),
        "close": pick_lang("إغلاق", "Close", "Fermer", "Kapat", "Schließen"),
        "back": pick_lang("رجوع", "Back", "Retour", "Geri", "Zurück"),
        "confirm": pick_lang("تأكيد", "Confirm", "Confirmer", "Onayla", "Bestätigen"),
        "print": pick_lang("طباعة", "Print", "Imprimer", "Yazdır", "Drucken"),
        "export": pick_lang("تصدير", "Export", "Exporter", "Dışa Aktar", "Exportieren"),
        "refresh": pick_lang("تحديث", "Refresh", "Actualiser", "Yenile", "Aktualisieren"),
        "details": pick_lang("التفاصيل", "Details", "Détails", "Ayrıntılar", "Details"),
        "actions": pick_lang("الإجراءات", "Actions", "Actions", "İşlemler", "Aktionen"),

        # Common Statuses & Financials
        "status": pick_lang("الحالة", "Status", "Statut", "Durum", "Status"),
        "active": pick_lang("نشط", "Active", "Actif", "Aktif", "Aktiv"),
        "inactive": pick_lang("معطل", "Inactive", "Inactif", "Pasif", "Inaktiv"),
        "pending": pick_lang("قيد المراجعة", "Pending", "En attente", "Beklemede", "Ausstehend"),
        "approved": pick_lang("تمت الموافقة", "Approved", "Approuvé", "Onaylandı", "Genehmigt"),
        "rejected": pick_lang("مرفوض", "Rejected", "Rejeté", "Reddedildi", "Abgelehnt"),
        "completed": pick_lang("مكتمل", "Completed", "Terminé", "Tamamlandı", "Abgeschlossen"),
        "cancelled": pick_lang("ملغي", "Cancelled", "Annulé", "İptal Edildi", "Storniert"),
        "currency": currency_sym,
        "total": pick_lang("الإجمالي", "Total", "Total", "Toplam", "Gesamt"),
        "subtotal": pick_lang("المجموع الفرعي", "Subtotal", "Sous-total", "Ara Toplam", "Zwischensumme"),
        "vat": pick_lang("ضريبة القيمة المضافة (15%)", "VAT (15%)", "TVA (15%)", "KDV (%15)", "MwSt. (15%)"),
        "discount": pick_lang("الخصم", "Discount", "Remise", "İndirim", "Rabatt"),
        "quantity": pick_lang("الكمية", "Qty", "Qté", "Adet", "Menge"),
        "price": pick_lang("السعر", "Price", "Prix", "Fiyat", "Preis"),
        "date": pick_lang("التاريخ", "Date", "Date", "Tarih", "Datum"),
        "notes": pick_lang("الملاحظات", "Notes", "Remarques", "Notlar", "Notizen"),

        # POS & KDS
        "cashier": pick_lang("الكاشير", "Cashier", "Caisse", "Kasiyer", "Kasse"),
        "dine_in": pick_lang("محلي", "Dine-In", "Sur place", "Restoranda", "Im Restaurant"),
        "takeaway": pick_lang("سفري", "Takeaway", "À emporter", "Paket Servis", "Zum Mitnehmen"),
        "delivery_type": pick_lang("توصيل", "Delivery", "Livraison", "Teslimat", "Lieferung"),
        "cash": pick_lang("نقداً", "Cash", "Espèces", "Nakit", "Barzahlung"),
        "card": pick_lang("شبكة / مدى", "Card / Mada", "Carte bancaire", "Banka Kartı", "Kartenzahlung"),
        "order_num": pick_lang("طلب رقم", "Order #", "Commande n°", "Sipariş No", "Bestellung Nr."),
        "cooking": pick_lang("قيد الطهي", "Cooking", "En cuisson", "Pişiriliyor", "In Zubereitung"),
        "ready": pick_lang("جاهز للاستلام", "Ready", "Prêt", "Hazır", "Fertig"),
        "on_the_way": pick_lang("في الطريق", "On The Way", "En route", "Yolda", "Unterwegs"),

        # Languages
        "language_arabic": "العربية",
        "language_english": "English",
        "language_french": "Français",
        "language_turkish": "Türkçe",
        "language_german": "Deutsch",
        "switch_to_arabic": "التبديل إلى العربية",
        "switch_to_english": "Switch to English",
        "switch_to_french": "Passer au français",
        "switch_to_turkish": "Türkçe'ye Geç",
        "switch_to_german": "Zu Deutsch wechseln",
        "select_language": pick_lang("اختيار اللغة", "Select Language", "Choisir la langue", "Dil Seçin", "Sprache wählen"),

        # Operational Domains
        "dash_command_center": pick_lang("مركز القيادة والعمليات", "Command & Operations Center", "Centre de commandement et d'opérations", "Komuta ve Operasyon Merkezi", "Kommando- und Betriebszentrum"),
        "dash_subtitle": pick_lang("متابعة حية للتدفق المالي، توزيع الطلبات، أداء الفروع، وكول سنتر الذكاء الاصطناعي في شاشة موحدة.", "Live monitoring of cash flow, order distribution, branch performance, and AI Call Center.", "Suivi en direct des flux de trésorerie, de la répartition des commandes, des performances des succursales et du centre d'appels IA.", "Nakit akışı, sipariş dağılımı, şube performansı ve Yapay Zeka Çağrı Merkezi canlı takibi.", "Live-Überwachung von Cashflow, Auftragsverteilung, Filialleistung und KI-Call-Center auf einem Bildschirm."),
        "dash_unified_system": pick_lang("النظام الموحد للإدارة العليا", "Unified Executive Management System", "Système unifié de gestion exécutive", "Birleşik Üst Düzey Yönetim Sistemi", "Einheitliches Führungsinformationssystem"),
        "dash_live_monitoring": pick_lang("متابعة فورية ومباشرة لكافة الفروع", "Live Real-Time Monitoring of All Branches", "Surveillance en temps réel de toutes les succursales", "Tüm Şubelerin Anlık Canlı Takibi", "Echtzeit-Überwachung aller Filialen"),
        "dash_chain_sales_today": pick_lang("إجمالي مبيعات السلسلة اليوم", "Total Chain Revenue Today", "Revenu total de la chaîne aujourd'hui", "Zincirin Bugünkü Toplam Geliri", "Gesamter Kettenumsatz heute"),
        "dash_net_revenue": pick_lang("صافي الإيراد المحصل", "Net Collected Revenue", "Revenu net collecté", "Net Tahsil Edilen Gelir", "Eingenommener Nettoerlös"),
        "dash_completed_orders": pick_lang("عدد الطلبات المكتملة", "Completed Orders Count", "Nombre de commandes terminées", "Tamamlanan Sipariş Sayısı", "Abgeschlossene Bestellungen"),
        "dash_active_orders": pick_lang("الطلبات النشطة حالياً", "Currently Active Orders", "Commandes actuellement actives", "Şu Anda Aktif Siparişler", "Aktuell aktive Bestellungen"),
        "dash_branches_performance": pick_lang("أداء الفروع المباشر", "Live Branch Performance", "Performance en direct des succursales", "Canlı Şube Performansı", "Live-Filialleistung"),
        "dash_sales_by_channel": pick_lang("توزيع المبيعات حسب القنوات", "Sales Distribution by Channel", "Distribution des ventes par canal", "Kanallara Göre Satış Dağılımı", "Umsatzverteilung nach Kanälen"),
        "dash_top_dishes": pick_lang("أكثر الأطباق طلباً بالسلسلة", "Top Selling Dishes Across Chain", "Plats les plus vendus de la chaîne", "Zincirde En Çok Satan Yemekler", "Meistverkaufte Gerichte der Kette"),
        "dash_sales_last_7_days": pick_lang("مبيعات آخر 7 أيام", "Sales - Last 7 Days", "Ventes des 7 derniers jours", "Son 7 Günlük Satışlar", "Umsatz der letzten 7 Tage"),

        "pos_title": pick_lang("الكاشير — نقطة البيع الذكية", "Smart Cashier & POS Terminal", "Caisse intelligente et terminal PDV", "Akıllı Kasiyer ve POS Terminali", "Intelligente Kasse & POS-Terminal"),
        "pos_subtitle": pick_lang("تسجيل الطلبات، إصدار الفواتير الفورية، والتحصيل المباشر", "Fast order entry, instant receipt printing, and live checkout", "Prise de commande rapide, impression de reçus et encaissement en direct", "Hızlı sipariş girişi, anında fiş yazdırma ve canlı ödeme", "Schnelle Auftragserfassung, Sofortbelegdruck und Live-Kassierung"),
        "pos_manage_menu": pick_lang("إدارة أصناف القائمة", "Manage Menu Items", "Gérer les éléments du menu", "Menü Öğelerini Yönet", "Menüelemente verwalten"),
        "pos_search_ph": pick_lang("ابحث عن وجبة أو مشروب…", "Search meal or beverage…", "Rechercher un plat ou une boisson…", "Yemek veya içecek ara…", "Gericht oder Getränk suchen…"),
        "pos_cart_details": pick_lang("تفاصيل الفاتورة والحساب", "Invoice & Bill Details", "Détails de la facture", "Fatura ve Hesap Ayrıntıları", "Rechnungsdetails"),
        "pos_checkout_btn": pick_lang("إتمام الطلب والدفع", "Complete Order & Checkout", "Finaliser la commande et payer", "Siparişi Tamamla ve Öde", "Bestellung abschließen & bezahlen"),

        "kds_title": pick_lang("شاشات المطبخ الذكية (KDS)", "Smart Kitchen Display System (KDS)", "Système d'affichage de cuisine intelligent (KDS)", "Akıllı Mutfak Ekran Sistemi (KDS)", "Intelligentes Küchenanzeigesystem (KDS)"),
        "kds_subtitle": pick_lang("تتبع فوري لأوامر الطهي والتحضير بالمطابخ والأقسام", "Real-time kitchen order tickets, timers, and cooking workflow", "Tickets de commande en temps réel, minuteurs et flux de cuisson", "Gerçek zamanlı mutfak sipariş fişleri, zamanlayıcılar ve pişirme akışı", "Echtzeit-Küchenbestellscheine, Timer und Zubereitungsablauf"),

        "branch_title": pick_lang("إدارة الفروع والمواقع", "Manage Branches & Locations", "Gérer les succursales et emplacements", "Şubeleri ve Konumları Yönet", "Filialen & Standorte verwalten"),
        "branch_subtitle": pick_lang("شبكة الفروع والمواقع التشغيلية", "Operational Branches & Locations Network", "Réseau opérationnel de succursales", "Operasyonel Şubeler ve Konumlar Ağı", "Betriebsfilialen & Standortnetzwerk"),

        "inv_title": pick_lang("المستودعات والمخزون", "Inventory & Warehouses", "Inventaire et stocks", "Envanter ve Depolar", "Warenlager & Inventar"),
        "inv_subtitle": pick_lang("إدارة المخزون والمستودعات", "Inventory & Stock Management", "Gestion des stocks et entrepôts", "Envanter ve Stok Yönetimi", "Inventar- & Lagerverwaltung"),

        "emp_title": pick_lang("الموظفون والرواتب", "Staff & Payroll", "Personnel et paie", "Personel ve Maaşlar", "Personal & Gehaltsabrechnung"),
        "emp_subtitle": pick_lang("إدارة الكادر والمسميات الوظيفية والصلاحيات", "Manage Staff, Job Roles & Permissions", "Gérer le personnel, les rôles et permissions", "Personeli, Görevleri ve Yetkileri Yönet", "Mitarbeiter, Rollen & Berechtigungen verwalten"),

        "sub_title": pick_lang("الاشتراك والتقارير المالية", "Subscription & Financial Reports", "Abonnement et rapports financiers", "Abonelik ve Finansal Raporlar", "Abonnement & Finanzberichte"),
        "sub_subtitle": pick_lang("إدارة الاشتراك واستهلاك الحساب", "Manage Subscription & Account Consumption", "Gérer l'abonnement et la consommation du compte", "Abonelik ve Hesap Tüketimini Yönet", "Abonnement & Kontoverbrauch verwalten"),

        "plat_title": pick_lang("لوحة الإدارة المركزية للمنصة (SaaS Superadmin)", "SaaS Platform Central Management", "Gestion centrale de la plateforme SaaS", "SaaS Platformu Merkezi Yönetimi", "Zentrale Verwaltung der SaaS-Plattform"),
        "plat_subtitle": pick_lang("إدارة المطاعم المشتركة، الباقات والاشتراكات، والتحكم بالمنظومة", "Manage subscribed restaurants, plans & subscriptions, and platform controls", "Gérer les restaurants abonnés, plans et paramètres", "Abone restoranları, planları ve platform kontrollerini yönet", "Abonnierte Restaurants, Tarife und Plattformsteuerungen verwalten"),

        "cc_title": pick_lang("الكول سنتر — منظومة كورا", "Call Center — KURA Dining OS", "Centre d'appels — KURA Dining OS", "Çağrı Merkezi — KURA Dining OS", "Call-Center — KURA Dining OS"),
        "cc_heading": pick_lang("الكول سنتر وخدمة العملاء", "Call Center & Customer Care", "Centre d'appels et service client", "Çağrı Merkezi ve Müşteri Hizmetleri", "Call-Center & Kundenservice"),
        "cc_subtitle": pick_lang("استقبال اتصالات الزبائن، البحث الفوري عن العملاء، وتسجيل طلبات التوصيل", "Incoming customer calls, rapid customer lookup, and delivery order dispatch", "Appels clients entrants, recherche rapide de clients et expédition des livraisons", "Gelen müşteri çağrıları, hızlı müşteri arama ve teslimat siparişi kaydı", "Eingehende Kundenanrufe, schnelle Kundensuche und Lieferbestellungsaufgabe"),
        "cc_lines_ready": pick_lang("الخطوط جاهزة لاستقبال الاتصالات", "Lines Ready for Inbound Calls", "Lignes prêtes pour les appels entrants", "Hatlar Gelen Aramalar İçin Hazır", "Leitungen bereit für eingehende Anrufe"),

        "deliv_title": pick_lang("إدارة التوصيل — منظومة كورا", "Delivery Fleet — KURA Dining OS", "Flotte de livraison — KURA Dining OS", "Teslimat Filosu — KURA Dining OS", "Lieferflotte — KURA Dining OS"),
        "deliv_heading": pick_lang("إدارة وتوزيع طلبات التوصيل", "Delivery Dispatch & Fleet Management", "Gestion de la flotte et répartition des livraisons", "Teslimat Dağıtımı ve Filo Yönetimi", "Lieferdisposition & Flottenmanagement"),
        "deliv_subtitle": pick_lang("متابعة مسار الطلبات خطوة بخطوة وتوزيعها على أسطول السائقين", "Step-by-step order tracking and live driver fleet dispatching", "Suivi des commandes étape par étape et répartition des chauffeurs", "Adım adım sipariş takibi ve canlı sürücü filosu sevkiyatı", "Schritt-für-Schritt-Auftragsverfolgung und Live-Fahrerflottendisposition"),

        "hq_orders_title": pick_lang("سجل كافة الطلبات والفواتير — الإدارة العامة", "Chain Orders & Invoices — Central HQ", "Commandes et factures de la chaîne — Siège central", "Zincir Siparişleri ve Faturaları — Genel Merkez", "Kettenbestellungen & Rechnungen — Hauptsitz"),
        "hq_orders_heading": pick_lang("سجل كافة الطلبات والفواتير الموحد", "Unified Orders & Invoices Record", "Registre unifié des commandes et factures", "Birleşik Siparişler ve Faturalar Kaydı", "Einheitliches Bestell- & Rechnungsregister"),
        "hq_orders_subtitle": pick_lang("متابعة مباشرة لتدفق طلبات وفواتير كافة الفروع في شاشة واحدة", "Live monitoring of incoming orders and bills across all branches in one screen", "Suivi en direct des commandes et factures de toutes les succursales", "Tüm şubelerdeki sipariş ve fatura akışının tek ekranda canlı takibi", "Live-Überwachung von Bestellungen und Rechnungen aller Filialen auf einem Bildschirm"),
    }

    # Safe lookup dictionary that provides translations for any string
    class SafeI18nDict(dict):
        def __init__(self, data, active_lang):
            super().__init__(data)
            self._lang = active_lang
            self._is_rtl = (active_lang == "ar")

        def __getitem__(self, key):
            if key in self:
                return super().__getitem__(key)
            if self._is_rtl:
                return key
            return get_translation(key, self._lang, default=key)

        def get(self, key, default=None):
            if key in self:
                return super().get(key, default)
            if self._is_rtl:
                return key
            fallback = default if default is not None else key
            return get_translation(key, self._lang, default=fallback)

    t = SafeI18nDict(base_t, lang)

    lang_names = {
        "ar": "العربية",
        "en": "English",
        "fr": "Français",
        "tr": "Türkçe",
        "de": "Deutsch",
    }
    lang_flags = {
        "ar": "🇸🇦",
        "en": "🇬🇧",
        "fr": "🇫🇷",
        "tr": "🇹🇷",
        "de": "🇩🇪",
    }

    languages_list = [
        {"code": "ar", "name": "العربية", "flag": "🇸🇦", "is_active": (lang == "ar")},
        {"code": "en", "name": "English", "flag": "🇬🇧", "is_active": (lang == "en")},
        {"code": "fr", "name": "Français", "flag": "🇫🇷", "is_active": (lang == "fr")},
        {"code": "tr", "name": "Türkçe", "flag": "🇹🇷", "is_active": (lang == "tr")},
        {"code": "de", "name": "Deutsch", "flag": "🇩🇪", "is_active": (lang == "de")},
    ]

    return {
        "CURRENT_LANG": lang,
        "CURRENT_LANGUAGE": lang,
        "LANG_CODE": lang,
        "LANGUAGE_CODE": lang,
        "CURRENT_LANG_NAME": lang_names.get(lang, "العربية"),
        "CURRENT_LANG_FLAG": lang_flags.get(lang, "🇸🇦"),
        "LANGUAGES_LIST": languages_list,
        "IS_RTL": is_rtl,
        "DIR": "rtl" if is_rtl else "ltr",
        "OPPOSITE_DIR": "ltr" if is_rtl else "rtl",
        "ALIGN_START": "right" if is_rtl else "left",
        "ALIGN_END": "left" if is_rtl else "right",
        "t": t,
    }
