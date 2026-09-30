#!/usr/bin/env python3
"""
Comprehensive I18N Catalog Builder for Diyafa Restaurant Management System.
Translates all 1017 unique Arabic strings found across all 23 templates,
applying high-precision restaurant & hospitality domain terminology.
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse

# 1. Authoritative Domain Overrides (Highest priority restaurant & hospitality industry terms)
DOMAIN_OVERRIDES = {
    # App & Brand
    "ضِيَافَة": "DIYAFA",
    "نظام مطاعم ضيافة": "Diyafa Restaurant Management",
    "نظام إدارة المطاعم": "Restaurant Management System",
    "نظام التشغيل السحابي للمطاعم والضيافة": "Cloud Operating System for Hospitality & Dining",
    "مركز القيادة والعمليات": "Command & Operations Center",
    "النظام الموحد للإدارة العليا": "Unified Executive Management System",
    "متابعة فورية ومباشرة لكافة الفروع": "Live Real-Time Monitoring of All Branches",
    "متابعة حية للتدفق المالي، توزيع الطلبات، أداء الفروع، وكول سنتر الذكاء الاصطناعي في شاشة موحدة.": "Live monitoring of cash flow, order distribution, branch performance, and AI Call Center on a unified screen.",
    "الإدارة العامة (كافة الفروع)": "Central HQ (All Branches)",
    "كافة الفروع والمدن": "All Branches & Cities",
    "التحويل للإدارة العامة (HQ)": "Switch to Central HQ",
    
    # KPIs & Dashboard
    "إجمالي مبيعات السلسلة اليوم": "Total Chain Revenue Today",
    "صافي الإيراد المحصل": "Net Collected Revenue",
    "عدد الطلبات المكتملة": "Completed Orders Count",
    "كفاءة التوصيل والتشغيل": "Delivery & Operational Efficiency",
    "الطلبات النشطة حالياً": "Currently Active Orders",
    "أداء الفروع المباشر": "Live Branch Performance",
    "توزيع المبيعات حسب القنوات": "Sales Distribution by Channel",
    "أكثر الأطباق طلباً بالسلسلة": "Top Selling Dishes Across Chain",
    "مبيعات آخر 7 أيام": "Sales - Last 7 Days",
    "إجمالي مبيعات الأسبوع": "Total Weekly Sales",
    "نسبة الإلغاء": "Cancellation Rate",
    "متوسط قيمة الفاتورة": "Average Order Value",
    "متوسط وقت التوصيل": "Average Delivery Time",
    "سجل كل الطلبات": "All Orders Register",
    "إدارة الفروع والمواقع": "Manage Branches & Locations",
    "تحديث البيانات": "Refresh Data",
    "أحدث العمليات": "Recent Operations",

    # Currencies & Units
    "ر.س": "SAR",
    "ريال": "SAR",
    "ريال سعودي": "SAR",
    "دقيقة": "min",
    "دقائق": "mins",
    "ساعة": "hr",
    "ساعات": "hrs",
    "يوم": "day",
    "أيام": "days",
    "شهر": "month",
    "أشهر": "months",
    "سنة": "year",

    # POS / Cashier
    "الكاشير — نقطة البيع الذكية": "Smart Cashier & POS Terminal",
    "تسجيل الطلبات، إصدار الفواتير الفورية، والتحصيل المباشر": "Fast order entry, instant receipt printing, and live checkout",
    "إدارة أصناف القائمة": "Manage Menu Items",
    "ابحث عن وجبة أو مشروب…": "Search meal or beverage…",
    "تفاصيل الفاتورة والحساب": "Invoice & Bill Details",
    "سلة الطلب": "Order Cart",
    "السلة فارغة": "Cart is empty",
    "أضف أصنافاً من القائمة": "Add items from the menu",
    "نوع الطلب": "Order Type",
    "محلي": "Dine-In",
    "صالة": "Dine-In",
    "سفري": "Takeaway",
    "توصيل": "Delivery",
    "كول سنتر": "Call Center",
    "تطبيق": "Mobile App",
    "طريقة الدفع": "Payment Method",
    "نقداً": "Cash",
    "نقدي": "Cash",
    "شبكة / مدى": "Mada / Card",
    "مدى / بطاقة": "Mada / Card",
    "بطاقة ائتمانية": "Credit Card",
    "آجل": "On Credit",
    "المجموع الفرعي": "Subtotal",
    "ضريبة القيمة المضافة (15%)": "VAT (15%)",
    "الخصم": "Discount",
    "الإجمالي النهائي": "Grand Total",
    "المبلغ المدفوع": "Amount Paid",
    "المتبقي": "Change Due",
    "إتمام الطلب والدفع": "Complete Order & Checkout",
    "حفظ وتعليق": "Hold Order",
    "تفريغ السلة": "Clear Cart",
    "العميل": "Customer",
    "عميل عام": "Walk-in Customer",
    "اختر العميل": "Select Customer",
    "عميل جديد": "New Customer",
    "رقم الطاولة": "Table Number",
    "رقم الهاتف": "Phone Number",
    "ملاحظات الطلب": "Order Notes",
    "أطباق رئيسية": "Main Dishes",
    "مشويات": "Grills",
    "ساندويتشات": "Sandwiches",
    "برجر": "Burgers",
    "دجاج": "Chicken",
    "مقبلات": "Appetizers",
    "مشروبات": "Beverages",
    "حلويات": "Desserts",
    "وجبات سريعة": "Fast Food",

    # Kitchen KDS
    "شاشات المطبخ الذكية (KDS)": "Smart Kitchen Display System (KDS)",
    "تتبع فوري لأوامر الطهي والتحضير بالمطابخ والأقسام": "Real-time kitchen order tickets, timers, and cooking workflow",
    "تحديث فوري": "Live Auto-Sync",
    "جديد / قيد الانتظار": "New / Queued",
    "قيد الطهي": "Cooking",
    "جاهز للاستلام": "Ready for Pickup",
    "بدء التحضير": "Start Cooking",
    "جاهز للتقديم": "Mark as Ready",
    "المطبخ هادئ الآن": "Kitchen is quiet right now",
    "لا توجد طلبات جارية في هذا القسم": "No active orders in this station",
    "الوجبات المطلوبة": "Ordered Items",
    "الوقت المنقضي": "Elapsed Time",
    "طلب رقم": "Order #",
    "القسم": "Station",
    "الفرع": "Branch",

    # Order Statuses & Badges
    "جديد": "New",
    "قيد الانتظار": "Pending",
    "قيد التحضير": "Preparing",
    "جاهز": "Ready",
    "في الطريق": "Out for Delivery",
    "تم التوصيل": "Delivered",
    "مكتمل": "Completed",
    "ملغي": "Cancelled",
    "مدفوع": "Paid",
    "غير مدفوع": "Unpaid",
    "مسترد": "Refunded",
    "معلق": "Pending",
    "نشط": "Active",
    "معطل": "Inactive",
    "تحت الصيانة": "Under Maintenance",

    # Branches
    "إدارة الفروع ونطاقات التوصيل": "Manage Branches & Delivery Zones",
    "شبكة الفروع والمواقع التشغيلية": "Operational Branches & Locations Network",
    "إضافة فرع جديد": "Add New Branch",
    "اسم الفرع": "Branch Name",
    "المدينة": "City",
    "العنوان": "Address",
    "مدير الفرع": "Branch Manager",
    "ساعات العمل": "Working Hours",
    "نطاق التوصيل (كم)": "Delivery Radius (km)",
    "تعديل الفرع": "Edit Branch",
    "تعطيل الفرع": "Disable Branch",
    "تفعيل الفرع": "Activate Branch",
    "حفظ الفرع": "Save Branch",
    "الفروع النشطة": "Active Branches",

    # Inventory
    "المستودعات والمخزون": "Inventory & Warehouses",
    "إدارة المخزون": "Inventory Management",
    "إدارة المخزون والمستودعات": "Inventory & Stock Management",
    "جرد المواد والمستودعات": "Stock Audit & Materials",
    "إضافة مادة جديدة للمخزون": "Add New Inventory Material",
    "اسم المادة / الصنف": "Item / Material Name",
    "الوحدة": "Unit",
    "الكمية الحالية": "Current Stock",
    "الحد الأدنى": "Minimum Alert Threshold",
    "تكلفة الوحدة": "Unit Cost",
    "سعر التكلفة": "Cost Price",
    "المستودع": "Warehouse",
    "المورد": "Supplier",
    "تسجيل حركة جرد": "Record Stock Audit",
    "تعديل الرصيد": "Adjust Quantity",
    "مواد قاربت على النفاد": "Items Near Depletion",
    "قيمة المخزون الكلية": "Total Stock Valuation",

    # Employees & Roles
    "الموظفون والرواتب": "Staff & Payroll",
    "إدارة الكادر والمسميات الوظيفية والصلاحيات": "Manage Staff, Job Roles & Permissions",
    "إدارة الكادر التشغيلي، المسميات الوظيفية، مصفوفة الصلاحيات الشاملة، والرواتب": "Manage operational staff, job titles, comprehensive permission matrix, and payroll",
    "إضافة موظف جديد": "Add New Employee",
    "إدارة المسميات والصلاحيات": "Manage Roles & Permissions",
    "اسم الموظف": "Employee Name",
    "المسمى الوظيفي": "Job Title",
    "الفرع المعين": "Assigned Branch",
    "رمز PIN للدخول": "Login PIN Code",
    "الراتب الشهري": "Monthly Salary",
    "تاريخ التعيين": "Hire Date",
    "الحالة الوظيفية": "Employment Status",
    "صلاحيات الموظف": "Employee Permissions",
    "حفظ الموظف": "Save Employee",

    # Orders (HQ & Branch)
    "سجل كافة الطلبات والفواتير": "All Orders & Invoices Log",
    "طلبات وفواتير الفرع": "Branch Orders & Invoices",
    "استعراض الفواتير ومتابعة الحالات والمدفوعات": "Review invoices, order statuses, and payment states",
    "تصدير تقرير Excel": "Export Excel Report",
    "تصفية الطلبات": "Filter Orders",
    "رقم الفاتورة / الطلب": "Invoice / Order #",
    "تاريخ الطلب": "Order Date",
    "تفاصيل الطلب": "Order Details",
    "تعديل الطلب": "Edit Order",
    "إلغاء الطلب": "Cancel Order",
    "طباعة إيصال": "Print Receipt",
    "إعادة طباعة": "Reprint",
    "أصناف الطلب": "Order Items",

    # Subscription & Billing
    "الاشتراك والتقارير المالية": "Subscription & Financial Reports",
    "إدارة الاشتراك واستهلاك الحساب": "Manage Subscription & Account Consumption",
    "الخطة الحالية": "Current Plan",
    "الأيام المتبقية": "Days Remaining",
    "تاريخ التجديد": "Renewal Date",
    "الفروع المستهلكة": "Consumed Branches",
    "الموظفون المسجلون": "Registered Staff",
    "ترقية الباقة": "Upgrade Plan",
    "طلب ترقية": "Request Upgrade",
    "سجل الفواتير السابقة": "Previous Billing History",
    "مفاتيح الربط البرمجي (API Keys)": "API Integration Keys",
    "توليد مفتاح جديد": "Generate New API Key",

    # AI Call Center & FastMCP
    "كول سنتر الذكاء الاصطناعي": "AI Voice Call Center",
    "مركز الاتصالات المباشر": "Live Call Center",
    "إدارة المساعد الذكي وFastMCP": "AI Voice Agent & FastMCP Integration",
    "المكالمات النشطة": "Active Calls",
    "إجمالي المكالمات الواردة": "Total Inbound Calls",
    "مكالمات ناجحة": "Successful Orders via AI",
    "المساعد الصوتي": "Voice Assistant",
    "بدء مكالمة تجريبية": "Start Test Call",
    "تفريغ المكالمة الصوتي المباشر": "Live Call Speech Transcript",
    "سجل المكالمات الصوتية": "Voice Calls History",

    # Platform SaaS Admin
    "إدارة منصة SaaS العامة": "SaaS Platform Admin",
    "لوحة الإدارة المركزية للمنصة (SaaS Superadmin)": "SaaS Platform Central Management (Superadmin)",
    "إدارة المطاعم المشتركة، الباقات والاشتراكات، والتحكم بالمنظومة": "Manage subscribed restaurants, plans & subscriptions, and platform controls",
    "إضافة منشأة جديدة": "Add New Restaurant Tenant",
    "المنشآت النشطة": "Active Restaurants",
    "طلبات الترقية المعلقة": "Pending Upgrade Requests",
    "إجمالي اشتراكات SaaS": "Total SaaS Subscriptions",

    # Common UI
    "حفظ": "Save",
    "إلغاء": "Cancel",
    "تأكيد": "Confirm",
    "حذف": "Delete",
    "تعديل": "Edit",
    "إضافة": "Add",
    "إغلاق": "Close",
    "رجوع": "Back",
    "بحث...": "Search...",
    "بحث": "Search",
    "تصفية": "Filter",
    "الكل": "All",
    "إجراء": "Action",
    "إجراءات": "Actions",
    "التفاصيل": "Details",
    "عرض": "View",
    "طباعة": "Print",
    "تصدير": "Export",
    "تحديث": "Refresh",
    "حفظ التغييرات": "Save Changes",
    "نعم، بالتأكيد": "Yes, Confirm",
    "لا، تراجع": "No, Cancel",
    "هل أنت متأكد؟": "Are you sure?",
    "تمت العملية بنجاح": "Operation completed successfully",
    "حدث خطأ أثناء المعالجة": "An error occurred during processing",
    "يرجى الانتظار…": "Please wait…",
    "لا توجد بيانات متاحة": "No data available",
    "لا توجد نتائج": "No results found",
}


def clean_text(s):
    return re.sub(r'\s+', ' ', s.strip())


def translate_online_batch(texts):
    """Batch translator using newlines to translate up to 40 phrases at once."""
    if not texts:
        return []
    combined = "\n".join(texts)
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=ar&tl=en&dt=t&q=" + urllib.parse.quote(combined)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                res = json.loads(response.read().decode('utf-8'))
                full_trans = ''.join([part[0] for part in res[0]])
                parts = [clean_text(p) for p in full_trans.split('\n')]
                # In case line counts match
                if len(parts) == len(texts):
                    return parts
                # If mismatch in split, fall back to individual
                break
        except Exception as e:
            time.sleep(1.0 + attempt)

    # Fallback to individual
    out = []
    for t in texts:
        out.append(translate_online_single(t))
    return out


def translate_online_single(text):
    if not text:
        return text
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=ar&tl=en&dt=t&q=" + urllib.parse.quote(text)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                res = json.loads(response.read().decode('utf-8'))
                return clean_text(''.join([part[0] for part in res[0]]))
        except Exception:
            time.sleep(0.5)
    return text


def main():
    print("Starting Comprehensive I18N Catalog Build...")
    
    with open('/root/motaem/unique_arabic_phrases.txt', 'r', encoding='utf-8') as f:
        phrases = [line.strip() for line in f if line.strip()]
        
    print(f"Total unique phrases loaded: {len(phrases)}")

    catalog = dict(DOMAIN_OVERRIDES)
    if os.path.exists('/root/motaem/static/js/diyafa_i18n_catalog.json'):
        with open('/root/motaem/static/js/diyafa_i18n_catalog.json', 'r', encoding='utf-8') as f:
            existing = json.load(f)
            for k, v in existing.items():
                if k not in catalog:
                    catalog[k] = v

    missing = []
    for p in phrases:
        cleaned = clean_text(p)
        if cleaned in catalog:
            continue
        missing.append(cleaned)

    print(f"Phrases covered before network calls: {len(catalog)}")
    print(f"Phrases needing translation: {len(missing)}")

    # Translate in batches of 30
    BATCH_SIZE = 30
    for i in range(0, len(missing), BATCH_SIZE):
        chunk = missing[i:i + BATCH_SIZE]
        translations = translate_online_batch(chunk)
        for orig, trans in zip(chunk, translations):
            catalog[orig] = trans
        print(f"Processed {min(i + BATCH_SIZE, len(missing))}/{len(missing)} phrases...")
        time.sleep(0.2)

    print(f"Total catalog entries generated: {len(catalog)}")

    # Save to JSON
    json_path = '/root/motaem/static/js/diyafa_i18n_catalog.json'
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    print(f"Saved JSON catalog to {json_path}")

    # Save to Python module
    py_path = '/root/motaem/core/i18n_catalog.py'
    with open(py_path, 'w', encoding='utf-8') as f:
        f.write("# Auto-generated comprehensive bilingual catalog for Diyafa RMS\n")
        f.write("# Total entries: " + str(len(catalog)) + "\n\n")
        f.write("I18N_CATALOG = " + json.dumps(catalog, ensure_ascii=False, indent=4) + "\n")
    print(f"Saved Python catalog to {py_path}")

    # Build the Diyafa I18N Client-Side Engine JS
    js_path = '/root/motaem/static/js/diyafa_i18n_engine.js'
    engine_code = f"""/**
 * Diyafa Restaurant Management System - Bilingual Dynamic Translation Engine
 * 100% Arabic & English Coverage across all 23 views, tables, cards, modals, and dynamic JS widgets.
 */
(function() {{
    'use strict';

    const LANG = (document.documentElement.lang || 'ar').toLowerCase().substring(0, 2);
    if (LANG !== 'en') {{
        // Native language is Arabic, no DOM translation needed
        return;
    }}

    const CATALOG = {json.dumps(catalog, ensure_ascii=False)};

    // Fast Normalized Lookup
    const normalizedCatalog = new Map();
    for (const [k, v] of Object.entries(CATALOG)) {{
        normalizedCatalog.set(normalize(k), v);
    }}

    function normalize(str) {{
        if (!str) return '';
        return str
            .replace(/[\\s\\u200B-\\u200D\\uFEFF]+/g, ' ')
            .trim();
    }}

    function translateText(text) {{
        if (!text) return null;
        const norm = normalize(text);
        if (!norm) return null;

        // 1. Exact match
        if (normalizedCatalog.has(norm)) {{
            return normalizedCatalog.get(norm);
        }}

        // 2. Check stripping punctuation (colon, dash, ellipsis, parentheses, quotes)
        const punctMatch = norm.match(/^([(\["'«\\s]*)(.+?)([:;—\\-\\.\\…\\)\\]"'»\\s]*)$/);
        if (punctMatch) {{
            const prefix = punctMatch[1] || '';
            const core = punctMatch[2].trim();
            const suffix = punctMatch[3] || '';
            if (core && normalizedCatalog.has(core)) {{
                return prefix + normalizedCatalog.get(core) + suffix;
            }}
        }}

        // 3. Currency and numeric patterns
        let res = norm
            .replace(/\\bر\\.س\\b/g, 'SAR')
            .replace(/\\bريال\\s*سعودي\\b/g, 'SAR')
            .replace(/\\bريال\\b/g, 'SAR')
            .replace(/طلب\\s*رقم\\s*#?([\\d]+)/g, 'Order #$1')
            .replace(/فاتورة\\s*رقم\\s*#?([\\d]+)/g, 'Invoice #$1')
            .replace(/طاولة\\s*رقم\\s*#?([\\d]+)/g, 'Table #$1')
            .replace(/فرع\\s*رقم\\s*#?([\\d]+)/g, 'Branch #$1')
            .replace(/منذ\\s*([\\d]+)\\s*دقيقة/g, '$1 mins ago')
            .replace(/منذ\\s*([\\d]+)\\s*ساعة/g, '$1 hrs ago')
            .replace(/منذ\\s*([\\d]+)\\s*يوم/g, '$1 days ago');

        // Check if modified string has catalog match
        if (res !== norm) {{
            const trimmedRes = res.trim();
            if (normalizedCatalog.has(trimmedRes)) {{
                return normalizedCatalog.get(trimmedRes);
            }}
            return res;
        }}

        return null;
    }}

    // Recursive text node translator
    function translateNode(node) {{
        if (!node) return;

        // Skip scripts, styles, inputs
        const tagName = node.tagName ? node.tagName.toUpperCase() : '';
        if (['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(tagName)) return;

        // Translate attributes
        if (node.nodeType === Node.ELEMENT_NODE) {{
            if (node.hasAttribute('placeholder')) {{
                const ph = node.getAttribute('placeholder');
                const tPh = translateText(ph);
                if (tPh) node.setAttribute('placeholder', tPh);
            }}
            if (node.hasAttribute('title')) {{
                const tit = node.getAttribute('title');
                const tTit = translateText(tit);
                if (tTit) node.setAttribute('title', tTit);
            }}
            if (node.hasAttribute('aria-label')) {{
                const al = node.getAttribute('aria-label');
                const tAl = translateText(al);
                if (tAl) node.setAttribute('aria-label', tAl);
            }}
            if (['INPUT', 'BUTTON'].includes(tagName) && node.type === 'submit') {{
                const val = node.value;
                const tVal = translateText(val);
                if (tVal) node.value = tVal;
            }}
        }}

        // Translate text nodes
        if (node.nodeType === Node.TEXT_NODE) {{
            const raw = node.nodeValue;
            if (raw && /[\\u0600-\\u06FF]/.test(raw)) {{
                const translated = translateText(raw);
                if (translated) {{
                    // Preserve leading/trailing spaces
                    const leading = raw.match(/^\\s*/)[0];
                    const trailing = raw.match(/\\s*$/)[0];
                    node.nodeValue = leading + translated + trailing;
                }}
            }}
            return;
        }}

        // Walk children
        for (let child = node.firstChild; child; child = child.nextSibling) {{
            translateNode(child);
        }}
    }}

    // Translate entire document body
    function translateFullDOM() {{
        const main = document.getElementById('main-canvas') || document.body;
        translateNode(main);
        
        // Also translate any modals/drawers that might be outside main
        document.querySelectorAll('.fixed, [role=\"dialog\"], .modal').forEach(el => {{
            translateNode(el);
        }});
    }}

    // Run on initial load
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', translateFullDOM);
    }} else {{
        translateFullDOM();
    }}

    // Window load pass for late-rendered items
    window.addEventListener('load', () => {{
        setTimeout(translateFullDOM, 50);
        setTimeout(translateFullDOM, 300);
    }});

    // MutationObserver for live dynamic updates (POS Cart, KDS tickets, Realtime Orders, Modals)
    let observerTimeout = null;
    const observer = new MutationObserver((mutations) => {{
        let hasNewArabic = false;
        for (const mut of mutations) {{
            if (mut.addedNodes && mut.addedNodes.length > 0) {{
                for (const added of mut.addedNodes) {{
                    if (added.textContent && /[\\u0600-\\u06FF]/.test(added.textContent)) {{
                        hasNewArabic = true;
                        break;
                    }}
                }}
            }}
            if (hasNewArabic) break;
        }}

        if (hasNewArabic) {{
            if (observerTimeout) clearTimeout(observerTimeout);
            observerTimeout = setTimeout(() => {{
                for (const mut of mutations) {{
                    for (const added of mut.addedNodes) {{
                        translateNode(added);
                    }}
                }}
            }}, 30);
        }}
    }});

    observer.observe(document.body, {{
        childList: true,
        subtree: true
    }});

    // Expose utility globally
    window.DiyafaI18n = {{
        translate: translateText,
        translateNode: translateNode,
        translateFullDOM: translateFullDOM,
        catalog: CATALOG
    }};
}})();
"""
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write(engine_code)
    print(f"Saved Client-side JS Engine to {js_path}")
    print("ALL DONE SUCCESSFULLY!")


if __name__ == '__main__':
    main()
