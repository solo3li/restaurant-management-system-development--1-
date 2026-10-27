#!/usr/bin/env python3
"""
Generate comprehensive 5-language catalog for Motaem Restaurant OS:
- Arabic (ar)
- English (en)
- French (fr)
- Turkish (tr)
- German (de)
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse

# Setup environment to load existing catalog
sys.path.insert(0, '/root/motaem')
from core.i18n_catalog import I18N_CATALOG as EXISTING_CATALOG

DOMAIN_OVERRIDES_MULTI = {
    "ضِيَافَة": {
        "en": "DIYAFA",
        "fr": "DIYAFA",
        "tr": "DIYAFA",
        "de": "DIYAFA"
    },
    "كُـورَا": {
        "en": "KURA",
        "fr": "KURA",
        "tr": "KURA",
        "de": "KURA"
    },
    "كورا": {
        "en": "KURA",
        "fr": "KURA",
        "tr": "KURA",
        "de": "KURA"
    },
    "منظومة كُـورَا لإدارة المطاعم": {
        "en": "KURA Restaurant Management OS",
        "fr": "Système d'exploitation de gestion de restaurant KURA",
        "tr": "KURA Restoran Yönetim İşletim Sistemi",
        "de": "KURA Restaurant-Management-Betriebssystem"
    },
    "نظام إدارة المطاعم": {
        "en": "Restaurant Management System",
        "fr": "Système de gestion de restaurant",
        "tr": "Restoran Yönetim Sistemi",
        "de": "Restaurant-Management-System"
    },
    "نظام التشغيل السحابي للمطاعم والضيافة": {
        "en": "Cloud Operating System for Hospitality & Dining",
        "fr": "Système d'exploitation cloud pour la restauration et l'hôtellerie",
        "tr": "Restoran ve Ağırlama İçin Bulut İşletim Sistemi",
        "de": "Cloud-Betriebssystem für Gastronomie & Restaurants"
    },
    "مركز القيادة والعمليات": {
        "en": "Command & Operations Center",
        "fr": "Centre de commandement et d'opérations",
        "tr": "Komuta ve Operasyon Merkezi",
        "de": "Kommando- und Betriebszentrum"
    },
    "النظام الموحد للإدارة العليا": {
        "en": "Unified Executive Management System",
        "fr": "Système unifié de gestion exécutive",
        "tr": "Birleşik Üst Düzey Yönetim Sistemi",
        "de": "Einheitliches Führungsinformationssystem"
    },
    "الإدارة العامة (كافة الفروع)": {
        "en": "Central HQ (All Branches)",
        "fr": "Siège central (Toutes les succursales)",
        "tr": "Genel Merkez (Tüm Şubeler)",
        "de": "Hauptsitz (Alle Filialen)"
    },
    "التحويل للإدارة العامة (HQ)": {
        "en": "Switch to Central HQ",
        "fr": "Passer au siège central (HQ)",
        "tr": "Genel Merkez Moduna Geç",
        "de": "Zum Hauptsitz (HQ) wechseln"
    },
    "ر.س": {"en": "SAR", "fr": "SAR", "tr": "SAR", "de": "SAR"},
    "ريال": {"en": "SAR", "fr": "SAR", "tr": "SAR", "de": "SAR"},
    "ريال سعودي": {"en": "SAR", "fr": "SAR", "tr": "SAR", "de": "SAR"},
    "دقيقة": {"en": "min", "fr": "min", "tr": "dk", "de": "Min"},
    "دقائق": {"en": "mins", "fr": "mins", "tr": "dk", "de": "Min"},
    "ساعة": {"en": "hr", "fr": "h", "tr": "sa", "de": "Std"},
    "ساعات": {"en": "hrs", "fr": "h", "tr": "sa", "de": "Std"},
    "يوم": {"en": "day", "fr": "jour", "tr": "gün", "de": "Tag"},
    "أيام": {"en": "days", "fr": "jours", "tr": "gün", "de": "Tage"},
    "شهر": {"en": "month", "fr": "mois", "tr": "ay", "de": "Monat"},
    "أشهر": {"en": "months", "fr": "mois", "tr": "ay", "de": "Monate"},
    "سنة": {"en": "year", "fr": "an", "tr": "yıl", "de": "Jahr"},
    "الكاشير — نقطة البيع الذكية": {
        "en": "Smart Cashier & POS Terminal",
        "fr": "Caisse intelligente et terminal PDV",
        "tr": "Akıllı Kasiyer ve POS Terminali",
        "de": "Intelligente Kasse & POS-Terminal"
    },
    "الكاشير": {"en": "Cashier", "fr": "Caisse", "tr": "Kasiyer", "de": "Kasse"},
    "محلي": {"en": "Dine-In", "fr": "Sur place", "tr": "Restoranda", "de": "Im Restaurant"},
    "صالة": {"en": "Dine-In", "fr": "Sur place", "tr": "Restoranda", "de": "Im Restaurant"},
    "سفري": {"en": "Takeaway", "fr": "À emporter", "tr": "Paket Servis", "de": "Zum Mitnehmen"},
    "توصيل": {"en": "Delivery", "fr": "Livraison", "tr": "Teslimat", "de": "Lieferung"},
    "كول سنتر": {"en": "Call Center", "fr": "Centre d'appels", "tr": "Çağrı Merkezi", "de": "Call-Center"},
    "نقداً": {"en": "Cash", "fr": "Espèces", "tr": "Nakit", "de": "Barzahlung"},
    "نقدي": {"en": "Cash", "fr": "Espèces", "tr": "Nakit", "de": "Barzahlung"},
    "شبكة / مدى": {"en": "Mada / Card", "fr": "Carte bancaire", "tr": "Banka Kartı", "de": "Kartenzahlung"},
    "مدى / بطاقة": {"en": "Mada / Card", "fr": "Carte bancaire", "tr": "Banka Kartı", "de": "Kartenzahlung"},
    "بطاقة ائتمانية": {"en": "Credit Card", "fr": "Carte de crédit", "tr": "Kredi Kartı", "de": "Kreditkarte"},
    "المجموع الفرعي": {"en": "Subtotal", "fr": "Sous-total", "tr": "Ara Toplam", "de": "Zwischensumme"},
    "ضريبة القيمة المضافة (15%)": {"en": "VAT (15%)", "fr": "TVA (15%)", "tr": "KDV (%15)", "de": "MwSt. (15%)"},
    "الخصم": {"en": "Discount", "fr": "Remise", "tr": "İndirim", "de": "Rabatt"},
    "الإجمالي النهائي": {"en": "Grand Total", "fr": "Total général", "tr": "Genel Toplam", "de": "Gesamtsumme"},
    "شاشات المطبخ الذكية (KDS)": {
        "en": "Smart Kitchen Display System (KDS)",
        "fr": "Système d'affichage de cuisine intelligent (KDS)",
        "tr": "Akıllı Mutfak Ekran Sistemi (KDS)",
        "de": "Intelligentes Küchenanzeigesystem (KDS)"
    },
    "جديد / قيد الانتظار": {"en": "New / Queued", "fr": "Nouveau / En attente", "tr": "Yeni / Beklemede", "de": "Neu / In Warteschlange"},
    "قيد الطهي": {"en": "Cooking", "fr": "En cuisson", "tr": "Pişiriliyor", "de": "In Zubereitung"},
    "جاهز للاستلام": {"en": "Ready for Pickup", "fr": "Prêt pour le retrait", "tr": "Teslime Hazır", "de": "Abholbereit"},
    "بدء التحضير": {"en": "Start Cooking", "fr": "Commencer la préparation", "tr": "Hazırlamaya Başla", "de": "Zubereitung starten"},
    "جاهز للتقديم": {"en": "Mark as Ready", "fr": "Prêt à servir", "tr": "Hazır Olarak İşaretle", "de": "Als fertig markieren"},
    "المطبخ هادئ الآن — جميع الطلبات منجزة": {
        "en": "Kitchen is Idle — All Orders Fulfilled",
        "fr": "La cuisine est calme — Toutes les commandes sont prêtes",
        "tr": "Mutfak sakin — Tüm siparişler tamamlandı",
        "de": "Die Küche ist ruhig — Alle Bestellungen abgeschlossen"
    },
    "المحطة متصلة وجاهزة • بانتظار الطلبات الفورية": {
        "en": "Station Online & Ready • Awaiting Orders",
        "fr": "Station en ligne et prête • En attente de commandes",
        "tr": "İstasyon Çevrimiçi ve Hazır • Siparişler Bekleniyor",
        "de": "Station online und bereit • Warten auf Bestellungen"
    },
}

def clean_text(s):
    if not s:
        return ''
    return s.strip()

def translate_batch(texts, target_lang):
    if not texts:
        return []
    joined = '\n'.join(texts)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=ar&tl={target_lang}&dt=t&q=" + urllib.parse.quote(joined)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                res = json.loads(response.read().decode('utf-8'))
                full_trans = ''.join([part[0] for part in res[0]])
                parts = [clean_text(p) for p in full_trans.split('\n')]
                if len(parts) == len(texts):
                    return parts
                break
        except Exception:
            time.sleep(1.0 + attempt * 0.5)

    # Fallback to single translations
    results = []
    for t in texts:
        url_single = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=ar&tl={target_lang}&dt=t&q=" + urllib.parse.quote(t)
        req_single = urllib.request.Request(url_single, headers={'User-Agent': 'Mozilla/5.0'})
        val = t
        for a in range(2):
            try:
                with urllib.request.urlopen(req_single, timeout=8) as r:
                    res_s = json.loads(r.read().decode('utf-8'))
                    val = clean_text(''.join([part[0] for part in res_s[0]]))
                    break
            except Exception:
                time.sleep(0.3)
        results.append(val)
    return results

def main():
    print("Starting generation of comprehensive 5-language catalog...")
    keys = list(EXISTING_CATALOG.keys())
    print(f"Total keys to process: {len(keys)}")

    # Initialize catalog dictionary
    full_catalog = {}
    for k in keys:
        en_val = EXISTING_CATALOG[k]
        if hasattr(en_val, 'translations'):
            en_text = en_val.translations.get('en', str(en_val))
        elif isinstance(en_val, dict):
            en_text = en_val.get('en', str(en_val))
        else:
            en_text = str(en_val)

        full_catalog[k] = {
            "ar": k,
            "en": en_text,
            "fr": None,
            "tr": None,
            "de": None
        }

    # Apply domain overrides
    for k, overrides in DOMAIN_OVERRIDES_MULTI.items():
        if k in full_catalog:
            full_catalog[k].update(overrides)
        else:
            full_catalog[k] = {"ar": k, **overrides}

    # Check which languages need translation
    for lang in ['fr', 'tr', 'de']:
        missing_keys = [k for k, v in full_catalog.items() if not v.get(lang)]
        print(f"Language [{lang}]: {len(missing_keys)} phrases needing translation...")
        BATCH_SIZE = 35
        for i in range(0, len(missing_keys), BATCH_SIZE):
            chunk = missing_keys[i:i + BATCH_SIZE]
            trans = translate_batch(chunk, lang)
            for k, t in zip(chunk, trans):
                full_catalog[k][lang] = t
            print(f"[{lang}] Progress: {min(i + BATCH_SIZE, len(missing_keys))}/{len(missing_keys)}")
            time.sleep(0.15)

    print("Translation complete! Verifying all keys have 5 languages...")
    for k, v in full_catalog.items():
        for lang in ['ar', 'en', 'fr', 'tr', 'de']:
            if not v.get(lang):
                v[lang] = v.get('en', k)

    # 1. Write static/js/diyafa_i18n_catalog.json
    json_path = '/root/motaem/static/js/diyafa_i18n_catalog.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(full_catalog, f, ensure_ascii=False, indent=2)
    print(f"✔ Saved JSON catalog to {json_path}")

    # 2. Write core/i18n_catalog.py
    py_path = '/root/motaem/core/i18n_catalog.py'
    with open(py_path, 'w', encoding='utf-8') as f:
        f.write("# Auto-generated comprehensive 5-language catalog for Motaem Restaurant OS\n")
        f.write(f"# Total entries: {len(full_catalog)}\n")
        f.write("# Supported languages: ar (Arabic), en (English), fr (French), tr (Turkish), de (German)\n\n")
        f.write("from django.utils import translation\n\n\n")
        f.write("class TranslatableString(str):\n")
        f.write("    def __new__(cls, en_text, translations=None):\n")
        f.write("        instance = super().__new__(cls, en_text)\n")
        f.write("        instance.translations = translations or {}\n")
        f.write("        return instance\n\n")
        f.write("    def get(self, lang, default=None):\n")
        f.write("        return self.translations.get(lang, default if default is not None else str(self))\n\n")
        f.write("    def for_lang(self, lang):\n")
        f.write("        if not lang or lang == 'ar':\n")
        f.write("            return self.translations.get('ar', str(self))\n")
        f.write("        return self.translations.get(lang, str(self))\n\n")
        f.write("    def __getitem__(self, item):\n")
        f.write("        if isinstance(item, str) and item in self.translations:\n")
        f.write("            return self.translations[item]\n")
        f.write("        return super().__getitem__(item)\n\n\n")
        f.write("class I18nCatalogDict(dict):\n")
        f.write("    def get(self, key, default=None, lang=None):\n")
        f.write("        if key not in self:\n")
        f.write("            return default\n")
        f.write("        val = super().__getitem__(key)\n")
        f.write("        if lang:\n")
        f.write("            if hasattr(val, 'for_lang'):\n")
        f.write("                return val.for_lang(lang)\n")
        f.write("            if isinstance(val, dict):\n")
        f.write("                return val.get(lang, default)\n")
        f.write("        return val\n\n")
        f.write("    def get_for_lang(self, key, lang, default=None):\n")
        f.write("        return self.get(key, default=default, lang=lang)\n\n\n")
        f.write("_RAW_CATALOG = {\n")
        for k, v in full_catalog.items():
            f.write(f"    {json.dumps(k, ensure_ascii=False)}: TranslatableString({json.dumps(v['en'], ensure_ascii=False)}, {json.dumps(v, ensure_ascii=False)}),\n")
        f.write("}\n\n")
        f.write("I18N_CATALOG = I18nCatalogDict(_RAW_CATALOG)\n\n\n")
        f.write("def get_translation(key, lang=None, default=None):\n")
        f.write("    if not key:\n")
        f.write("        return default if default is not None else key\n")
        f.write("    if not lang or lang == 'ar':\n")
        f.write("        return default if default is not None else key\n")
        f.write("    if key in I18N_CATALOG:\n")
        f.write("        entry = I18N_CATALOG[key]\n")
        f.write("        if hasattr(entry, 'for_lang'):\n")
        f.write("            return entry.for_lang(lang)\n")
        f.write("        if isinstance(entry, dict):\n")
        f.write("            return entry.get(lang, entry.get('en', default if default is not None else key))\n")
        f.write("        return entry\n")
        f.write("    return default if default is not None else key\n")

    print(f"✔ Saved Python catalog to {py_path}")

if __name__ == '__main__':
    main()
