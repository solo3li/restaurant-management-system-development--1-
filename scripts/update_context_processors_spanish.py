#!/usr/bin/env python3
"""
Update core/context_processors.py with full 6-language support including Spanish (es).
Line-by-line safe replacement.
"""

target_file = '/root/motaem/core/context_processors.py'
with open(target_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

SPANISH_BASE_T = {
    # App & Brand
    "app_title": 'pick_lang("منظومة مطاعم السحابية", "Motaem Restaurant OS", "Système d\'exploitation Motaem Restaurant", "Motaem Restoran Bulut İşletim Sistemi", "Motaem Restaurant Cloud-Betriebssystem", "Sistema Operativo en la Nube Motaem Restaurant")',
    "brand_name": 'pick_lang("مطاعم", "Motaem", "Motaem", "Motaem", "Motaem", "Motaem")',
    "brand_subtitle": 'pick_lang("نظام إدارة المطاعم السحابي", "Cloud Restaurant OS", "Système d\'exploitation cloud pour restaurants", "Bulut Restoran İşletim Sistemi", "Cloud-Restaurant-Betriebssystem", "Sistema de Gestión de Restaurantes en la Nube")',
    "brand_tagline": 'pick_lang("النظام السحابي لإدارة سلاسل المطاعم والضيافة الحديثة", "Cloud Operating System for Hospitality & Dining", "Système d\'exploitation cloud pour la restauration et l\'hôtellerie", "Restoran ve Ağırlama İçin Bulut İşletim Sistemi", "Cloud-Betriebssystem für Gastronomie & Restaurants", "Sistema operativo en la nube para cadenas de restaurantes y hostelería")',
    "online_system": 'pick_lang("متصل بالنظام السحابي", "Connected to Cloud OS", "Connecté au système cloud", "Bulut Sistemine Bağlı", "Mit Cloud-System verbunden", "Conectado al sistema en la nube")',
    "all_branches_label": 'pick_lang("الإدارة العامة (كافة الفروع)", "Central HQ (All Branches)", "Siège central (Toutes les succursales)", "Genel Merkez (Tüm Şubeler)", "Hauptsitz (Alle Filialen)", "Sede Central (Todas las sucursales)")',
    "branch_prefix": 'pick_lang("فرع", "Branch", "Succursale", "Şube", "Filiale", "Sucursal")',

    # Navigation
    "nav_dashboard": 'pick_lang("لوحة الإدارة العامة (HQ)", "HQ Central Dashboard", "Tableau de bord central HQ", "Genel Merkez Paneli", "HQ-Zentral-Dashboard", "Panel Central de Control (HQ)")',
    "nav_branch_dashboard": 'pick_lang("لوحة تشغيل الفرع", "Branch Operations", "Opérations de succursale", "Şube Operasyonları", "Filialbetrieb", "Operaciones de la Sucursal")',
    "nav_branches": 'pick_lang("إدارة الفروع والمواقع", "Branches & Locations", "Succursales & Emplacements", "Şubeler ve Konumlar", "Filialen & Standorte", "Sucursales y Ubicaciones")',
    "nav_all_branches": 'pick_lang("كافة الفروع والمدن", "All Branches & Cities", "Toutes les succursales", "Tüm Şubeler ve Şehirler", "Alle Filialen & Städte", "Todas las Sucursales y Ciudades")',
    "nav_switch_hq": 'pick_lang("التحويل للإدارة العامة (HQ)", "Switch to HQ Mode", "Passer au mode HQ", "Genel Merkez Moduna Geç", "In den HQ-Modus wechseln", "Cambiar al Modo Sede Central (HQ)")',
    "nav_pos_menu": 'pick_lang("نقاط البيع وقائمة الطعام", "POS & Menu", "PDV & Menu", "POS ve Menü", "POS & Speisekarte", "TPV y Carta")',
    "nav_pos": 'pick_lang("كاشير نقطة البيع (POS)", "Cashier Point of Sale (POS)", "Caisse point de vente (PDV)", "Kasiyer Satış Noktası (POS)", "Kasse & POS", "Caja Punto de Venta (TPV)")',
    "nav_menu": 'pick_lang("قائمة الأطباق والأسعار", "Menu Dishes & Pricing", "Menu et tarifs", "Menü ve Fiyatlandırma", "Speisekarte & Preise", "Carta de Platos y Precios")',
    "nav_kitchen": 'pick_lang("شاشات المطبخ (KDS)", "Kitchen Displays (KDS)", "Écrans de cuisine (KDS)", "Mutfak Ekranları (KDS)", "Küchenanzeigen (KDS)", "Pantallas de Cocina (KDS)")',
    "nav_ai_callcenter": 'pick_lang("كول سنتر الذكاء الاصطناعي", "AI Call Center", "Centre d\'appels IA", "Yapay Zeka Çağrı Merkezi", "KI-Call-Center", "Call Center con Inteligencia Artificial")',
    "nav_callcenter_orders": 'pick_lang("استقبال طلبات الفروع", "Branch Order Entry", "Prise de commandes succursales", "Şube Sipariş Alımı", "Filial-Bestellannahme", "Recepción de Pedidos de Sucursales")',
    "nav_callcenter_live": 'pick_lang("استقبال طلبات الفروع", "Branch Order Entry", "Prise de commandes succursales", "Şube Sipariş Alımı", "Filial-Bestellannahme", "Recepción de Pedidos de Sucursales")',
    "nav_whatsapp_chathub": 'pick_lang("صندوق محادثات الواتساب", "WhatsApp Chat Hub", "Hub de discussion WhatsApp", "WhatsApp Sohbet Merkezi", "WhatsApp-Chat-Hub", "Centro de Chat de WhatsApp")',
    "nav_callcenter_mgmt": 'pick_lang("إعدادات المساعد الصوتي", "AI Voice Assistant Settings", "Paramètres de l\'assistant vocal IA", "Yapay Zeka Sesli Asistan Ayarları", "KI-Sprachassistent-Einstellungen", "Ajustes del Asistente de Voz IA")',
    "nav_callcenter_overview": 'pick_lang("نظرة عامة وإحصائيات", "Overview & Stats", "Aperçu et statistiques", "Genel Bakış ve İstatistikler", "Übersicht & Statistiken", "Resumen y Estadísticas")',
    "nav_callcenter_persona": 'pick_lang("شخصية المساعد واللهجة", "Persona & Voice", "Personnalité et voix", "Kişilik ve Ses", "Persönlichkeit & Stimme", "Personalidad y Voz del Asistente")',
    "nav_callcenter_hours": 'pick_lang("مواعيد العمل والاعتذار", "Working Hours", "Heures de travail", "Çalışma Saatleri", "Öffnungszeiten", "Horarios de Atención")',
    "nav_callcenter_knowledge": 'pick_lang("قاعدة المعرفة (RAG)", "Knowledge Base", "Base de connaissances (RAG)", "Bilgi Tabanı (RAG)", "Wissensdatenbank (RAG)", "Base de Conocimientos (RAG)")',
    "nav_callcenter_queues": 'pick_lang("طوابير وموظفو التحويل", "Queues & Agents", "Files d\'attente et agents", "Kuyruklar ve Temsilciler", "Warteschlangen & Mitarbeiter", "Colas y Agentes de Desvío")',
    "nav_callcenter_calls": 'pick_lang("سجل المكالمات والتسجيلات", "Call Logs & Audio", "Historique des appels", "Çağrı Kayıtları", "Anrufliste & Aufnahmen", "Registro de Llamadas y Grabaciones")',
    "nav_callcenter_capabilities": 'pick_lang("صلاحيات وقدرات الذكاء", "AI Capabilities & MCP", "Capacités de l\'IA & MCP", "Yapay Zeka Yetenekleri ve MCP", "KI-Fähigkeiten & MCP", "Capacidades de IA y Protocolo MCP")',
    "nav_callcenter_omnichannel": 'pick_lang("قنوات الاتصال والواتساب", "Omnichannel & WhatsApp", "Omnicanal & WhatsApp", "Çok Kanallı ve WhatsApp", "Omnichannel & WhatsApp", "Omnicanal y WhatsApp")',
    "nav_inventory": 'pick_lang("المستودعات والمخزون", "Inventory & Warehouses", "Inventaire et stocks", "Envanter ve Depolar", "Warenlager & Inventar", "Almacenes e Inventario")',
    "nav_stock_audit": 'pick_lang("جرد المواد والمستودعات", "Stock Audit & Materials", "Inventaire des stocks", "Stok Sayımı ve Malzemeler", "Bestandsprüfung & Materialien", "Auditoría de Stock y Materiales")',
    "nav_delivery": 'pick_lang("أسطول التوصيل والمناديب", "Delivery Fleet & Drivers", "Flotte de livraison et livreurs", "Teslimat Filosu ve Kuryeler", "Lieferflotte & Fahrer", "Flota de Reparto y Repartidores")',
    "nav_orders": 'pick_lang("سجل كافة الطلبات والفواتير", "All Orders & Invoices", "Toutes les commandes et factures", "Tüm Siparişler ve Faturalar", "Alle Bestellungen & Rechnungen", "Historial de Pedidos y Facturas")',
    "nav_branch_orders": 'pick_lang("طلبات وفواتير الفرع", "Branch Orders & Invoices", "Commandes de la succursale", "Şube Siparişleri ve Faturaları", "Filialbestellungen & Rechnungen", "Pedidos y Facturas de la Sucursal")',
    "nav_employees": 'pick_lang("الموظفون والرواتب", "Staff & Payroll", "Personnel et paie", "Personel ve Maaşlar", "Personal & Gehaltsabrechnung", "Personal y Nóminas")',
    "nav_subscription": 'pick_lang("الاشتراك والتقارير المالية", "Subscription & Financials", "Abonnement et finances", "Abonelik ve Finansal Raporlar", "Abonnement & Finanzen", "Suscripción e Informes Financieros")',
    "nav_general_admin": 'pick_lang("الإدارة العامة", "General Admin", "Administration générale", "Genel Yönetim", "Hauptverwaltung", "Administración General")',
    "nav_platform": 'pick_lang("إدارة منصة SaaS العامة", "SaaS Platform Admin", "Administration de la plateforme SaaS", "SaaS Platform Yöneticisi", "SaaS-Plattform-Administration", "Administración de la Plataforma SaaS")',
    "nav_django_admin": 'pick_lang("لوحة Django Admin", "Django Admin Console", "Console Django Admin", "Django Yönetici Paneli", "Django Admin-Konsole", "Consola Django Admin")',

    # Header & User Actions
    "profile": 'pick_lang("الملف الشخصي", "User Profile", "Profil utilisateur", "Kullanıcı Profili", "Benutzerprofil", "Perfil de Usuario")',
    "logout": 'pick_lang("تسجيل الخروج", "Sign Out", "Déconnexion", "Çıkış Yap", "Abmelden", "Cerrar Sesión")',
    "login": 'pick_lang("تسجيل الدخول", "Sign In", "Connexion", "Giriş Yap", "Anmelden", "Iniciar Sesión")',
    "register": 'pick_lang("إنشاء حساب منشأة", "Register Restaurant", "Inscrire un restaurant", "Restoran Kaydet", "Restaurant registrieren", "Registrar Restaurante")',
    "notifications": 'pick_lang("الإشعارات", "Notifications", "Notifications", "Bildirimler", "Benachrichtigungen", "Notificaciones")',
    "collapse_sidebar": 'pick_lang("تصغير / توسيع القائمة الجانبية (Ctrl + B)", "Collapse / Expand Sidebar (Ctrl + B)", "Réduire / Agrandir la barre latérale", "Kenar Çubuğunu Daralt / Genişlet", "Seitenleiste ein-/ausklappen", "Contraer / Expandir Barra Lateral (Ctrl + B)")',
    "open_menu": 'pick_lang("فتح القائمة الرئيسية", "Open Main Menu", "Ouvrir le menu principal", "Ana Menüyü Aç", "Hauptmenü öffnen", "Abrir Menú Principal")',
    "live": 'pick_lang("مباشر", "LIVE", "EN DIRECT", "CANLI", "LIVE", "EN VIVO")',

    # Common Actions
    "save": 'pick_lang("حفظ", "Save", "Enregistrer", "Kaydet", "Speichern", "Guardar")',
    "cancel": 'pick_lang("إلغاء", "Cancel", "Annuler", "İptal", "Abbrechen", "Cancelar")',
    "delete": 'pick_lang("حذف", "Delete", "Supprimer", "Sil", "Löschen", "Eliminar")',
    "edit": 'pick_lang("تعديل", "Edit", "Modifier", "Düzenle", "Bearbeiten", "Editar")',
    "create": 'pick_lang("إضافة جديد", "Add New", "Ajouter nouveau", "Yeni Ekle", "Neu hinzufügen", "Añadir Nuevo")',
    "search": 'pick_lang("بحث...", "Search...", "Rechercher...", "Ara...", "Suchen...", "Buscar...")',
    "filter": 'pick_lang("تصفية", "Filter", "Filtrer", "Filtrele", "Filtern", "Filtrar")',
    "all": 'pick_lang("الكل", "All", "Tous", "Tümü", "Alle", "Todos")',
    "close": 'pick_lang("إغلاق", "Close", "Fermer", "Kapat", "Schließen", "Cerrar")',
    "back": 'pick_lang("رجوع", "Back", "Retour", "Geri", "Zurück", "Volver")',
    "confirm": 'pick_lang("تأكيد", "Confirm", "Confirmer", "Onayla", "Bestätigen", "Confirmar")',
    "print": 'pick_lang("طباعة", "Print", "Imprimer", "Yazdır", "Drucken", "Imprimir")',
    "export": 'pick_lang("تصدير", "Export", "Exporter", "Dışa Aktar", "Exportieren", "Exportar")',
    "refresh": 'pick_lang("تحديث", "Refresh", "Actualiser", "Yenile", "Aktualisieren", "Actualizar")',
    "details": 'pick_lang("التفاصيل", "Details", "Détails", "Ayrıntılar", "Details", "Detalles")',
    "actions": 'pick_lang("الإجراءات", "Actions", "Actions", "İşlemler", "Aktionen", "Acciones")',

    # Common Statuses & Financials
    "status": 'pick_lang("الحالة", "Status", "Statut", "Durum", "Status", "Estado")',
    "active": 'pick_lang("نشط", "Active", "Actif", "Aktif", "Aktiv", "Activo")',
    "inactive": 'pick_lang("معطل", "Inactive", "Inactif", "Pasif", "Inaktiv", "Inactivo")',
    "pending": 'pick_lang("قيد المراجعة", "Pending", "En attente", "Beklemede", "Ausstehend", "Pendiente")',
    "approved": 'pick_lang("تمت الموافقة", "Approved", "Approuvé", "Onaylandı", "Genehmigt", "Aprobado")',
    "rejected": 'pick_lang("مرفوض", "Rejected", "Rejeté", "Reddedildi", "Abgelehnt", "Rechazado")',
    "completed": 'pick_lang("مكتمل", "Completed", "Terminé", "Tamamlandı", "Abgeschlossen", "Completado")',
    "cancelled": 'pick_lang("ملغي", "Cancelled", "Annulé", "İptal Edildi", "Storniert", "Cancelado")',
    "total": 'pick_lang("الإجمالي", "Total", "Total", "Toplam", "Gesamt", "Total")',
    "subtotal": 'pick_lang("المجموع الفرعي", "Subtotal", "Sous-total", "Ara Toplam", "Zwischensumme", "Subtotal")',
    "vat": 'pick_lang("ضريبة القيمة المضافة (15%)", "VAT (15%)", "TVA (15%)", "KDV (%15)", "MwSt. (15%)", "IVA (15%)")',
    "discount": 'pick_lang("الخصم", "Discount", "Remise", "İndirim", "Rabatt", "Descuento")',
    "quantity": 'pick_lang("الكمية", "Qty", "Qté", "Adet", "Menge", "Cant.")',
    "price": 'pick_lang("السعر", "Price", "Prix", "Fiyat", "Preis", "Precio")',
    "date": 'pick_lang("التاريخ", "Date", "Date", "Tarih", "Datum", "Fecha")',
    "notes": 'pick_lang("الملاحظات", "Notes", "Remarques", "Notlar", "Notizen", "Notas")',

    # POS & KDS
    "cashier": 'pick_lang("الكاشير", "Cashier", "Caisse", "Kasiyer", "Kasse", "Caja")',
    "dine_in": 'pick_lang("محلي", "Dine-In", "Sur place", "Restoranda", "Im Restaurant", "En sala")',
    "takeaway": 'pick_lang("سفري", "Takeaway", "À emporter", "Paket Servis", "Zum Mitnehmen", "Para llevar")',
    "delivery_type": 'pick_lang("توصيل", "Delivery", "Livraison", "Teslimat", "Lieferung", "A domicilio")',
    "cash": 'pick_lang("نقداً", "Cash", "Espèces", "Nakit", "Barzahlung", "Efectivo")',
    "card": 'pick_lang("شبكة / مدى", "Card / Mada", "Carte bancaire", "Banka Kartı", "Kartenzahlung", "Tarjeta")',
    "order_num": 'pick_lang("طلب رقم", "Order #", "Commande n°", "Sipariş No", "Bestellung Nr.", "Pedido N°")',
    "cooking": 'pick_lang("قيد الطهي", "Cooking", "En cuisson", "Pişiriliyor", "In Zubereitung", "En preparación")',
    "ready": 'pick_lang("جاهز للاستلام", "Ready", "Prêt", "Hazır", "Fertig", "Listo para recoger")',
    "on_the_way": 'pick_lang("في الطريق", "On The Way", "En route", "Yolda", "Unterwegs", "En camino")',
    "select_language": 'pick_lang("اختيار اللغة", "Select Language", "Choisir la langue", "Dil Seçin", "Sprache wählen", "Seleccionar Idioma")',

    # Operational Domains
    "dash_command_center": 'pick_lang("مركز القيادة والعمليات", "Command & Operations Center", "Centre de commandement et d\'opérations", "Komuta ve Operasyon Merkezi", "Kommando- und Betriebszentrum", "Centro de Mando y Operaciones")',
    "dash_subtitle": 'pick_lang("متابعة حية للتدفق المالي، توزيع الطلبات، أداء الفروع، وكول سنتر الذكاء الاصطناعي في شاشة موحدة.", "Live monitoring of cash flow, order distribution, branch performance, and AI Call Center.", "Suivi en direct des flux de trésorerie, de la répartition des commandes, des performances des succursales et du centre d\'appels IA.", "Nakit akışı, sipariş dağılımı, şube performansı ve Yapay Zeka Çağrı Merkezi canlı takibi.", "Live-Überwachung von Cashflow, Auftragsverteilung, Filialleistung und KI-Call-Center auf einem Bildschirm.", "Supervisión en tiempo real del flujo de caja, distribución de pedidos, rendimiento de sucursales y Call Center de IA.")',
    "dash_unified_system": 'pick_lang("النظام الموحد للإدارة العليا", "Unified Executive Management System", "Système unifié de gestion exécutive", "Birleşik Üst Düzey Yönetim Sistemi", "Einheitliches Führungsinformationssystem", "Sistema Unificado de Alta Dirección")',
    "dash_live_monitoring": 'pick_lang("متابعة فورية ومباشرة لكافة الفروع", "Live Real-Time Monitoring of All Branches", "Surveillance en temps réel de toutes les succursales", "Tüm Şubelerin Anlık Canlı Takibi", "Echtzeit-Überwachung aller Filialen", "Monitoreo en Tiempo Real de Todas las Sucursales")',
    "dash_chain_sales_today": 'pick_lang("إجمالي مبيعات السلسلة اليوم", "Total Chain Revenue Today", "Revenu total de la chaîne aujourd\'hui", "Zincirin Bugünkü Toplam Geliri", "Gesamter Kettenumsatz heute", "Ventas Totales de la Cadena Hoy")',
    "dash_net_revenue": 'pick_lang("صافي الإيراد المحصل", "Net Collected Revenue", "Revenu net collecté", "Net Tahsil Edilen Gelir", "Eingenommener Nettoerlös", "Ingresos Netos Cobrados")',
    "dash_completed_orders": 'pick_lang("عدد الطلبات المكتملة", "Completed Orders Count", "Nombre de commandes terminées", "Tamamlanan Sipariş Sayısı", "Abgeschlossene Bestellungen", "Pedidos Completados")',
    "dash_active_orders": 'pick_lang("الطلبات النشطة حالياً", "Currently Active Orders", "Commandes actuellement actives", "Şu Anda Aktif Siparişler", "Aktuell aktive Bestellungen", "Pedidos Activos Actualmente")',
    "dash_branches_performance": 'pick_lang("أداء الفروع المباشر", "Live Branch Performance", "Performance en direct des succursales", "Canlı Şube Performansı", "Live-Filialleistung", "Rendimiento en Vivo de Sucursales")',
    "dash_sales_by_channel": 'pick_lang("توزيع المبيعات حسب القنوات", "Sales Distribution by Channel", "Distribution des ventes par canal", "Kanallara Göre Satış Dağılımı", "Umsatzverteilung nach Kanälen", "Distribución de Ventas por Canal")',
    "dash_top_dishes": 'pick_lang("أكثر الأطباق طلباً بالسلسلة", "Top Selling Dishes Across Chain", "Plats les plus vendus de la chaîne", "Zincirde En Çok Satan Yemekler", "Meistverkaufte Gerichte der Kette", "Platos Más Vendidos de la Cadena")',
    "dash_sales_last_7_days": 'pick_lang("مبيعات آخر 7 أيام", "Sales - Last 7 Days", "Ventes des 7 derniers jours", "Son 7 Günlük Satışlar", "Umsatz der letzten 7 Tage", "Ventas de los Últimos 7 Días")',

    "pos_title": 'pick_lang("الكاشير — نقطة البيع الذكية", "Smart Cashier & POS Terminal", "Caisse intelligente et terminal PDV", "Akıllı Kasiyer ve POS Terminali", "Intelligente Kasse & POS-Terminal", "Caja — Terminal Punto de Venta Inteligente (TPV)")',
    "pos_subtitle": 'pick_lang("تسجيل الطلبات، إصدار الفواتير الفورية، والتحصيل المباشر", "Fast order entry, instant receipt printing, and live checkout", "Prise de commande rapide, impression de reçus et encaissement en direct", "Hızlı sipariş girişi, anında fiş yazdırma ve canlı ödeme", "Schnelle Auftragserfassung, Sofortbelegdruck und Live-Kassierung", "Registro ágil de pedidos, emisión inmediata de facturas y cobro directo")',
    "pos_manage_menu": 'pick_lang("إدارة أصناف القائمة", "Manage Menu Items", "Gérer les éléments du menu", "Menü Öğelerini Yönet", "Menüelemente verwalten", "Gestionar Artículos de la Carta")',
    "pos_search_ph": 'pick_lang("ابحث عن وجبة أو مشروب…", "Search meal or beverage…", "Rechercher un plat ou une boisson…", "Yemek veya içecek ara…", "Gericht oder Getränk suchen…", "Buscar plato o bebida…")',
    "pos_cart_details": 'pick_lang("تفاصيل الفاتورة والحساب", "Invoice & Bill Details", "Détails de la facture", "Fatura ve Hesap Ayrıntıları", "Rechnungsdetails", "Detalles de Factura y Cuenta")',
    "pos_checkout_btn": 'pick_lang("إتمام الطلب والدفع", "Complete Order & Checkout", "Finaliser la commande et payer", "Siparişi Tamamla ve Öde", "Bestellung abschließen & bezahlen", "Completar Pedido y Cobrar")',

    "kds_title": 'pick_lang("شاشات المطبخ الذكية (KDS)", "Smart Kitchen Display System (KDS)", "Système d\'affichage de cuisine intelligent (KDS)", "Akıllı Mutfak Ekran Sistemi (KDS)", "Intelligentes Küchenanzeigesystem (KDS)", "Pantallas de Cocina Inteligentes (KDS)")',
    "kds_subtitle": 'pick_lang("تتبع فوري لأوامر الطهي والتحضير بالمطابخ والأقسام", "Real-time kitchen order tickets, timers, and cooking workflow", "Tickets de commande en temps réel, minuteurs et flux de cuisson", "Gerçek zamanlı mutfak sipariş fişleri, zamanlayıcılar ve pişirme akışı", "Echtzeit-Küchenbestellscheine, Timer und Zubereitungsablauf", "Seguimiento en tiempo real de comandas, tiempos y flujo de preparación en cocina")',

    "branch_title": 'pick_lang("إدارة الفروع والمواقع", "Manage Branches & Locations", "Gérer les succursales et emplacements", "Şubeleri ve Konumları Yönet", "Filialen & Standorte verwalten", "Gestión de Sucursales y Ubicaciones")',
    "branch_subtitle": 'pick_lang("شبكة الفروع والمواقع التشغيلية", "Operational Branches & Locations Network", "Réseau opérationnel de succursales", "Operasyonel Şubeler ve Konumlar Ağı", "Betriebsfilialen & Standortnetzwerk", "Red de Sucursales y Sedes Operativas")',

    "inv_title": 'pick_lang("المستودعات والمخزون", "Inventory & Warehouses", "Inventaire et stocks", "Envanter ve Depolar", "Warenlager & Inventar", "Almacenes e Inventario")',
    "inv_subtitle": 'pick_lang("إدارة المخزون والمستودعات", "Inventory & Stock Management", "Gestion des stocks et entrepôts", "Envanter ve Stok Yönetimi", "Inventar- & Lagerverwaltung", "Control de Stock y Almacenes")',

    "emp_title": 'pick_lang("الموظفون والرواتب", "Staff & Payroll", "Personnel et paie", "Personel ve Maaşlar", "Personal & Gehaltsabrechnung", "Personal y Nóminas")',
    "emp_subtitle": 'pick_lang("إدارة الكادر والمسميات الوظيفية والصلاحيات", "Manage Staff, Job Roles & Permissions", "Gérer le personnel, les rôles et permissions", "Personeli, Görevleri ve Yetkileri Yönet", "Mitarbeiter, Rollen & Berechtigungen verwalten", "Gestión de Plantilla, Puestos y Permisos")',

    "sub_title": 'pick_lang("الاشتراك والتقارير المالية", "Subscription & Financial Reports", "Abonnement et rapports financiers", "Abonelik ve Finansal Raporlar", "Abonnement & Finanzberichte", "Suscripción e Informes Financieros")',
    "sub_subtitle": 'pick_lang("إدارة الاشتراك واستهلاك الحساب", "Manage Subscription & Account Consumption", "Gérer l\'abonnement et la consommation du compte", "Abonelik ve Hesap Tüketimini Yönet", "Abonnement & Kontoverbrauch verwalten", "Gestión de Suscripción y Consumo de la Cuenta")',

    "plat_title": 'pick_lang("لوحة الإدارة المركزية للمنصة (SaaS Superadmin)", "SaaS Platform Central Management", "Gestion centrale de la plateforme SaaS", "SaaS Platformu Merkezi Yönetimi", "Zentrale Verwaltung der SaaS-Plattform", "Panel de Administración Central SaaS")',
    "plat_subtitle": 'pick_lang("إدارة المطاعم المشتركة، الباقات والاشتراكات، والتحكم بالمنظومة", "Manage subscribed restaurants, plans & subscriptions, and platform controls", "Gérer les restaurants abonnés, plans et paramètres", "Abone restoranları, planları ve platform kontrollerini yönet", "Abonnierte Restaurants, Tarife und Plattformsteuerungen verwalten", "Administrar restaurantes suscritos, planes, membresías y controles de la plataforma")',

    "cc_title": 'pick_lang("الكول سنتر — منظومة كورا", "Call Center — KURA Dining OS", "Centre d\'appels — KURA Dining OS", "Çağrı Merkezi — KURA Dining OS", "Call-Center — KURA Dining OS", "Call Center — KURA Dining OS")',
    "cc_heading": 'pick_lang("الكول سنتر وخدمة العملاء", "Call Center & Customer Care", "Centre d\'appels et service client", "Çağrı Merkezi ve Müşteri Hizmetleri", "Call-Center & Kundenservice", "Call Center y Atención al Cliente")',
    "cc_subtitle": 'pick_lang("استقبال اتصالات الزبائن، البحث الفوري عن العملاء، وتسجيل طلبات التوصيل", "Incoming customer calls, rapid customer lookup, and delivery order dispatch", "Appels clients entrants, recherche rapide de clients et expédition des livraisons", "Gelen müşteri çağrıları, hızlı müşteri arama ve teslimat siparişi kaydı", "Eingehende Kundenanrufe, schnelle Kundensuche und Lieferbestellungsaufgabe", "Recepción de llamadas de clientes, búsqueda instantánea y asignación de pedidos a domicilio")',
    "cc_lines_ready": 'pick_lang("الخطوط جاهزة لاستقبال الاتصالات", "Lines Ready for Inbound Calls", "Lignes prêtes pour les appels entrants", "Hatlar Gelen Aramalar İçin Hazır", "Leitungen bereit für eingehende Anrufe", "Líneas listas para recibir llamadas")',

    "deliv_title": 'pick_lang("إدارة التوصيل — منظومة كورا", "Delivery Fleet — KURA Dining OS", "Flotte de livraison — KURA Dining OS", "Teslimat Filosu — KURA Dining OS", "Lieferflotte — KURA Dining OS", "Flota de Reparto — KURA Dining OS")',
    "deliv_heading": 'pick_lang("إدارة وتوزيع طلبات التوصيل", "Delivery Dispatch & Fleet Management", "Gestion de la flotte et répartition des livraisons", "Teslimat Dağıtımı ve Filo Yönetimi", "Lieferdisposition & Flottenmanagement", "Gestión y Despacho de Pedidos a Domicilio")',
    "deliv_subtitle": 'pick_lang("متابعة مسار الطلبات خطوة بخطوة وتوزيعها على أسطول السائقين", "Step-by-step order tracking and live driver fleet dispatching", "Suivi des commandes étape par étape et répartition des chauffeurs", "Adım adım sipariş takibi ve canlı sürücü filosu sevkiyatı", "Schritt-für-Schritt-Auftragsverfolgung und Live-Fahrerflottendisposition", "Seguimiento paso a paso de los pedidos y despacho a la flota de repartidores")',

    "hq_orders_title": 'pick_lang("سجل كافة الطلبات والفواتير — الإدارة العامة", "Chain Orders & Invoices — Central HQ", "Commandes et factures de la chaîne — Siège central", "Zincir Siparişleri ve Faturaları — Genel Merkez", "Kettenbestellungen & Rechnungen — Hauptsitz", "Historial de Pedidos y Facturas de la Cadena — Sede Central")',
    "hq_orders_heading": 'pick_lang("سجل كافة الطلبات والفواتير الموحد", "Unified Orders & Invoices Record", "Registre unifié des commandes et factures", "Birleşik Siparişler ve Faturalar Kaydı", "Einheitliches Bestell- & Rechnungsregister", "Registro Unificado de Pedidos y Facturas")',
    "hq_orders_subtitle": 'pick_lang("متابعة مباشرة لتدفق طلبات وفواتير كافة الفروع في شاشة واحدة", "Live monitoring of incoming orders and bills across all branches in one screen", "Suivi en direct des commandes et factures de toutes les succursales", "Tüm şubelerdeki sipariş ve fatura akışının tek ekranda canlı takibi", "Live-Überwachung von Bestellungen und Rechnungen aller Filialen auf einem Bildschirm", "Supervisión en vivo de pedidos y facturas de todas las sucursales en una pantalla")',

    # Landing Page Meta & Nav
    "landing_meta_title": 'pick_lang("مطاعم — منظومة إدارة سلاسل المطاعم والضيافة السحابية", "Motaem — Cloud Restaurant & Hospitality Operating System", "Motaem — Système d\'exploitation cloud pour restaurants et hôtellerie", "Motaem — Bulut Restoran ve Ağırlama İşletim Sistemi", "Motaem — Cloud-Betriebssystem für Gastronomie & Restaurantketten", "Motaem — Sistema Operativo en la Nube para Restaurantes y Hostelería")',
    "landing_nav_voice_demo": 'pick_lang("تجربة صوتية حية", "Live Voice Demo", "Démo vocale en direct", "Canlı Sesli Demo", "Live-Sprachdemo", "Demostración de Voz en Vivo")',
    "landing_nav_dashboard": 'pick_lang("لوحة الإدارة", "Dashboard", "Tableau de bord", "Yönetim Paneli", "Dashboard", "Panel de Control")',
    "landing_nav_profile": 'pick_lang("البروفايل", "Profile", "Profil", "Profil", "Profil", "Perfil")',
    "landing_nav_start_free": 'pick_lang("ابدأ مجاناً", "Start Free", "Démarrer gratuitement", "Ücretsiz Başlayın", "Kostenlos starten", "Empieza Gratis")',

    # Landing Hero & Teaser
    "landing_hero_talk_ai": 'pick_lang("تحدث مع المساعد الصوتي الآن مباشرة", "Talk to Voice AI Assistant Now", "Parler à l\'assistant vocal IA", "Yapay Zeka Sesli Asistanla Şimdi Konuşun", "Jetzt direkt mit dem KI-Sprachassistenten sprechen", "Habla con el Asistente de Voz IA en Directo")',
    "landing_no_card": 'pick_lang("بدون بطاقة ائتمانية", "No Credit Card Required", "Aucune carte de crédit requise", "Kredi Kartı Gerekmez", "Keine Kreditkarte erforderlich", "Sin Tarjeta de Crédito")',
    "landing_instant_setup": 'pick_lang("تفعيل فوري خلال دقيقتين", "Instant 2-Minute Setup", "Configuration instantanée en 2 minutes", "2 Dakikada Anında Kurulum", "Sofortige Einrichtung in 2 Minuten", "Activación Inmediata en 2 Minutos")',
    "landing_metric_kitchen": 'pick_lang("بث المطبخ اللحظي", "Real-Time Kitchen Feed", "Flux de cuisine en temps réel", "Gerçek Zamanlı Mutfak Yayını", "Echtzeit-Küchen-Feed", "Transmisión en Vivo de Cocina")',
    "landing_metric_callcenter": 'pick_lang("كول سنتر AI صوتي", "AI Voice Call Center", "Centre d\'appels vocal IA", "Yapay Zeka Sesli Çağrı Merkezi", "KI-Sprach-Call-Center", "Call Center de Voz con IA")',
    "landing_metric_uptime": 'pick_lang("استقرار سحابي تام", "Guaranteed Cloud Uptime", "Disponibilité cloud garantie", "Garantili Bulut Çalışma Süresi", "Garantierte Cloud-Verfügbarkeit", "Disponibilidad Cloud Garantizada")',
    "landing_teaser_badge": 'pick_lang("اتصال صوتي حي ومباشر فائق السرعة", "Instant Live Voice Call • Zero Delay", "Appel vocal direct instantané • Zéro latence", "Anında Canlı Sesli Arama • Sıfır Gecikme", "Direkter Live-Sprachanruf • Keine Verzögerung", "Llamada de Voz en Vivo Instantánea • Cero Demora")',
    "landing_teaser_heading": 'pick_lang("جرّب المساعد الصوتي الذكي الآن وتحدث معه مباشرة من المتصفح", "Test the AI Voice Agent Live in Your Browser", "Testez l\'assistant vocal IA en direct dans votre navigateur", "Yapay Zeka Sesli Temsilciyi Tarayıcınızda Canlı Deneyin", "Testen Sie den KI-Sprachassistenten live in Ihrem Browser", "Prueba el Asistente de Voz IA en Directo desde tu Navegador")',
    "landing_teaser_desc": 'pick_lang("اطلب وجبة، استفسر عن الأسعار أو الفروع، واختبر فهم اللهجات والرد اللحظي.", "Dial in directly from your computer or phone microphone to experience native voice ordering.", "Appelez directement depuis votre micro pour commander à la voix en temps réel.", "Doğal sesli sipariş deneyimi için doğrudan mikrofonunuzdan arayın.", "Wählen Sie sich direkt über Ihr Mikrofon ein, um natürliche Sprachbestellungen zu erleben.", "Pide un plato, consulta precios o sucursales y comprueba la comprensión natural y respuesta instantánea.")',
    "landing_teaser_btn": 'pick_lang("بدء المكالمة الصوتية الحية", "Start Live Voice Session", "Démarrer la session vocale en direct", "Canlı Sesli Görüşmeyi Başlat", "Live-Sprachübertragung starten", "Iniciar Llamada de Voz en Vivo")',

    # Landing Pillars
    "landing_pillars_badge": 'pick_lang("قدرات تشغيلية موحدة", "Unified Operational Capabilities", "Capacités opérationnelles unifiées", "Birleşik Operasyonel Yetenekler", "Einheitliche betriebliche Funktionen", "Capacidades Operativas Unificadas")',
    "landing_pillars_heading": 'pick_lang("كل ما تحتاجه لإدارة وتوسيع مطاعمك من مكان واحد", "Everything You Need to Manage & Scale Your Restaurants from One Place", "Tout ce dont vous avez besoin pour gérer et développer vos restaurants en un seul endroit", "Restoranlarınızı Tek Bir Yerden Yönetmek ve Büyütmek İçin İhtiyacınız Olan Her Şey", "Alles, was Sie zur Verwaltung und Skalierung Ihrer Restaurants an einem Ort benötigen", "Todo lo que Necesitas para Gestionar y Escalar tus Restaurantes en un Solo Lugar")',
    "landing_pillars_desc": 'pick_lang("صممت منظومة «مطاعم» لتغطي رحلة الطلب بالكامل من لحظة اتصال العميل وحتى تسليم الوجبة بدقة ولحظية تامة.", "Engineered by Motaem to streamline the entire order journey—from the moment a customer calls to hot meal delivery with zero latency.", "Conçu par Motaem pour optimiser tout le cycle de commande, de l\'appel du client à la livraison sans délai.", "Müşterinin aradığı andan sıcak yemeğin teslimine kadar tüm sipariş sürecini sıfır gecikmeyle yönetmek için tasarlandı.", "Entwickelt von Motaem, um den gesamten Bestellablauf vom Anruf des Kunden bis zur heißen Essensauslieferung ohne Verzögerung zu optimieren.", "Diseñado por Motaem para optimizar el ciclo completo del pedido: desde la llamada del cliente hasta la entrega puntual.")',
    "landing_pos_title": 'pick_lang("نقطة البيع السحابية (Cloud POS)", "Cloud Point of Sale (POS)", "Point de vente cloud (PDV)", "Bulut Satış Noktası (POS)", "Cloud-Kassensystem (POS)", "Punto de Venta en la Nube (TPV)")',
    "landing_pos_desc": 'pick_lang("واجهة كاشير لمسية خفيفة وسريعة تدعم الفواتير الإلكترونية المعتمدة (QR Code وZATCA)، إدارة الطاولات، والطلبات المحلية والسفري بدون أي تعليق.", "Lightning-fast touch cashier terminal supporting QR & ZATCA e-invoicing, table management, and dine-in/takeaway orders with zero lag.", "Terminal de caisse tactile ultra-rapide compatible avec facturation QR & ZATCA, gestion des tables et commandes sur place/à emporter.", "QR ve ZATCA e-faturalandırma, masa yönetimi ve gecikmesiz paket/içeride sipariş destekleyen yüksek hızlı dokunmatik kasiyer terminali.", "Blitzschnelles Touch-Kassenterminal mit Unterstützung für QR- & ZATCA-E-Rechnungen, Tischverwaltung und Bestellungen vor Ort/zum Mitnehmen.", "Terminal de caja táctil ultra-rápido con facturación electrónica ZATCA y QR, gestión de mesas y pedidos en sala y para llevar.")',
    "landing_kds_title": 'pick_lang("شاشات المطبخ الحية (KDS Live)", "Live Kitchen Display System (KDS Live)", "Système d\'affichage en cuisine en direct (KDS Live)", "Canlı Mutfak Ekran Sistemi (KDS Live)", "Live-Küchenanzeigesystem (KDS Live)", "Pantallas de Cocina en Vivo (KDS Live)")',
    "landing_kds_desc": 'pick_lang("بث حي عبر تقنية SSE بالملي ثانية بدون تحديث الصفحة، عزل صارم لمحطات الطهي، جرس تنبيه صوتي فندقي، وقوائم إنجاز الوجبات خطوة بخطوة.", "Real-time SSE zero-latency live streaming without page reloads, kitchen station isolation, chime alerts, and step-by-step cooking progress.", "Diffusion en direct SSE à latence zéro sans rechargement, isolation des postes de cuisine, alertes sonores et suivi pas à pas.", "Sayfa yenilemesi olmadan gerçek zamanlı SSE canlı akış, istasyon ayrımı, sesli uyarılar ve adım adım hazırlık takibi.", "Echtzeit-SSE-Streaming ohne Seiten-Reloads, Trennung von Küchenstationen, Signalton-Benachrichtigungen und schrittweiser Zubereitungsfortschritt.", "Transmisión en directo SSE en milisegundos sin recargar página, separación estricta de partidas de cocina, alertas sonoras y flujo de preparación paso a paso.")',
    "landing_ai_title": 'pick_lang("كول سنتر الذكاء الاصطناعي (AI Phone)", "AI Phone Agent & Call Center", "Agent téléphonique IA & Centre d\'appels", "Yapay Zeka Telefon Temsilcisi ve Çağrı Merkezi", "KI-Telefonagent & Call-Center", "Agente Telefónico con IA y Call Center")',
    "landing_ai_desc": 'pick_lang("رد آلي فوري على المكالمات الهاتفية، فهم اللهجات بدقة، تسجيل الطلبات وإسنادها تلقائياً للمطبخ والفرع المناسب.", "Automated inbound phone call handling with native dialect comprehension, order capture, and automatic routing to the nearest branch and kitchen.", "Gestion automatisée des appels entrants avec compréhension des dialectes, saisie des commandes et acheminement automatique vers la cuisine.", "Doğal lehçe anlama, sipariş kaydı ve en yakın şubeye/mutfağa otomatik yönlendirme ile gelen çağrıların otomatik yönetimi.", "Automatisierte Annahme eingehender Anrufe mit Dialektverständnis, Auftragserfassung und Weiterleitung an Filiale und Küche.", "Atención automática e inmediata de llamadas, comprensión natural, registro de pedidos y derivación automática a la cocina y sucursal adecuada.")',
    "landing_ai_try": 'pick_lang("جرّب المكالمة الصوتية الآن", "Try Live Call Now", "Essayer l\'appel en direct", "Canlı Aramayı Şimdi Deneyin", "Jetzt Live-Anruf testen", "Probar Llamada en Vivo Ahora")',
    "landing_ai_tag": 'pick_lang("مكالمة صوتية مباشرة", "Live Voice Demo", "Démo vocale en direct", "Canlı Sesli Demo", "Live-Sprachdemo", "Demostración de Voz en Directo")',
    "landing_chain_title": 'pick_lang("إدارة السلاسل والتسعير الفرعي", "Chain Management & Branch Pricing", "Gestion de chaîne et tarification par succursale", "Zincir Yönetimi ve Şube Fiyatlandırması", "Kettenverwaltung & Filialpreisgestaltung", "Gestión de Cadenas y Precios por Sucursal")',
    "landing_chain_desc": 'pick_lang("إدارة مركزية لكافة الفروع مع حرية تخصيص أسعار الأطباق والأحجام لكل فرع على حدة، مراقبة المخزون، وصلاحيات الموظفين الدقيقة.", "Centralized headquarters management with branch-specific menu pricing, multi-warehouse inventory auditing, and granular staff RBAC roles.", "Gestion centralisée avec tarification spécifique par succursale, inventaire multi-entrepôts et rôles RBAC précis pour le personnel.", "Şubeye özel menü fiyatlandırması, çoklu depo stok denetimi ve ayrıntılı personel yetkilendirmesi ile merkezi yönetim.", "Zentrale Verwaltung mit filialbezogener Menüpreisgestaltung, Bestandsprüfung für mehrere Lager und granularen Mitarbeiterrollen.", "Gestión centralizada de todas las sucursales con precios personalizados por sede, control de inventario y permisos detallados de personal.")',
    "landing_delivery_title": 'pick_lang("إدارة التوصيل وأسطول السائقين (Delivery Dispatch)", "Delivery Dispatch & Fleet Management", "Expédition des livraisons & Gestion de flotte", "Teslimat Dağıtımı ve Filo Yönetimi", "Lieferdisposition & Flottenmanagement", "Despacho de Envíos y Gestión de Flota de Reparto")',
    "landing_delivery_desc": 'pick_lang("لوحة كانبان تفاعلية لنقل الطلبات بين مراحل التجهيز، إسناد فوري للسائقين المتاحين، وتتبع دقيق لوقت التوصيل لضمان وصول الوجبات ساخنة وطازجة.", "Interactive Kanban board for order preparation stages, instant driver dispatching, and live delivery duration tracking to ensure meals arrive fresh and hot.", "Tableau Kanban interactif pour les étapes de préparation, répartition immédiate des livreurs et suivi précis du délai de livraison.", "Hazırlık aşamaları için etkileşimli Kanban panosu, anında kurye ataması ve yemeklerin sıcak teslimatı için canlı süre takibi.", "Interaktives Kanban-Board für Zubereitungsphasen, sofortige Fahrerzuweisung und Live-Lieferzeitverfolgung für frische Speisen.", "Tablero Kanban interactivo para fases de preparación, asignación inmediata a repartidores y seguimiento en vivo para garantizar entregas óptimas.")',

    # Stats & Pricing
    "landing_stat_chains": 'pick_lang("سلسلة مطاعم رائدة", "Leading Restaurant Chains", "Chaînes de restaurants leaders", "Öncü Restoran Zincirleri", "Führende Restaurantketten", "Cadenas de Restaurantes Líderes")',
    "landing_stat_branches": 'pick_lang("فرع تشغيلي نشط", "Active Operational Branches", "Succursales opérationnelles actives", "Aktif Operasyonel Şubeler", "Aktive Betriebsfilialen", "Sucursales Operativas Activas")',
    "landing_stat_orders": 'pick_lang("طلب منفذ يومياً", "Orders Handled Daily", "Commandes traitées chaque jour", "Günlük İşlenen Siparişler", "Täglich abgewickelte Bestellungen", "Pedidos Gestionados Diariamente")',
    "landing_stat_uptime": 'pick_lang("استقرار الخوادم السحابية", "Cloud Server Uptime", "Disponibilité des serveurs cloud", "Bulut Sunucu Çalışma Süresi", "Cloud-Server-Verfügbarkeit", "Disponibilidad de Servidores en la Nube")',
    "landing_pricing_badge": 'pick_lang("باقات واضحة وبسيطة", "Simple & Transparent Pricing", "Tarification simple et transparente", "Basit ve Şeffaf Fiyatlandırma", "Einfache & transparente Preise", "Precios Claros y Transparentes")',
    "landing_pricing_heading": 'pick_lang("اختر الخطة المناسبة لحجم ونشاط مطاعمك", "Choose the Perfect Plan for Your Restaurant Operations", "Choisissez le forfait idéal pour vos activités", "Restoran Operasyonlarınız İçin Mükemmel Planı Seçin", "Wählen Sie den perfekten Tarif für Ihren Restaurantbetrieb", "Elige el Plan Perfecto para tu Cadena de Restaurantes")',
    "landing_pricing_desc": 'pick_lang("جميع الباقات تتضمن فترة تجريبية مجانية لمدة 14 يوماً بدون الحاجة لبطاقة ائتمان.", "All plans include a 14-day free trial with full access. No credit card required.", "Tous les forfaits incluent un essai gratuit de 14 jours avec accès complet. Sans carte bancaire.", "Tüm planlar tam erişimli 14 günlük ücretsiz deneme içerir. Kredi kartı gerekmez.", "Alle Tarife enthalten eine 14-tägige kostenlose Testversion mit vollem Zugriff. Keine Kreditkarte erforderlich.", "Todos los planes incluyen 14 días de prueba gratuita con acceso completo. Sin tarjeta de crédito.")',
    "landing_popular": 'pick_lang("الأكثر طلباً", "Most Popular", "Le plus populaire", "En Popüler", "Am beliebtesten", "Más Popular")',
    "landing_price_free": 'pick_lang("مجاناً", "Free", "Gratuit", "Ücretsiz", "Kostenlos", "Gratis")',
    "landing_14_days": 'pick_lang("14 يوماً", "14 Days", "14 jours", "14 Gün", "14 Tage", "14 Días")',
    "landing_usd_month": 'pick_lang("دولار / شهرياً", "USD / Month", "USD / mois", "USD / Ay", "USD / Monat", "USD / Mes")',
    "landing_yearly_save": 'pick_lang("أو وفر 20% بالدفع السنوي", "or Save 20% on Annual Billing", "ou économisez 20% sur la facturation annuelle", "veya Yıllık Ödemede %20 Tasarruf Edin", "oder 20% sparen bei jährlicher Abrechnung", "o Ahorra 20% con Pago Anual")',
    "landing_allowed_branches": 'pick_lang("الفروع المتاحة:", "Allowed Branches:", "Succursales autorisées :", "İzin Verilen Şubeler:", "Zulässige Filialen:", "Sucursales Permitidas:")',
    "landing_unlimited": 'pick_lang("غير محدودة", "Unlimited", "Illimité", "Sınırsız", "Unbegrenzt", "Ilimitadas")',
    "landing_branches_unit": 'pick_lang("فروع", "branches", "succursales", "şube", "Filialen", "sucursales")',
    "landing_staff_members": 'pick_lang("كادر الموظفين:", "Staff Members:", "Personnel :", "Personel Sayısı:", "Mitarbeiteranzahl:", "Equipo de Empleados:")',
    "landing_employees_unit": 'pick_lang("موظف", "employees", "employés", "personel", "Mitarbeiter", "empleados")',
    "landing_kds_feature": 'pick_lang("شاشات المطبخ KDS الحية", "Live Kitchen Display System (KDS)", "Système d\'affichage en cuisine (KDS)", "Canlı Mutfak Ekranı (KDS)", "Live-Küchenanzeigesystem (KDS)", "Pantallas de Cocina KDS en Vivo")',
    "landing_ai_feature": 'pick_lang("كول سنتر الذكاء الاصطناعي (AI Telephony)", "AI Phone Call Center (AI Telephony)", "Centre d\'appels IA (Téléphonie IA)", "Yapay Zeka Telefon Çağrı Merkezi", "KI-Telefon-Call-Center (KI-Telefonie)", "Call Center con Inteligencia Artificial (Telefonía IA)")',
    "landing_zatca_feature": 'pick_lang("الفواتير الإلكترونية المعتمدة ZATCA", "Compliant E-Invoicing (ZATCA & QR)", "Facturation électronique conforme (ZATCA & QR)", "Uyumlu E-Faturalandırma (ZATCA ve QR)", "Konforme E-Rechnungsstellung (ZATCA & QR)", "Facturación Electrónica Homologada (ZATCA y QR)")',
    "landing_start_trial": 'pick_lang("ابدأ التجربة المجانية", "Start Free Trial", "Commencer l\'essai gratuit", "Ücretsiz Denemeyi Başlat", "Kostenlose Testversion starten", "Comenzar Prueba Gratuita")',

    # Plan Names
    "plan_starter_name": 'pick_lang("باقة البداية", "Starter Plan", "Forfait Débutant", "Başlangıç Planı", "Starter-Tarif", "Plan Inicio")',
    "plan_growth_name": 'pick_lang("باقة النمو", "Growth Plan", "Forfait Croissance", "Büyüme Planı", "Wachstums-Tarif", "Plan Crecimiento")',
    "plan_enterprise_name": 'pick_lang("باقة السلاسل (Enterprise)", "Enterprise Plan", "Forfait Entreprise", "Kurumsal Plan", "Enterprise-Tarif", "Plan Cadenas (Enterprise)")',
    "plan_trial_name": 'pick_lang("باقة التجربة المجانية", "Free Trial Plan", "Forfait Essai Gratuit", "Ücretsiz Deneme Planı", "Kostenloser Test-Tarif", "Plan de Prueba Gratuita")',
    "plan_basic_name": 'pick_lang("الباقة الأساسية", "Basic Plan", "Forfait De Base", "Temel Plan", "Basis-Tarif", "Plan Básico")',
    "plan_pro_name": 'pick_lang("الباقة المتقدمة (Pro)", "Pro Plan", "Forfait Pro", "Pro Planı", "Pro-Tarif", "Plan Avanzado (Pro)")',

    "plan_starter_desc": 'pick_lang("مثالية للمطاعم الفردية والكافيهات وعربات الطعام", "Ideal for individual restaurants, food trucks, and single-branch cafes", "Idéal pour les restaurants indépendants, food trucks et cafés à succursale unique", "Tek şubeli restoranlar, yemek kamyonları ve kafeler için ideal", "Ideal für Einzelrestaurants, Food Trucks und Cafés mit einer Filiale", "Ideal para restaurantes individuales, cafeterías y food trucks de una sola sede")',
    "plan_growth_desc": 'pick_lang("للمطاعم المتنامية وسلاسل الفروع مع كول سنتر الذكاء الاصطناعي وجرد المخزون", "For scaling restaurant chains with AI call center and smart inventory", "Pour les chaînes en expansion avec centre d\'appels IA et inventaire intelligent", "Yapay zeka çağrı merkezi ve akıllı envanter ile büyüyen restoran zincirleri için", "Für wachsende Restaurantketten mit KI-Callcenter und intelligenter Inventur", "Para cadenas en expansión con Call Center de IA y control inteligente de inventario")',
    "plan_enterprise_desc": 'pick_lang("فروع وموظفون غير محدودين مع خوادم سحابية مستقلة ودعم VIP مخصص", "Unlimited branches and staff with dedicated cloud servers and VIP support", "Succursales et personnel illimités avec serveurs dédiés et support VIP", "Özel bulut sunucuları ve VIP destek ile sınırsız şube ve personel", "Unbegrenzte Filialen und Mitarbeiter mit dedizierten Servern und VIP-Support", "Sucursales y empleados ilimitados con servidores en la nube dedicados y soporte VIP")',
    "plan_trial_desc": 'pick_lang("فترة تجريبية مجانية 14 يوماً مع كافة إمكانيات الكاشير وإدارة المطبخ", "Free 14-day trial for essential restaurant and cashier operations", "Essai gratuit de 14 jours pour les opérations de caisse et de cuisine", "Temel restoran ve kasiyer operasyonları için 14 günlük ücretsiz deneme", "Kostenlose 14-Tage-Testversion für Kassen- und Restaurantabläufe", "Prueba gratuita de 14 días con todas las funciones de TPV y gestión de cocina")',
    "plan_basic_desc": 'pick_lang("مصممة للمطاعم الصغيرة والعلامات الناشئة بفروع محدودة", "Designed for small restaurants and emerging brands with limited branches", "Conçu pour les petits restaurants et marques émergentes avec succursales limitées", "Sınırlı şubesi olan küçük restoranlar ve gelişen markalar için tasarlandı", "Entwickelt für kleine Restaurants und aufstrebende Marken mit wenigen Filialen", "Diseñado para pequeños restaurantes y marcas emergentes con sucursales limitadas")',
    "plan_pro_desc": 'pick_lang("باقة شاملة تضم كول سنتر الذكاء الاصطناعي، إدارة أسطول التوصيل، وصلاحيات مخصصة", "Comprehensive suite with AI phone call center, delivery dispatch, and custom RBAC", "Suite complète avec centre d\'appels IA, expédition des livraisons et rôles RBAC personnalisés", "Yapay zeka çağrı merkezi, teslimat dağıtımı ve özel yetkilendirme içeren kapsamlı paket", "Umfassendes Paket mit KI-Telefon-Callcenter, Lieferdisposition und benutzerdefinierten Rollen", "Paquete integral con Call Center de IA, gestión de repartidores y permisos avanzados")',

    # FAQ & CTA & Footer
    "landing_faq_badge": 'pick_lang("إجابات واضحة", "Clear Answers", "Réponses claires", "Net Cevaplar", "Klare Antworten", "Respuestas Claras")',
    "landing_faq_heading": 'pick_lang("الأسئلة الشائعة", "Frequently Asked Questions", "Foire aux questions", "Sıkça Sorulan Sorular", "Häufig gestellte Fragen", "Preguntas Frecuentes")',
    "landing_faq_q1": 'pick_lang("هل أحتاج لشراء أجهزة كاشير مخصصة ومكلفة للبدء؟", "Do I need to purchase expensive, proprietary POS hardware to get started?", "Dois-je acheter du matériel de caisse propriétaire et coûteux pour commencer ?", "Başlamak için pahalı ve tescilli POS donanımı satın almam gerekir mi?", "Muss ich teure, proprietäre POS-Hardware kaufen, um zu beginnen?", "¿Necesito comprar hardware de TPV costoso y exclusivo para comenzar?")',
    "landing_faq_a1": 'pick_lang("لا، تعمل منصة «مطاعم» بالكامل سحابياً من خلال أي متصفح ويب على أجهزة الآيباد، التابلت، أجهزة الكمبيوتر المحمولة، أو شاشات نقاط البيع اللمسية الحالية لديك دون الحاجة لأجهزة مخصصة.", "No. Motaem runs 100% in the cloud on any modern web browser across iPads, tablets, laptops, or your existing touch POS screens without proprietary hardware.", "Non. Motaem fonctionne à 100% dans le cloud sur n\'importe quel navigateur moderne sur iPad, tablettes, ordinateurs portables ou vos écrans tactiles actuels sans matériel dédié.", "Hayır. Motaem, iPad\'ler, tabletler, dizüstü bilgisayarlar veya mevcut dokunmatik POS ekranlarınızda herhangi bir modern web tarayıcısında %100 bulut üzerinde çalışır.", "Nein. Motaem läuft zu 100 % in der Cloud auf jedem modernen Webbrowser auf iPads, Tablets, Laptops oder Ihren vorhandenen Touchscreens ohne proprietäre Hardware.", "No. Motaem funciona al 100% en la nube desde cualquier navegador web en iPad, tablet, ordenador portátil o pantalla táctil existente sin hardware propietario.")',
    "landing_faq_q2": 'pick_lang("كيف يعمل كول سنتر الذكاء الاصطناعي في استقبال الطلبات؟", "How does the AI Phone Agent handle incoming phone orders?", "Comment l\'agent téléphonique IA gère-t-il les commandes entrantes ?", "Yapay Zeka Telefon Temsilcisi gelen telefon siparişlerini nasıl yönetir?", "Wie nimmt der KI-Telefonagent eingehende telefonische Bestellungen entgegen?", "¿Cómo gestiona el Call Center de IA los pedidos entrantes por teléfono?")',
    "landing_faq_a2": 'pick_lang("يتصل النظام برقم هاتف مطعمك ويستقبل المكالمات الصوتية بصوت طبيعي يفهم اللهجات بدقة، يسأل العميل عن طلبه وعنوانه، ثم يقوم آلياً بتسجيل الطلب في شاشة المطبخ (KDS) وإرسال إشعار للكاشير فوراً.", "The system connects to your restaurant phone line, answers customer calls with natural voice, understands dialects, captures order details and delivery addresses, and instantly pushes the ticket to the kitchen display (KDS).", "Le système se connecte à la ligne téléphonique de votre restaurant, répond aux appels d\'une voix naturelle, comprend les dialectes, enregistre les détails et transmet le ticket au KDS.", "Sistem restoran telefon hattınıza bağlanır, aramaları doğal sesle yanıtlar, lehçeleri anlar, sipariş ve adres bilgilerini alır ve fişi anında mutfak ekranına (KDS) iletir.", "Das System verbindet sich mit Ihrer Telefonleitung, nimmt Anrufe mit natürlicher Stimme an, versteht Dialekte, erfasst Bestelldaten und sendet das Ticket sofort an das Küchensystem (KDS).", "El sistema se conecta a tu línea telefónica, atiende llamadas con voz natural, comprende dialectos, toma los datos del pedido y dirección, y envía la comanda al instante al KDS de cocina.")',
    "landing_faq_q3": 'pick_lang("هل يمكنني تحديد أسعار مختلفة لنفس الطبق بين الفروع؟", "Can I set different menu prices for the same dish across different branches?", "Puis-je définir des prix de menu différents pour le même plat entre les succursales ?", "Aynı yemek için farklı şubelerde farklı menü fiyatları belirleyebilir miyim?", "Kann ich für dasselbe Gericht in verschiedenen Filialen unterschiedliche Preise festlegen?", "¿Puedo fijar precios diferentes para el mismo plato según la sucursal?")',
    "landing_faq_a3": 'pick_lang("نعم بكل تأكيد، تتيح منصة «مطاعم» ميزة \\"تسعير الفرع المستقل\\" حيث يمكنك ضبط سعر خاص لكل صنف وحجم حسب تكلفة وتشغيل كل فرع، مع بقاء إدارة المنيو والصور مركزية وموحدة.", "Yes, absolutely. Motaem supports independent branch-level pricing, allowing you to set customized prices for each branch location while keeping menu catalog items centrally managed.", "Oui, absolument. Motaem prend en charge la tarification indépendante au niveau de la succursale tout en conservant une gestion centrale des menus.", "Evet, kesinlikle. Motaem, menü kataloğu öğelerini merkezi olarak yönetirken, her şube konumu için özel fiyatlar belirlemenize olanak tanır.", "Ja, absolut. Motaem unterstützt unabhängige Filialpreise, sodass Sie individuelle Preise für jeden Standort festlegen können, während die Menüverwaltung zentral bleibt.", "Sí, totalmente. Motaem admite fijación de precios independiente por sucursal, permitiendo ajustar tarifas para cada sede mientras la carta central se mantiene unificada.")',
    "landing_cta_heading": 'pick_lang("جاهز لنقل تشغيل مطاعمك وسلسلة فروعك إلى المستقبل؟", "Ready to Elevate Your Restaurant Chain into the Future?", "Prêt à propulser votre chaîne de restaurants vers le futur ?", "Restoran Zincirinizi Geleceğe Taşımaya Hazır mısınız?", "Bereit, Ihre Restaurantkette in die Zukunft zu führen?", "¿Listo para Impulsar tus Restaurantes hacia el Futuro?")',
    "landing_cta_desc": 'pick_lang("انضم الآن للمطاعم التي تعتمد على «مطاعم» يومياً لرفع سرعة المطبخ وزيادة أرباح الفروع بدون تعقيد.", "Join thriving hospitality brands that rely on Motaem every day to accelerate kitchen workflows and boost profitability without complexity.", "Rejoignez les enseignes de restauration qui comptent sur Motaem chaque jour pour accélérer le travail en cuisine et augmenter leurs profits.", "Mutfak iş akışlarını hızlandırmak ve kârlılığı artırmak için her gün Motaem\'e güvenen başarılı markalara katılın.", "Schließen Sie sich erfolgreichen Gastronomiebetrieben an, die täglich auf Motaem vertrauen, um Arbeitsabläufe zu beschleunigen und Erträge zu steigern.", "Únete a las marcas líderes que confían en Motaem cada día para acelerar la cocina y aumentar beneficios sin complicaciones.")',
    "landing_cta_btn": 'pick_lang("سجل مطعمك وابدأ التجربة المجانية 14 يوماً ←", "Register Your Restaurant & Start Free 14-Day Trial →", "Inscrivez votre restaurant et démarrez l\'essai gratuit de 14 jours →", "Restoranınızı Kaydedin ve 14 Günlük Ücretsiz Denemeyi Başlatın →", "Registrieren Sie Ihr Restaurant & starten Sie den 14-Tage-Test →", "Registra tu Restaurante y Comienza la Prueba Gratuita de 14 Días →")',
    "landing_footer_desc": 'pick_lang("— سحابة تشغيل سلاسل المطاعم الحديثة", "— Modern Cloud Restaurant Operating System", "— Système d\'exploitation cloud moderne pour restaurants", "— Modern Bulut Restoran İşletim Sistemi", "— Modernes Cloud-Restaurant-Betriebssystem", "— Sistema Operativo Cloud para Cadenas de Restaurantes Modernas")',
    "landing_footer_status": 'pick_lang("كافة الخدمات السحابية تعمل بكفاءة 100%", "All Cloud Services Operational 100%", "Tous les services cloud fonctionnent à 100%", "Tüm Bulut Hizmetleri %100 Çalışıyor", "Alle Cloud-Dienste zu 100 % betriebsbereit", "Todos los Servicios en la Nube Operativos al 100%")',
    "landing_footer_rights": 'pick_lang("© 2026 جميع الحقوق محفوظة", "© 2026 All Rights Reserved", "© 2026 Tous droits réservés", "© 2026 Tüm Hakları Saklıdır", "© 2026 Alle Rechte vorbehalten", "© 2026 Todos los Derechos Reservados")',

    # System UI
    "sidebar_resize_tooltip": 'pick_lang("اسحب لتغيير حجم القائمة | نقر مزدوج لإعادة العرض الأصلي (288px)", "Drag to resize sidebar | Double click to reset width (288px)", "Faites glisser pour redimensionner | Double-cliquez pour réinitialiser (288px)", "Kenar çubuğunu yeniden boyutlandırmak için sürükleyin | Sıfırlamak için çift tıklayın (288px)", "Ziehen zum Anpassen der Leiste | Doppelklick zum Zurücksetzen (288px)", "Arrastra para cambiar el tamaño | Doble clic para restablecer (288px)")',
    "sub_banner_expired_title": 'pick_lang("تنبيه: اشتراك المنشأة منتهي أو معلق", "Warning: Organization subscription expired or suspended", "Avertissement : L\'abonnement de l\'organisation a expiré ou est suspendu", "Uyarı: Kuruluş aboneliğinin süresi doldu veya askıya alındı", "Warnung: Organisationsabonnement abgelaufen oder ausgesetzt", "Aviso: La suscripción del establecimiento ha caducado o está suspendida")',
    "sub_banner_expired_desc": 'pick_lang("باقتك الحالية انتهت صلاحيتها. يرجى التواصل مع إدارة المنصة لتجديد الاشتراك واستعادة كافة الصلاحيات.", "Your active plan has expired. Please contact platform administration to renew your subscription and restore all capabilities.", "Votre forfait actif a expiré. Veuillez contacter l\'administration de la plateforme pour renouveler votre abonnement.", "Aktif planınızın süresi doldu. Aboneliğinizi yenilemek için lütfen platform yönetimiyle iletişime geçin.", "Ihr aktiver Tarif ist abgelaufen. Bitte kontaktieren Sie die Administration, um Ihr Abonnement zu erneuern.", "Tu plan activo ha caducado. Por favor, contacta con la administración para renovar la suscripción.")',
    "sub_banner_expired_badge": 'pick_lang("منتهي الصلاحية", "Expired", "Expiré", "Süresi Doldu", "Abgelaufen", "Caducado")',
    "sub_banner_expiring_title": 'pick_lang("تذكير: اشتراك منشأتك ينتهي قريباً", "Reminder: Organization subscription expires soon", "Rappel : L\'abonnement de votre organisation expire bientôt", "Hatırlatma: Kuruluş aboneliğiniz yakında sona eriyor", "Erinnerung: Organisationsabonnement läuft bald ab", "Recordatorio: La suscripción de tu establecimiento caduca pronto")',
    "sub_banner_expiring_badge": 'pick_lang("قرب الانتهاء", "Expiring Soon", "Expire bientôt", "Yakında Bitiyor", "Läuft bald ab", "Próximo a Caducar")',
}

new_lines = []
for line in lines:
    stripped = line.strip()
    # 1. Update supported_langs
    if stripped == 'supported_langs = ["ar", "en", "fr", "tr", "de"]':
        new_lines.append('    supported_langs = ["ar", "en", "fr", "tr", "de", "es"]\n')
        continue

    # 2. Update docstring
    if 'Arabic, English, French, Turkish, German' in line:
        line = line.replace('Arabic, English, French, Turkish, German', 'Arabic, English, French, Turkish, German, Spanish')

    # 3. Update pick_lang signature
    if stripped == 'def pick_lang(ar_text, en_text, fr_text=None, tr_text=None, de_text=None):':
        new_lines.append('    def pick_lang(ar_text, en_text, fr_text=None, tr_text=None, de_text=None, es_text=None):\n')
        continue

    # 4. In pick_lang body, add elif lang == "es": val = es_text or en_text
    if stripped == 'elif lang == "de":':
        new_lines.append(line)
        continue
    if stripped == 'val = de_text or en_text':
        new_lines.append(line)
        new_lines.append('        elif lang == "es":\n')
        new_lines.append('            val = es_text or en_text\n')
        continue

    # 5. base_t replacements: match '"key": pick_lang('
    replaced = False
    for k, new_v in SPANISH_BASE_T.items():
        if stripped.startswith(f'"{k}": pick_lang('):
            new_lines.append(f'        "{k}": {new_v},\n')
            replaced = True
            break
    if replaced:
        continue

    # 6. Add Spanish language definitions
    if stripped == '"switch_to_german": "Zu Deutsch wechseln",':
        new_lines.append(line)
        new_lines.append('        "switch_to_spanish": "Cambiar a Español",\n')
        continue
    if stripped == '"language_german": "Deutsch",':
        new_lines.append(line)
        new_lines.append('        "language_spanish": "Español",\n')
        continue

    # 7. lang_names, lang_flags, languages_list
    if stripped == '"de": "Deutsch",':
        new_lines.append(line)
        new_lines.append('        "es": "Español",\n')
        continue
    if stripped == '"de": "🇩🇪",':
        new_lines.append(line)
        new_lines.append('        "es": "🇪🇸",\n')
        continue
    if stripped == '{"code": "de", "name": "Deutsch", "flag": "🇩🇪", "is_active": (lang == "de")},':
        new_lines.append(line)
        new_lines.append('        {"code": "es", "name": "Español", "flag": "🇪🇸", "is_active": (lang == "es")},\n')
        continue

    new_lines.append(line)

with open(target_file, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"✔ Successfully updated {target_file}")
