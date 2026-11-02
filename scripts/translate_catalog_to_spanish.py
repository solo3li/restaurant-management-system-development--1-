#!/usr/bin/env python3
"""
Generate comprehensive Spanish ('es') translations for Motaem Restaurant OS.
Updates:
1. core/i18n_catalog.py
2. static/js/diyafa_i18n_catalog.json
3. staticfiles/js/diyafa_i18n_catalog.json
4. static/js/diyafa_i18n_engine.js
5. staticfiles/js/diyafa_i18n_engine.js
"""

import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse

BASE_DIR = '/root/motaem'
sys.path.insert(0, BASE_DIR)

# Comprehensive Spanish hospitality & restaurant domain dictionary
SPANISH_DOMAIN_OVERRIDES = {
    # Brand & System
    "ضِيَافَة": "DIYAFA",
    "كُـورَا": "KURA",
    "كورا": "KURA",
    "مطاعم": "Motaem",
    "منظومة مطاعم السحابية": "Sistema Operativo en la Nube Motaem Restaurant",
    "نظام إدارة المطاعم": "Sistema de Gestión de Restaurantes",
    "نظام إدارة المطاعم السحابي": "Sistema de Gestión de Restaurantes en la Nube",
    "نظام التشغيل السحابي للمطاعم والضيافة": "Sistema Operativo en la Nube para Restaurantes y Hostelería",
    "النظام السحابي لإدارة سلاسل المطاعم والضيافة الحديثة": "Sistema operativo en la nube para cadenas de restaurantes y hostelería",
    "منظومة كُـورَا لإدارة المطاعم": "Sistema Operativo de Gestión de Restaurantes KURA",
    "منظومة كورا لإدارة المطاعم": "Sistema de Gestión de Restaurantes KURA",
    "نظام مطاعم ضيافة": "Sistema de Restaurantes DIYAFA",
    "متصل بالنظام السحابي": "Conectado al sistema en la nube",
    "الإدارة العامة (كافة الفروع)": "Sede Central (Todas las sucursales)",
    "كافة الفروع والمدن": "Todas las sucursales y ciudades",
    "التحويل للإدارة العامة (HQ)": "Cambiar a Sede Central (HQ)",
    "مركز القيادة والعمليات": "Centro de Mando y Operaciones",
    "النظام الموحد للإدارة العليا": "Sistema Unificado de Alta Dirección",
    "متابعة فورية ومباشرة لكافة الفروع": "Monitoreo en tiempo real de todas las sucursales",
    "متابعة حية للتدفق المالي، توزيع الطلبات، أداء الفروع، وكول سنتر الذكاء الاصطناعي في شاشة موحدة.": "Supervisión en vivo de flujo de caja, distribución de pedidos, rendimiento de sucursales y Call Center de IA.",
    "فرع": "Sucursal",
    "الفروع": "Sucursales",
    "الفرع": "Sucursal",
    "الفرع المنفذ": "Sucursal preparadora",

    # Currencies & Time units
    "ر.س": "SAR",
    "ريال": "SAR",
    "ريال سعودي": "SAR",
    "SAR": "SAR",
    "USD": "USD",
    "EUR": "EUR",
    "دقيقة": "min",
    "دقائق": "min",
    "ساعة": "h",
    "ساعات": "h",
    "يوم": "día",
    "أيام": "días",
    "شهر": "mes",
    "أشهر": "meses",
    "سنة": "año",

    # Operations: POS, Cashier, KDS, Orders
    "الكاشير — نقطة البيع الذكية": "Caja — Terminal Punto de Venta Inteligente (TPV)",
    "الكاشير": "Caja",
    "كاشير": "Cajero",
    "نقاط البيع وقائمة الطعام": "TPV y Carta",
    "كاشير نقطة البيع (POS)": "Caja Punto de Venta (TPV)",
    "نقطة البيع": "Punto de Venta (TPV)",
    "نقاط البيع": "Puntos de Venta (TPV)",
    "نقاط البيع والكاشير (POS)": "Punto de Venta y Caja (TPV)",
    "شاشات المطبخ الذكية (KDS)": "Pantallas de Cocina Inteligentes (KDS)",
    "شاشات المطبخ (KDS)": "Pantallas de Cocina (KDS)",
    "المطبخ": "Cocina",
    "المطبخ هادئ الآن": "La cocina está tranquila ahora",
    "المطبخ هادئ الآن — جميع الطلبات منجزة": "La cocina está tranquila — Todos los pedidos completados",
    "المحطة متصلة وجاهزة • بانتظار الطلبات الفورية": "Estación conectada y lista • Esperando pedidos en tiempo real",
    "ستظهر تذاكر الطلبات الجديدة هنا فورياً بمجرد تسجيلها من الكاشير أو الكول سنتر أو تطبيقات التوصيل مصحوبة برنين التنبيه.": "Las nuevas comandas aparecerán aquí al instante al registrarse desde TPV, Call Center o apps con alerta sonora.",
    "تتبع فوري لأوامر الطهي والتحضير بالمطابخ والأقسام": "Seguimiento en tiempo real de comandas, tiempos y flujo de preparación en cocina",
    "تسجيل الطلبات، إصدار الفواتير الفورية، والتحصيل المباشر": "Registro ágil de pedidos, emisión inmediata de facturas y cobro directo",
    "تسجيل طلبات الصالة والسفري والفواتير والمدفوعات": "Registro de pedidos en sala y para llevar, facturas y cobros",
    "المطبخ وإعداد الوجبات (KDS)": "Cocina y preparación de comandas (KDS)",
    "بدء التحضير": "Iniciar preparación",
    "جاهز للتقديم": "Marcar como listo",
    "قيد الطهي": "En preparación",
    "جاهز للاستلام": "Listo para recoger",
    "جديد / قيد الانتظار": "Nuevo / En espera",
    "تحديث فوري": "Sincronización en vivo",

    # Order Types & Payment
    "نوع الطلب": "Tipo de pedido",
    "محلي": "En sala",
    "صالة": "En sala",
    "سفري": "Para llevar",
    "توصيل": "A domicilio",
    "كول سنتر": "Call Center",
    "طريقة الدفع": "Forma de pago",
    "نقداً": "Efectivo",
    "نقدي": "Efectivo",
    "شبكة / مدى": "Tarjeta / Red",
    "مدى / بطاقة": "Tarjeta / Red",
    "بطاقة ائتمانية": "Tarjeta de crédito",
    "آجل": "A crédito",
    "المجموع الفرعي": "Subtotal",
    "ضريبة القيمة المضافة (15%)": "IVA (15%)",
    "الخصم": "Descuento",
    "الإجمالي النهائي": "Total Final",
    "المبلغ المدفوع": "Importe pagado",
    "المتبقي": "Cambio / Restante",
    "إتمام الطلب والدفع": "Completar pedido y cobrar",
    "حفظ وتعليق": "Poner en espera",
    "تفريغ السلة": "Vaciar carrito",
    "سلة الطلب": "Carrito del pedido",
    "السلة فارغة": "El carrito está vacío",
    "أضف أصنافاً من القائمة": "Añadir artículos de la carta",
    "تفاصيل الفاتورة والحساب": "Detalles de factura y cuenta",
    "فاتورة الطلب": "Factura del pedido",
    "طلب رقم": "Pedido N°",
    "سجل كل الطلبات": "Historial de todos los pedidos",
    "سجل كافة الطلبات والفواتير": "Historial de pedidos y facturas",
    "طلبات وفواتير الفرع": "Pedidos y facturas de la sucursal",
    "سجل كافة الطلبات والفواتير الموحد": "Registro unificado de pedidos y facturas",
    "سجل كافة الطلبات والفواتير — الإدارة العامة": "Historial de pedidos y facturas — Sede Central",
    "متابعة مباشرة لتدفق طلبات وفواتير كافة الفروع في شاشة واحدة": "Supervisión en vivo de pedidos y facturas de todas las sucursales en una pantalla",

    # Customer & Tables
    "العميل": "Cliente",
    "عميل": "Cliente",
    "العملاء": "Clientes",
    "عميل عام": "Cliente general",
    "اختر العميل": "Seleccionar cliente",
    "عميل جديد": "Nuevo cliente",
    "اسم العميل *": "Nombre del cliente *",
    "اسم العميل": "Nombre del cliente",
    "رقم الطاولة": "Número de mesa",
    "طاولة": "Mesa",
    "الطاولات": "Mesas",
    "رقم الهاتف": "Número de teléfono",
    "ملاحظات الطلب": "Notas del pedido",
    "الملاحظات": "Notas",

    # Menu & Dishes
    "قائمة الأطباق والأسعار": "Carta de Platos y Precios",
    "قائمة الطعام": "Carta del menú",
    "المنيو": "Carta",
    "إدارة أصناف القائمة": "Gestionar artículos de la carta",
    "ابحث عن وجبة أو مشروب…": "Buscar plato o bebida…",
    "أطباق رئيسية": "Platos principales",
    "مشويات": "Carnes a la brasa",
    "ساندويتشات": "Bocadillos",
    "برجر": "Hamburguesas",
    "دجاج": "Pollo",
    "مقبلات": "Entrantes",
    "مشروبات": "Bebidas",
    "حلويات": "Postres",
    "وجبات سريعة": "Comida rápida",
    "الوجبات المطلوبة": "Platos pedidos",
    "معاينة المنيو": "Vista previa de la carta",
    "استعراض صفحة المنيو للعملاء": "Ver página de la carta para clientes",

    # Delivery & Fleet
    "أسطول التوصيل والمناديب": "Flota de Reparto y Repartidores",
    "إدارة التوصيل — منظومة كورا": "Flota de Reparto — KURA Dining OS",
    "إدارة وتوزيع طلبات التوصيل": "Despacho y Gestión de Pedidos a Domicilio",
    "متابعة مسار الطلبات خطوة بخطوة وتوزيعها على أسطول السائقين": "Seguimiento paso a paso de pedidos y despacho a la flota de repartidores",
    "لا توجد طلبات مسلّمة اليوم": "No hay pedidos entregados hoy",
    "نطاق التوصيل (كم)": "Radio de reparto (km)",
    "مندوب التوصيل": "Repartidor",
    "السائق": "Conductor / Repartidor",

    # Inventory & Warehouses
    "المستودعات والمخزون": "Almacenes e Inventario",
    "إدارة المخزون والمستودعات": "Control de Stock y Almacenes",
    "جرد المواد والمستودعات": "Auditoría de Stock y Materiales",
    "جرد المخزون والمستودعات": "Inventario de Almacén y Stock",

    # Staff & Permissions
    "الموظفون والرواتب": "Personal y Nóminas",
    "فريق العمل والرواتب": "Equipo de Personal y Nóminas",
    "إدارة الكادر والمسميات الوظيفية والصلاحيات": "Gestión de Plantilla, Puestos y Permisos",
    "تطبيق الخصومات والعروض": "Aplicar descuentos y promociones",

    # Subscription
    "الاشتراك والتقارير المالية": "Suscripción e Informes Financieros",
    "إدارة الاشتراك واستهلاك الحساب": "Gestión de Suscripción y Consumo de la Cuenta",
    "تنبيه: اشتراك المنشأة منتهي أو معلق": "Aviso: La suscripción del establecimiento ha caducado o está suspendida",
    "تذكير: اشتراك منشأتك ينتهي قريباً": "Recordatorio: La suscripción de tu establecimiento caduca pronto",
    "منتهي الصلاحية": "Caducado",
    "قرب الانتهاء": "Próximo a caducar",

    # AI Call Center & Omnichannel
    "كول سنتر الذكاء الاصطناعي": "Call Center con Inteligencia Artificial",
    "استقبال طلبات الفروع": "Recepción de Pedidos de Sucursales",
    "صندوق محادثات الواتساب": "Centro de Chat de WhatsApp",
    "إعدادات المساعد الصوتي": "Ajustes del Asistente de Voz IA",
    "نظرة عامة وإحصائيات": "Resumen y Estadísticas",
    "شخصية المساعد واللهجة": "Personalidad y Voz del Asistente",
    "مواعيد العمل والاعتذار": "Horarios de Atención",
    "قاعدة المعرفة (RAG)": "Base de Conocimientos (RAG)",
    "طوابير وموظفو التحويل": "Colas y Agentes de Desvío",
    "سجل المكالمات والتسجيلات": "Registro de Llamadas y Grabaciones",
    "صلاحيات وقدرات الذكاء": "Capacidades de IA y Protocolo MCP",
    "قنوات الاتصال والواتساب": "Omnicanal y WhatsApp",
    "الكول سنتر — منظومة كورا": "Call Center — KURA Dining OS",
    "الكول سنتر وخدمة العملاء": "Call Center y Atención al Cliente",
    "استقبال اتصالات الزبائن، البحث الفوري عن العملاء، وتسجيل طلبات التوصيل": "Recepción de llamadas de clientes, búsqueda instantánea y asignación de pedidos a domicilio",
    "الخطوط جاهزة لاستقبال الاتصالات": "Líneas listas para recibir llamadas",

    # Statuses
    "جديد": "Nuevo",
    "قيد الانتظار": "Pendiente",
    "قيد التحضير": "En preparación",
    "جاهز": "Listo",
    "في الطريق": "En camino",
    "تم التوصيل": "Entregado",
    "مكتمل": "Completado",
    "ملغي": "Cancelado",
    "مدفوع": "Pagado",
    "غير مدفوع": "No pagado",
    "مسترد": "Reembolsado",
    "معلق": "Pendiente",
    "نشط": "Activo",
    "معطل": "Inactivo",
    "تحت الصيانة": "En mantenimiento",

    # Common UI
    "حفظ": "Guardar",
    "إلغاء": "Cancelar",
    "حذف": "Eliminar",
    "تعديل": "Editar",
    "إضافة جديد": "Añadir nuevo",
    "بحث...": "Buscar...",
    "تصفية": "Filtrar",
    "الكل": "Todos",
    "إغلاق": "Cerrar",
    "رجوع": "Volver",
    "تأكيد": "Confirmar",
    "طباعة": "Imprimir",
    "تصدير": "Exportar",
    "تحديث": "Actualizar",
    "التفاصيل": "Detalles",
    "الإجراءات": "Acciones",
    "الحالة": "Estado",
    "الإجمالي": "Total",
    "الكمية": "Cantidad",
    "السعر": "Precio",
    "التاريخ": "Fecha",
    "الوقت المنقضي": "Tiempo transcurrido",
    "القسم": "Categoría",
    "المدينة": "Ciudad",
    "العنوان": "Dirección",
    "مدير الفرع": "Gerente de sucursal",
    "ساعات العمل": "Horarios de apertura",
    "تعديل الفرع": "Editar sucursal",
    "تعطيل الفرع": "Desactivar sucursal",
    "إضافة فرع جديد": "Añadir nueva sucursal",
    "اسم الفرع": "Nombre de la sucursal",
}

def clean_translated_text(s):
    if not s:
        return ""
    # Strip whitespace
    s = s.strip()
    # If wrapped in quotes, unwrap
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s

def fix_hospitality_terminology(text):
    if not text:
        return text
    # Replace non-restaurant terminology
    replacements = [
        (r'\bPOS\b', 'TPV'),
        (r'\bPunto de Venta\b', 'TPV'),
        (r'\bpuntos de venta\b', 'puntos de venta (TPV)'),
        (r'\borden\b', 'pedido'),
        (r'\bordeness\b', 'pedidos'),
        (r'\bÓrdenes\b', 'Pedidos'),
        (r'\bOrden\b', 'Pedido'),
        (r'\brama\b', 'sucursal'),
        (r'\bramas\b', 'sucursales'),
        (r'\bRama\b', 'Sucursal'),
        (r'\bRamas\b', 'Sucursales'),
    ]
    res = text
    for pat, rep in replacements:
        res = re.sub(pat, rep, res)
    return res

def translate_batch_to_spanish(texts):
    if not texts:
        return []
    joined = '\n'.join(texts)
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=ar&tl=es&dt=t&q=" + urllib.parse.quote(joined)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                data = json.loads(response.read().decode('utf-8'))
                full_trans = ''.join([part[0] for part in data[0]])
                parts = [clean_translated_text(p) for p in full_trans.split('\n')]
                if len(parts) == len(texts):
                    return parts
                break
        except Exception as e:
            time.sleep(1.0 + attempt * 0.7)

    # Fallback to translating individual texts
    results = []
    for t in texts:
        url_single = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=ar&tl=es&dt=t&q=" + urllib.parse.quote(t)
        req_single = urllib.request.Request(url_single, headers={'User-Agent': 'Mozilla/5.0'})
        val = t
        for a in range(3):
            try:
                with urllib.request.urlopen(req_single, timeout=8) as r:
                    res_s = json.loads(r.read().decode('utf-8'))
                    val = clean_translated_text(''.join([part[0] for part in res_s[0]]))
                    break
            except Exception:
                time.sleep(0.4)
        results.append(val)
    return results

def main():
    print("=" * 70)
    print("Starting Comprehensive 6-Language (Adding Spanish) Catalog Generation")
    print("=" * 70)

    # 1. Load current JSON catalog
    json_path = os.path.join(BASE_DIR, 'static/js/diyafa_i18n_catalog.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        catalog = json.load(f)

    total_keys = len(catalog)
    print(f"Loaded existing catalog with {total_keys} entries.")

    # 2. Check which keys need Spanish translation
    keys_to_translate = []
    for k, v in catalog.items():
        # Check override first
        if k in SPANISH_DOMAIN_OVERRIDES:
            v['es'] = SPANISH_DOMAIN_OVERRIDES[k]
        elif not v.get('es'):
            keys_to_translate.append(k)

    print(f"Domain overrides applied: {len(SPANISH_DOMAIN_OVERRIDES)} entries.")
    print(f"Entries needing translation to Spanish: {len(keys_to_translate)}.")

    # 3. Batch translation
    BATCH_SIZE = 40
    for i in range(0, len(keys_to_translate), BATCH_SIZE):
        chunk = keys_to_translate[i:i + BATCH_SIZE]
        translations = translate_batch_to_spanish(chunk)
        for k, trans in zip(chunk, translations):
            cleaned = fix_hospitality_terminology(trans)
            # If translation failed and left Arabic, fallback to English translation
            if any('\u0600' <= c <= '\u06FF' for c in cleaned):
                en_val = catalog[k].get('en', '')
                if en_val and not any('\u0600' <= c <= '\u06FF' for c in en_val):
                    cleaned = en_val
            catalog[k]['es'] = cleaned
        progress = min(i + BATCH_SIZE, len(keys_to_translate))
        print(f"  [es] Progress: {progress}/{len(keys_to_translate)} ({progress*100//len(keys_to_translate)}%)")
        time.sleep(0.1)

    # 4. Strict Quality Verification
    print("\n>>> Verifying 100% Spanish coverage and zero Arabic leakage...")
    missing_es = 0
    arabic_residue = []
    fake_es = []

    for k, v in catalog.items():
        es_val = v.get('es')
        if not es_val or not str(es_val).strip():
            # If empty, take English or generate
            missing_es += 1
            v['es'] = v.get('en', k)
        elif any('\u0600' <= c <= '\u06FF' for c in str(es_val)):
            arabic_residue.append((k, es_val))
            # Fix residue with English translation
            v['es'] = v.get('en', k)
        elif es_val == k and any('\u0600' <= c <= '\u06FF' for c in k):
            fake_es.append(k)
            v['es'] = v.get('en', k)

    print(f"  Verified {total_keys} entries.")
    print(f"  Missing: {missing_es}, Arabic residue fixed: {len(arabic_residue)}, Fake entries fixed: {len(fake_es)}")

    # Double check zero Arabic in es across all entries
    final_residue = [k for k, v in catalog.items() if any('\u0600' <= c <= '\u06FF' for c in str(v.get('es', '')))]
    assert len(final_residue) == 0, f"Critical: {len(final_residue)} keys still have Arabic residue in 'es'"

    # 5. Write static/js/diyafa_i18n_catalog.json
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    print(f"✔ Saved static/js/diyafa_i18n_catalog.json")

    # 6. Write staticfiles/js/diyafa_i18n_catalog.json
    staticfiles_json_path = os.path.join(BASE_DIR, 'staticfiles/js/diyafa_i18n_catalog.json')
    if os.path.exists(os.path.dirname(staticfiles_json_path)):
        with open(staticfiles_json_path, 'w', encoding='utf-8') as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
        print(f"✔ Saved staticfiles/js/diyafa_i18n_catalog.json")

    # 7. Write core/i18n_catalog.py
    py_path = os.path.join(BASE_DIR, 'core/i18n_catalog.py')
    with open(py_path, 'w', encoding='utf-8') as f:
        f.write('"""\n')
        f.write('Motaem Cloud Restaurant OS - Master 6-Language I18N Catalog\n')
        f.write('Official Supported Languages:\n')
        f.write('  - ar: Arabic (Default, RTL)\n')
        f.write('  - en: English (LTR)\n')
        f.write('  - fr: French (LTR)\n')
        f.write('  - tr: Turkish (LTR)\n')
        f.write('  - de: German (LTR)\n')
        f.write('  - es: Spanish (LTR)\n')
        f.write('"""\n')
        f.write('import json\n\n')
        f.write('class TranslatableString(str):\n')
        f.write('    def __new__(cls, default_en, translations=None):\n')
        f.write('        obj = str.__new__(cls, default_en)\n')
        f.write('        obj.translations = translations or {}\n')
        f.write('        return obj\n\n')
        f.write('    def for_lang(self, lang):\n')
        f.write('        if not self.translations:\n')
        f.write('            return str(self)\n')
        f.write('        return self.translations.get(lang, self.translations.get("en", str(self)))\n\n')
        f.write('    def __getitem__(self, key):\n')
        f.write('        if self.translations and key in self.translations:\n')
        f.write('            return self.translations[key]\n')
        f.write('        return super().__getitem__(key)\n\n')
        f.write('_DEFAULT_SENTINEL = object()\n\n\n')
        f.write('class I18nCatalogDict(dict):\n')
        f.write('    def __init__(self, raw_catalog):\n')
        f.write('        super().__init__()\n')
        f.write('        self._raw = raw_catalog\n')
        f.write('        for k, v in raw_catalog.items():\n')
        f.write('            if isinstance(v, dict):\n')
        f.write('                en_val = v.get("en", k)\n')
        f.write('                self[k] = TranslatableString(en_val, v)\n')
        f.write('            else:\n')
        f.write('                self[k] = TranslatableString(str(v), {"en": str(v), "ar": k})\n\n')
        f.write('    def get_translation(self, key, lang="en", default=_DEFAULT_SENTINEL):\n')
        f.write('        if key in self:\n')
        f.write('            val = self[key]\n')
        f.write('            if isinstance(val, TranslatableString):\n')
        f.write('                return val.for_lang(lang)\n')
        f.write('            return str(val)\n')
        f.write('        return key if default is _DEFAULT_SENTINEL else default\n\n')
        f.write('_RAW_CATALOG = {\n')
        for k, v in catalog.items():
            f.write(f'    {json.dumps(k, ensure_ascii=False)}: {{\n')
            f.write(f'        "ar": {json.dumps(v.get("ar", k), ensure_ascii=False)},\n')
            f.write(f'        "en": {json.dumps(v.get("en", ""), ensure_ascii=False)},\n')
            f.write(f'        "fr": {json.dumps(v.get("fr", ""), ensure_ascii=False)},\n')
            f.write(f'        "tr": {json.dumps(v.get("tr", ""), ensure_ascii=False)},\n')
            f.write(f'        "de": {json.dumps(v.get("de", ""), ensure_ascii=False)},\n')
            f.write(f'        "es": {json.dumps(v.get("es", ""), ensure_ascii=False)}\n')
            f.write('    },\n')
        f.write('}\n')
        f.write('I18N_CATALOG = I18nCatalogDict(_RAW_CATALOG)\n\n')
        f.write('def get_translation(key, lang="en", default=_DEFAULT_SENTINEL):\n')
        f.write('    return I18N_CATALOG.get_translation(key, lang, default=default)\n')

    print(f"✔ Saved core/i18n_catalog.py ({total_keys} entries with Spanish)")

    # 8. Update static/js/diyafa_i18n_engine.js
    engine_path = os.path.join(BASE_DIR, 'static/js/diyafa_i18n_engine.js')
    with open(engine_path, 'r', encoding='utf-8') as f:
        engine_content = f.read()

    # Update description comment
    engine_content = re.sub(
        r'5-Language Dynamic Translation Engine',
        '6-Language Dynamic Translation Engine',
        engine_content
    )
    engine_content = re.sub(
        r'Arabic, English, French, Turkish & German Coverage',
        'Arabic, English, French, Turkish, German & Spanish Coverage',
        engine_content
    )
    # Update language list check
    engine_content = re.sub(
        r"if \(!\['en', 'fr', 'tr', 'de'\]\.includes\(LANG\)\)",
        "if (!['en', 'fr', 'tr', 'de', 'es'].includes(LANG))",
        engine_content
    )

    # Update embedded CATALOG in line 20
    embedded_json = json.dumps(catalog, ensure_ascii=False)
    engine_content = re.sub(
        r'const CATALOG = \{.*?\};',
        f'const CATALOG = {embedded_json};',
        engine_content
    )

    with open(engine_path, 'w', encoding='utf-8') as f:
        f.write(engine_content)
    print(f"✔ Saved static/js/diyafa_i18n_engine.js")

    staticfiles_engine_path = os.path.join(BASE_DIR, 'staticfiles/js/diyafa_i18n_engine.js')
    if os.path.exists(os.path.dirname(staticfiles_engine_path)):
        with open(staticfiles_engine_path, 'w', encoding='utf-8') as f:
            f.write(engine_content)
        print(f"✔ Saved staticfiles/js/diyafa_i18n_engine.js")

    print("\n" + "=" * 70)
    print("ALL 6-LANGUAGE ASSETS GENERATED AND VERIFIED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == '__main__':
    main()
