import os
import sys
import json
import gzip

BASE_DIR = '/root/motaem'
sys.path.insert(0, BASE_DIR)

from core.i18n_catalog import _RAW_CATALOG

NEW_ENTRIES = {
    # System and Base
    "مالك المنشأة (HQ)": {
        "ar": "مالك المنشأة (HQ)",
        "en": "Restaurant Owner (HQ)",
        "fr": "Propriétaire de l'établissement (HQ)",
        "tr": "İşletme Sahibi (HQ)",
        "de": "Restaurantinhaber (HQ)",
        "es": "Propietario del establecimiento (HQ)"
    },
    "تمت استعادة العرض الافتراضي للشريط الجانبي (288px)": {
        "ar": "تمت استعادة العرض الافتراضي للشريط الجانبي (288px)",
        "en": "Default sidebar width restored (288px)",
        "fr": "Largeur de barre latérale par défaut restaurée (288px)",
        "tr": "Varsayılan kenar çubuğu genişliği geri yüklendi (288px)",
        "de": "Standard-Seitenleistenbreite wiederhergestellt (288px)",
        "es": "Ancho predeterminado de la barra lateral restaurado (288px)"
    },
    "إدارة عامة (HQ)": {
        "ar": "إدارة عامة (HQ)",
        "en": "General Management (HQ)",
        "fr": "Direction générale (HQ)",
        "tr": "Genel Merkez (HQ)",
        "de": "Hauptverwaltung (HQ)",
        "es": "Dirección General (HQ)"
    },

    # Branches
    "الفرع النموذجي": {
        "ar": "الفرع النموذجي",
        "en": "Model Branch",
        "fr": "Succursale modèle",
        "tr": "Model Şube",
        "de": "Modell-Filiale",
        "es": "Sucursal modelo"
    },
    "الفرع الرئيسي — العليا": {
        "ar": "الفرع الرئيسي — العليا",
        "en": "Main Branch — Olaya",
        "fr": "Succursale principale — Olaya",
        "tr": "Ana Şube — Olaya",
        "de": "Hauptfiliale — Olaya",
        "es": "Sucursal principal — Olaya"
    },
    "فرع النرجس": {
        "ar": "فرع النرجس",
        "en": "Al-Narjis Branch",
        "fr": "Succursale Al-Narjis",
        "tr": "Al-Narjis Şubesi",
        "de": "Al-Narjis-Filiale",
        "es": "Sucursal Al-Narjis"
    },
    "فرع الياسمين": {
        "ar": "فرع الياسمين",
        "en": "Al-Yasmin Branch",
        "fr": "Succursale Al-Yasmin",
        "tr": "Al-Yasmin Şubesi",
        "de": "Al-Yasmin-Filiale",
        "es": "Sucursal Al-Yasmin"
    },
    "فرع الروضة — جدة": {
        "ar": "فرع الروضة — جدة",
        "en": "Al-Rawdah Branch — Jeddah",
        "fr": "Succursale Al-Rawdah — Djeddah",
        "tr": "Al-Rawdah Şubesi — Cidde",
        "de": "Al-Rawdah-Filiale — Dschidda",
        "es": "Sucursal Al-Rawdah — Yeda"
    },
    "فرع مدينة الشروق التجريبي": {
        "ar": "فرع مدينة الشروق التجريبي",
        "en": "El Shorouk Pilot Branch",
        "fr": "Succursale pilote d'El Shorouk",
        "tr": "El Shorouk Pilot Şubesi",
        "de": "Pilotfiliale El Shorouk",
        "es": "Sucursal piloto El Shorouk"
    },
    "فرع القاهرة (شامل الضريبة 14%)": {
        "ar": "فرع القاهرة (شامل الضريبة 14%)",
        "en": "Cairo Branch (Tax Incl. 14%)",
        "fr": "Succursale du Caire (TTC 14%)",
        "tr": "Kahire Şubesi (%14 Vergi Dahil)",
        "de": "Kairo-Filiale (Inkl. 14% MwSt.)",
        "es": "Sucursal de El Cairo (IVA incl. 14%)"
    },
    "فرع الإسكندرية (غير شامل الضريبة 10%)": {
        "ar": "فرع الإسكندرية (غير شامل الضريبة 10%)",
        "en": "Alexandria Branch (Tax Excl. 10%)",
        "fr": "Succursale d'Alexandrie (HT 10%)",
        "tr": "İskenderiye Şubesi (%10 Vergi Hariç)",
        "de": "Alexandria-Filiale (Exkl. 10% MwSt.)",
        "es": "Sucursal de Alejandría (IVA no incl. 10%)"
    },
    "فرع النرجس (A)": {
        "ar": "فرع النرجس (A)",
        "en": "Al-Narjis Branch (A)",
        "fr": "Succursale Al-Narjis (A)",
        "tr": "Al-Narjis Şubesi (A)",
        "de": "Al-Narjis-Filiale (A)",
        "es": "Sucursal Al-Narjis (A)"
    },
    "فرع الملقا (B)": {
        "ar": "فرع الملقا (B)",
        "en": "Al-Malqa Branch (B)",
        "fr": "Succursale Al-Malqa (B)",
        "tr": "Al-Malqa Şubesi (B)",
        "de": "Al-Malqa-Filiale (B)",
        "es": "Sucursal Al-Malqa (B)"
    },
    "فرع العليا": {
        "ar": "فرع العليا",
        "en": "Olaya Branch",
        "fr": "Succursale d'Olaya",
        "tr": "Olaya Şubesi",
        "de": "Olaya-Filiale",
        "es": "Sucursal de Olaya"
    },
    "فرع الكورنيش": {
        "ar": "فرع الكورنيش",
        "en": "Corniche Branch",
        "fr": "Succursale de la Corniche",
        "tr": "Kordon Şubesi",
        "de": "Corniche-Filiale",
        "es": "Sucursal Corniche"
    },
    "الفرع الرئيسي E2E": {
        "ar": "الفرع الرئيسي E2E",
        "en": "Main Branch E2E",
        "fr": "Succursale principale E2E",
        "tr": "Ana Şube E2E",
        "de": "Hauptfiliale E2E",
        "es": "Sucursal principal E2E"
    },
    "المقر الرئيسي": {
        "ar": "المقر الرئيسي",
        "en": "Headquarters",
        "fr": "Siège principal",
        "tr": "Genel Merkez",
        "de": "Hauptsitz",
        "es": "Sede central"
    },
    "الفرع الرئيسي — مطعم النصر الجديد": {
        "ar": "الفرع الرئيسي — مطعم النصر الجديد",
        "en": "Main Branch — Al Nasr Restaurant",
        "fr": "Succursale principale — Restaurant Al Nasr",
        "tr": "Ana Şube — Al Nasr Restoranı",
        "de": "Hauptfiliale — Restaurant Al Nasr",
        "es": "Sucursal principal — Restaurante Al Nasr"
    },

    # Cities
    "الرياض": {
        "ar": "الرياض",
        "en": "Riyadh",
        "fr": "Riyad",
        "tr": "Riyad",
        "de": "Riad",
        "es": "Riad"
    },
    "جدة": {
        "ar": "جدة",
        "en": "Jeddah",
        "fr": "Djeddah",
        "tr": "Cidde",
        "de": "Dschidda",
        "es": "Yeda"
    },
    "القاهرة": {
        "ar": "القاهرة",
        "en": "Cairo",
        "fr": "Le Caire",
        "tr": "Kahire",
        "de": "Kairo",
        "es": "El Cairo"
    },
    "الإسكندرية": {
        "ar": "الإسكندرية",
        "en": "Alexandria",
        "fr": "Alexandrie",
        "tr": "İskenderiye",
        "de": "Alexandria",
        "es": "Alejandría"
    },
    "مدينة الشروق": {
        "ar": "مدينة الشروق",
        "en": "El Shorouk City",
        "fr": "Ville d'El Shorouk",
        "tr": "El Shorouk Şehri",
        "de": "Stadt El Shorouk",
        "es": "Ciudad El Shorouk"
    },
    "مكة المكرمة": {
        "ar": "مكة المكرمة",
        "en": "Makkah",
        "fr": "La Mecque",
        "tr": "Mekke",
        "de": "Mekka",
        "es": "La Meca"
    },
    "المدينة المنورة": {
        "ar": "المدينة المنورة",
        "en": "Madinah",
        "fr": "Médine",
        "tr": "Medine",
        "de": "Medina",
        "es": "Medina"
    },
    "الدمام": {
        "ar": "الدمام",
        "en": "Dammam",
        "fr": "Dammam",
        "tr": "Dammam",
        "de": "Dammam",
        "es": "Dammam"
    },
    "الخبر": {
        "ar": "الخبر",
        "en": "Khobar",
        "fr": "Khobar",
        "tr": "Hobart",
        "de": "Chobar",
        "es": "Khobar"
    },

    # Addresses
    "شارع التحلية، حي العليا": {
        "ar": "شارع التحلية، حي العليا",
        "en": "Tahlia St, Olaya District",
        "fr": "Rue Tahlia, quartier Olaya",
        "tr": "Tahlia Cad., Olaya Bölgesi",
        "de": "Tahlia-Str., Olaya-Bezirk",
        "es": "Calle Tahlia, distrito Olaya"
    },
    "طريق أنس بن مالك، حي النرجس": {
        "ar": "طريق أنس بن مالك، حي النرجس",
        "en": "Anas Ibn Malik Rd, Al-Narjis District",
        "fr": "Route Anas Ibn Malik, quartier Al-Narjis",
        "tr": "Enes bin Malik Yolu, Al-Narjis Bölgesi",
        "de": "Anas-Ibn-Malik-Str., Al-Narjis-Bezirk",
        "es": "Camino Anas Ibn Malik, distrito Al-Narjis"
    },
    "شارع عثمان بن عفان، حي الياسمين": {
        "ar": "شارع عثمان بن عفان، حي الياسمين",
        "en": "Othman Ibn Affan St, Al-Yasmin District",
        "fr": "Rue Othman Ibn Affan, quartier Al-Yasmin",
        "tr": "Osman bin Affan Cad., Al-Yasmin Bölgesi",
        "de": "Othman-Ibn-Affan-Str., Al-Yasmin-Bezirk",
        "es": "Calle Othman Ibn Affan, distrito Al-Yasmin"
    },
    "شارع التحلية، حي الروضة": {
        "ar": "شارع التحلية، حي الروضة",
        "en": "Tahlia St, Al-Rawdah District",
        "fr": "Rue Tahlia, quartier Al-Rawdah",
        "tr": "Tahlia Cad., Al-Rawdah Bölgesi",
        "de": "Tahlia-Str., Al-Rawdah-Bezirk",
        "es": "Calle Tahlia, distrito Al-Rawdah"
    },
    "شارع الكيال، حي الروضة": {
        "ar": "شارع الكيال، حي الروضة",
        "en": "Al-Kayyal St, Al-Rawdah District",
        "fr": "Rue Al-Kayyal, quartier Al-Rawdah",
        "tr": "Al-Kayyal Cad., Al-Rawdah Bölgesi",
        "de": "Al-Kayyal-Str., Al-Rawdah-Bezirk",
        "es": "Calle Al-Kayyal, distrito Al-Rawdah"
    },
    "طريق الشباب، بجوار الجامعة البريطانية": {
        "ar": "طريق الشباب، بجوار الجامعة البريطانية",
        "en": "Al-Shabab Rd, next to BUE",
        "fr": "Route Al-Shabab, près de l'Université britannique",
        "tr": "Al-Shabab Yolu, İngiliz Üniversitesi Yanı",
        "de": "Al-Shabab-Str., neben der Britischen Universität",
        "es": "Camino Al-Shabab, junto a la Universidad Británica"
    },
    "الرياض، المملكة العربية السعودية": {
        "ar": "الرياض، المملكة العربية السعودية",
        "en": "Riyadh, Saudi Arabia",
        "fr": "Riyad, Arabie saoudite",
        "tr": "Riyad, Suudi Arabistan",
        "de": "Riad, Saudi-Arabien",
        "es": "Riad, Arabia Saudita"
    },

    # Job Roles
    "كاشير الصالة": {
        "ar": "كاشير الصالة",
        "en": "Dining Cashier",
        "fr": "Caissier de salle",
        "tr": "Salon Kasiyeri",
        "de": "Saal-Kassierer",
        "es": "Cajero de sala"
    },
    "كاشير صالة": {
        "ar": "كاشير صالة",
        "en": "Dining Cashier",
        "fr": "Caissier de salle",
        "tr": "Salon Kasiyeri",
        "de": "Saal-Kassierer",
        "es": "Cajero de sala"
    },
    "كاشير رئيسي": {
        "ar": "كاشير رئيسي",
        "en": "Head Cashier",
        "fr": "Caissier principal",
        "tr": "Baş Kasiyer",
        "de": "Chefkassierer",
        "es": "Cajero principal"
    },
    "طاهٍ رئيسي / مطبخ": {
        "ar": "طاهٍ رئيسي / مطبخ",
        "en": "Head Chef / Kitchen",
        "fr": "Chef cuisinier / Cuisine",
        "tr": "Baş Aşçı / Mutfak",
        "de": "Küchenchef / Küche",
        "es": "Jefe de cocina"
    },
    "شيف المطبخ": {
        "ar": "شيف المطبخ",
        "en": "Kitchen Chef",
        "fr": "Chef de cuisine",
        "tr": "Mutfak Şefi",
        "de": "Küchenchef",
        "es": "Chef de cocina"
    },
    "سائق توصيل": {
        "ar": "سائق توصيل",
        "en": "Delivery Driver",
        "fr": "Chauffeur-livreur",
        "tr": "Teslimat Kuryesi",
        "de": "Lieferfahrer",
        "es": "Repartidor"
    },
    "موظف كول سنتر": {
        "ar": "موظف كول سنتر",
        "en": "Call Center Agent",
        "fr": "Agent de centre d'appels",
        "tr": "Çağrı Merkezi Temsilcisi",
        "de": "Call-Center-Mitarbeiter",
        "es": "Agente de call center"
    },
    "مدير فرع": {
        "ar": "مدير فرع",
        "en": "Branch Manager",
        "fr": "Directeur de succursale",
        "tr": "Şube Müdürü",
        "de": "Filialleiter",
        "es": "Gerente de sucursal"
    },
    "مدير عام / إدارة عليا": {
        "ar": "مدير عام / إدارة عليا",
        "en": "General Manager / Senior Management",
        "fr": "Directeur général / Haute direction",
        "tr": "Genel Müdür / Üst Yönetim",
        "de": "Geschäftsführer / Leitung",
        "es": "Director General / Alta Dirección"
    },
    "مدير عام تجريبي": {
        "ar": "مدير عام تجريبي",
        "en": "Pilot General Manager",
        "fr": "Directeur général pilote",
        "tr": "Pilot Genel Müdür",
        "de": "Pilot-Geschäftsführer",
        "es": "Director general piloto"
    },
    "كاشير فرع تجريبي": {
        "ar": "كاشير فرع تجريبي",
        "en": "Pilot Branch Cashier",
        "fr": "Caissier succursale pilote",
        "tr": "Pilot Şube Kasiyeri",
        "de": "Pilot-Filialkassierer",
        "es": "Cajero de sucursal piloto"
    },
    "طاهٍ فرع تجريبي": {
        "ar": "طاهٍ فرع تجريبي",
        "en": "Pilot Branch Cook",
        "fr": "Cuisinier succursale pilote",
        "tr": "Pilot Şube Aşçısı",
        "de": "Pilot-Filialkoch",
        "es": "Cocinero de sucursal piloto"
    },
    "سائق فرع تجريبي": {
        "ar": "سائق فرع تجريبي",
        "en": "Pilot Branch Driver",
        "fr": "Chauffeur succursale pilote",
        "tr": "Pilot Şube Şoförü",
        "de": "Pilot-Filialfahrer",
        "es": "Conductor de sucursal piloto"
    },
    "مدير فرع محلي تجريبي": {
        "ar": "مدير فرع محلي تجريبي",
        "en": "Pilot Local Branch Manager",
        "fr": "Directeur de succursale locale pilote",
        "tr": "Pilot Yerel Şube Müdürü",
        "de": "Pilot-Lokaler Filialleiter",
        "es": "Gerente local piloto"
    },
    "مدير عام HQ تجريبي": {
        "ar": "مدير عام HQ تجريبي",
        "en": "Pilot HQ General Manager",
        "fr": "Directeur général HQ pilote",
        "tr": "Pilot Genel Merkez Müdürü",
        "de": "Pilot-HQ-Geschäftsführer",
        "es": "Director general HQ piloto"
    },
    "كاشير تدقيق": {
        "ar": "كاشير تدقيق",
        "en": "Audit Cashier",
        "fr": "Caissier d'audit",
        "tr": "Denetim Kasiyeri",
        "de": "Prüfkassierer",
        "es": "Cajero auditor"
    },

    # Inventory Items & Units
    "مادة تجريبية": {
        "ar": "مادة تجريبية",
        "en": "Test Item",
        "fr": "Article test",
        "tr": "Test Maddesi",
        "de": "Test-Artikel",
        "es": "Artículo de prueba"
    },
    "أرز بسمتي": {
        "ar": "أرز بسمتي",
        "en": "Basmati Rice",
        "fr": "Riz Basmati",
        "tr": "Basmati Pirinç",
        "de": "Basmati-Reis",
        "es": "Arroz basmati"
    },
    "دجاج طازج": {
        "ar": "دجاج طازج",
        "en": "Fresh Chicken",
        "fr": "Poulet frais",
        "tr": "Taze Tavuk",
        "de": "Frisches Hähnchen",
        "es": "Pollo fresco"
    },
    "لحم غنم": {
        "ar": "لحم غنم",
        "en": "Lamb Meat",
        "fr": "Viande d'agneau",
        "tr": "Kuzu Eti",
        "de": "Lammfleisch",
        "es": "Carne de cordero"
    },
    "طماطم": {
        "ar": "طماطم",
        "en": "Tomatoes",
        "fr": "Tomates",
        "tr": "Domates",
        "de": "Tomaten",
        "es": "Tomates"
    },
    "بصل": {
        "ar": "بصل",
        "en": "Onions",
        "fr": "Oignons",
        "tr": "Soğan",
        "de": "Zwiebeln",
        "es": "Cebollas"
    },
    "زيت طبخ": {
        "ar": "زيت طبخ",
        "en": "Cooking Oil",
        "fr": "Huile de cuisson",
        "tr": "Sıvı Yağ",
        "de": "Speiseöl",
        "es": "Aceite de cocina"
    },
    "بهارات مشكلة": {
        "ar": "بهارات مشكلة",
        "en": "Mixed Spices",
        "fr": "Épices mélangées",
        "tr": "Karışık Baharat",
        "de": "Gewürzmischung",
        "es": "Especias mixtas"
    },
    "خبز صاج": {
        "ar": "خبز صاج",
        "en": "Saj Bread",
        "fr": "Pain Saj",
        "tr": "Saç Ekmeği",
        "de": "Saj-Brot",
        "es": "Pan saj"
    },
    "مشروبات غازية": {
        "ar": "مشروبات غازية",
        "en": "Soft Drinks",
        "fr": "Boissons gazeuses",
        "tr": "Gazlı İçecekler",
        "de": "Erfrischungsgetränke",
        "es": "Refrescos"
    },
    "سكر": {
        "ar": "سكر",
        "en": "Sugar",
        "fr": "Sucre",
        "tr": "Şeker",
        "de": "Zucker",
        "es": "Azúcar"
    },
    "لحم أنجوس مفروم": {
        "ar": "لحم أنجوس مفروم",
        "en": "Minced Angus Beef",
        "fr": "Bœuf Angus haché",
        "tr": "Kıyılmış Angus Eti",
        "de": "Gehacktes Angus-Rindfleisch",
        "es": "Carne picada de angus"
    },
    "خبز بريوش طازج": {
        "ar": "خبز بريوش طازج",
        "en": "Fresh Brioche Buns",
        "fr": "Pains briochés frais",
        "tr": "Taze Brioche Ekmeği",
        "de": "Frische Brioche-Brötchen",
        "es": "Pan brioche fresco"
    },
    "جبن شيدر طبيعي": {
        "ar": "جبن شيدر طبيعي",
        "en": "Natural Cheddar Cheese",
        "fr": "Fromage cheddar naturel",
        "tr": "Doğal Çedar Peyniri",
        "de": "Natürlicher Cheddar-Käse",
        "es": "Queso cheddar natural"
    },
    "صوص البرجر الخاص": {
        "ar": "صوص البرجر الخاص",
        "en": "Special Burger Sauce",
        "fr": "Sauce burger spéciale",
        "tr": "Özel Burger Sosu",
        "de": "Spezielle Burger-Sauce",
        "es": "Salsa especial para hamburguesas"
    },
    "كجم": {
        "ar": "كجم",
        "en": "kg",
        "fr": "kg",
        "tr": "kg",
        "de": "kg",
        "es": "kg"
    },
    "لتر": {
        "ar": "لتر",
        "en": "L",
        "fr": "L",
        "tr": "L",
        "de": "L",
        "es": "L"
    },
    "علبة": {
        "ar": "علبة",
        "en": "Can",
        "fr": "Boîte",
        "tr": "Kutu",
        "de": "Dose",
        "es": "Lata"
    },
    "قطعة": {
        "ar": "قطعة",
        "en": "Piece",
        "fr": "Pièce",
        "tr": "Parça",
        "de": "Stück",
        "es": "Pieza"
    },
    "كرتون": {
        "ar": "كرتون",
        "en": "Carton",
        "fr": "Carton",
        "tr": "Koli",
        "de": "Karton",
        "es": "Cartón"
    },
    "حبة": {
        "ar": "حبة",
        "en": "Piece",
        "fr": "Pièce",
        "tr": "Adet",
        "de": "Stück",
        "es": "Unidad"
    },
    "المادة الغذائية": {
        "ar": "المادة الغذائية",
        "en": "Food Item",
        "fr": "Ingrédient alimentaire",
        "tr": "Gıda Maddesi",
        "de": "Lebensmittel",
        "es": "Alimento"
    },
    "حد الأمان": {
        "ar": "حد الأمان",
        "en": "Par Level",
        "fr": "Seuil de sécurité",
        "tr": "Güvenlik Limiti",
        "de": "Mindestbestand",
        "es": "Nivel de seguridad"
    },

    # Dishes & Categories
    "شاي كرك تجريبي": {
        "ar": "شاي كرك تجريبي",
        "en": "Pilot Karak Tea",
        "fr": "Thé Karak pilote",
        "tr": "Pilot Karak Çayı",
        "de": "Pilot Karak-Tee",
        "es": "Té Karak piloto"
    },
    "أطباق عامة": {
        "ar": "أطباق عامة",
        "en": "General Dishes",
        "fr": "Plats généraux",
        "tr": "Genel Yemekler",
        "de": "Allgemeine Gerichte",
        "es": "Platos generales"
    },

    # Support Tickets
    "دعم فني ونظام": {
        "ar": "دعم فني ونظام",
        "en": "Technical & System Support",
        "fr": "Support technique et système",
        "tr": "Teknik ve Sistem Desteği",
        "de": "Technischer & System-Support",
        "es": "Soporte técnico y de sistemas"
    },
    "فواتير واشتراكات": {
        "ar": "فواتير واشتراكات",
        "en": "Billing & Subscriptions",
        "fr": "Facturation et abonnements",
        "tr": "Faturalandırma ve Abonelikler",
        "de": "Abrechnung & Abonnements",
        "es": "Facturación y suscripciones"
    },
    "أجهزة ونقاط بيع": {
        "ar": "أجهزة ونقاط بيع",
        "en": "Hardware & POS",
        "fr": "Matériel et PDV",
        "tr": "Donanım ve POS",
        "de": "Hardware & POS",
        "es": "Equipamiento y TPV"
    },
    "اقتراحات وميزات جديدة": {
        "ar": "اقتراحات وميزات جديدة",
        "en": "Feature Suggestions",
        "fr": "Suggestions de fonctionnalités",
        "tr": "Öneriler ve Yeni Özellikler",
        "de": "Funktionsvorschläge",
        "es": "Sugerencias y nuevas funciones"
    },
    "منخفضة": {
        "ar": "منخفضة",
        "en": "Low",
        "fr": "Faible",
        "tr": "Düşük",
        "de": "Niedrig",
        "es": "Baja"
    },
    "متوسطة": {
        "ar": "متوسطة",
        "en": "Medium",
        "fr": "Moyenne",
        "tr": "Orta",
        "de": "Mittel",
        "es": "Media"
    },
    "عالية": {
        "ar": "عالية",
        "en": "High",
        "fr": "Élevée",
        "tr": "Yüksek",
        "de": "Hoch",
        "es": "Alta"
    },
    "حرجة وعاجلة": {
        "ar": "حرجة وعاجلة",
        "en": "Urgent & Critical",
        "fr": "Critique et urgent",
        "tr": "Acil ve Kritik",
        "de": "Dringend & Kritisch",
        "es": "Urgente y crítica"
    },
    "مفتوحة": {
        "ar": "مفتوحة",
        "en": "Open",
        "fr": "Ouvert",
        "tr": "Açık",
        "de": "Offen",
        "es": "Abierta"
    },
    "تم الحل": {
        "ar": "تم الحل",
        "en": "Resolved",
        "fr": "Résolu",
        "tr": "Çözüldü",
        "de": "Gelöst",
        "es": "Resuelta"
    },
    "مغلقة": {
        "ar": "مغلقة",
        "en": "Closed",
        "fr": "Fermé",
        "tr": "Kapalı",
        "de": "Geschlossen",
        "es": "Cerrada"
    },
    "مغلقة / أرشيف": {
        "ar": "مغلقة / أرشيف",
        "en": "Closed / Archive",
        "fr": "Fermé / Archive",
        "tr": "Kapalı / Arşiv",
        "de": "Geschlossen / Archiv",
        "es": "Cerrada / Archivo"
    },
    "جميع التصنيفات": {
        "ar": "جميع التصنيفات",
        "en": "All Categories",
        "fr": "Toutes les catégories",
        "tr": "Tüm Kategoriler",
        "de": "Alle Kategorien",
        "es": "Todas las categorías"
    },
    "بحث برقم التذكرة أو الموضوع...": {
        "ar": "بحث برقم التذكرة أو الموضوع...",
        "en": "Search by ticket # or subject...",
        "fr": "Rechercher par n° de ticket ou sujet...",
        "tr": "Bilet no veya konuya göre ara...",
        "de": "Nach Ticket-Nr. oder Betreff suchen...",
        "es": "Buscar por n° de ticket o asunto..."
    },
    "فتح تذكرة دعم فني جديدة": {
        "ar": "فتح تذكرة دعم فني جديدة",
        "en": "Open New Support Ticket",
        "fr": "Ouvrir un nouveau ticket de support",
        "tr": "Yeni Destek Talebi Aç",
        "de": "Neues Support-Ticket erstellen",
        "es": "Abrir nuevo ticket de soporte"
    },
    "أرسل تفاصيل المشكلة وسيقوم فريق الدعم الفني بمتابعتها": {
        "ar": "أرسل تفاصيل المشكلة وسيقوم فريق الدعم الفني بمتابعتها",
        "en": "Send issue details and the support team will follow up",
        "fr": "Envoyez les détails du problème et l'équipe de support assurera le suivi",
        "tr": "Sorun detaylarını gönderin, destek ekibimiz ilgilensin",
        "de": "Senden Sie die Problemdetails, unser Support-Team kümmert sich darum",
        "es": "Envíe los detalles del problema y el equipo de soporte le dará seguimiento"
    },
    "عنوان التذكرة / المشكلة": {
        "ar": "عنوان التذكرة / المشكلة",
        "en": "Ticket Title / Issue",
        "fr": "Titre du ticket / Problème",
        "tr": "Talep Başlığı / Sorun",
        "de": "Ticket-Titel / Problem",
        "es": "Título del ticket / Problema"
    },
    "تفاصيل المشكلة والخطوات": {
        "ar": "تفاصيل المشكلة والخطوات",
        "en": "Issue Details & Steps",
        "fr": "Détails du problème et étapes",
        "tr": "Sorun Detayları ve Adımlar",
        "de": "Problemdetails & Schritte",
        "es": "Detalles del problema y pasos"
    },
    "إرسال التذكرة": {
        "ar": "إرسال التذكرة",
        "en": "Submit Ticket",
        "fr": "Envoyer le ticket",
        "tr": "Talebi Gönder",
        "de": "Ticket absenden",
        "es": "Enviar ticket"
    },

    # Call Center
    "جوال العميل": {
        "ar": "جوال العميل",
        "en": "Customer Mobile",
        "fr": "Mobile client",
        "tr": "Müşteri Cep Telefonu",
        "de": "Kunden-Handy",
        "es": "Móvil del cliente"
    },
    "الاسم الكامل": {
        "ar": "الاسم الكامل",
        "en": "Full Name",
        "fr": "Nom complet",
        "tr": "Tam Adı",
        "de": "Vollständiger Name",
        "es": "Nombre completo"
    },
    "اسم التأكيد": {
        "ar": "اسم التأكيد",
        "en": "Confirmation Name",
        "fr": "Nom de confirmation",
        "tr": "Onay Adı",
        "de": "Bestätigungsname",
        "es": "Nombre de confirmación"
    },
    "رقم التأكيد": {
        "ar": "رقم التأكيد",
        "en": "Confirmation Number",
        "fr": "Numéro de confirmation",
        "tr": "Onay Numarası",
        "de": "Bestätigungsnummer",
        "es": "Número de confirmación"
    },
    "الحي، اسم الشارع، رقم العمارة أو الشقة...": {
        "ar": "الحي، اسم الشارع، رقم العمارة أو الشقة...",
        "en": "District, Street, Bldg/Apt #...",
        "fr": "Quartier, rue, n° immeuble/appartement...",
        "tr": "Mahalle, sokak, bina/daire no...",
        "de": "Stadtteil, Straße, Gebäude-/Wohnungs-Nr...",
        "es": "Barrio, calle, n° de edificio o piso..."
    },
    "تم إصدار وتمرير الطلب بنجاح": {
        "ar": "تم إصدار وتمرير الطلب بنجاح",
        "en": "Order successfully issued and dispatched",
        "fr": "Commande émise et transmise avec succès",
        "tr": "Sipariş başarıyla oluşturuldu ve iletildi",
        "de": "Bestellung erfolgreich erstellt und weitergeleitet",
        "es": "Pedido emitido y enviado con éxito"
    },
    "طلب توصيل": {
        "ar": "طلب توصيل",
        "en": "Delivery Order",
        "fr": "Commande de livraison",
        "tr": "Teslimat Siparişi",
        "de": "Lieferbestellung",
        "es": "Pedido a domicilio"
    },
    "تسجيل مكالمة / فاتورة جديدة": {
        "ar": "تسجيل مكالمة / فاتورة جديدة",
        "en": "Record Call / New Invoice",
        "fr": "Enregistrer un appel / Nouvelle facture",
        "tr": "Çağrı Kaydet / Yeni Fatura",
        "de": "Anruf aufzeichnen / Neue Rechnung",
        "es": "Registrar llamada / Nueva factura"
    },
    "ملاحظات المطبخ والتحضير (اختياري)...": {
        "ar": "ملاحظات المطبخ والتحضير (اختياري)...",
        "en": "Kitchen & prep notes (optional)...",
        "fr": "Notes cuisine et préparation (facultatif)...",
        "tr": "Mutfak ve hazırlık notları (isteğe bağlı)...",
        "de": "Küchen- und Zubereitungsnotizen (optional)...",
        "es": "Notas de cocina y preparación (opcional)..."
    },
    "-- اختر المنطقة لتوجيه الفرع وحساب التوصيل --": {
        "ar": "-- اختر المنطقة لتوجيه الفرع وحساب التوصيل --",
        "en": "-- Select area to route branch and calculate delivery --",
        "fr": "-- Sélectionnez la zone pour acheminer la succursale et calculer la livraison --",
        "tr": "-- Şube yönlendirmesi ve teslimat hesaplaması için bölge seçin --",
        "de": "-- Bereich auswählen für Filialweiterleitung & Lieferberechnung --",
        "es": "-- Seleccione la zona para dirigir a la sucursal y calcular entrega --"
    },

    # Delivery
    "— إسناد جماعي لسائق —": {
        "ar": "— إسناد جماعي لسائق —",
        "en": "— Bulk Assign to Driver —",
        "fr": "— Attribution groupée à un chauffeur —",
        "tr": "— Kuryeye Toplu Atama —",
        "de": "— Sammelzuweisung an Fahrer —",
        "es": "— Asignación masiva a repartidor —"
    },
    "نقل للمرحلة التالية": {
        "ar": "نقل للمرحلة التالية",
        "en": "Move to Next Stage",
        "fr": "Passer à l'étape suivante",
        "tr": "Sonraki Aşamaya Geç",
        "de": "Zur nächsten Stufe weiterleiten",
        "es": "Pasar a la siguiente etapa"
    },
    "لا توجد طلبات تطابق معايير البحث": {
        "ar": "لا توجد طلبات تطابق معايير البحث",
        "en": "No orders match search criteria",
        "fr": "Aucune commande ne correspond aux critères de recherche",
        "tr": "Arama kriterlerine uygun sipariş bulunamadı",
        "de": "Keine Bestellungen entsprechen den Suchkriterien",
        "es": "No hay pedidos que coincidan con los criterios de búsqueda"
    },
    "جرب البحث بكلمة أخرى أو برقم الطلب": {
        "ar": "جرب البحث بكلمة أخرى أو برقم الطلب",
        "en": "Try searching with another keyword or order #",
        "fr": "Essayez de rechercher avec un autre mot ou numéro de commande",
        "tr": "Farklı bir anahtar kelime veya sipariş numarasıyla aramayı deneyin",
        "de": "Versuchen Sie die Suche mit einem anderen Begriff oder einer Auftragsnummer",
        "es": "Intente buscar con otra palabra clave o n° de pedido"
    },
    "لا توجد طلبات توصيل جديدة حالياً": {
        "ar": "لا توجد طلبات توصيل جديدة حالياً",
        "en": "No new delivery orders currently",
        "fr": "Aucune nouvelle commande de livraison pour le moment",
        "tr": "Şu anda yeni teslimat siparişi yok",
        "de": "Derzeit keine neuen Lieferaufträge",
        "es": "No hay nuevos pedidos de entrega en este momento"
    },
    "الطلبات المسجلة من الكاشير أو مركز الاتصال بالذكاء الاصطناعي ستصل هنا تلقائياً": {
        "ar": "الطلبات المسجلة من الكاشير أو مركز الاتصال بالذكاء الاصطناعي ستصل هنا تلقائياً",
        "en": "Orders placed from cashier or AI call center will arrive here automatically",
        "fr": "Les commandes passées depuis la caisse ou le centre d'appels IA arriveront ici automatiquement",
        "tr": "Kasiyerden veya yapay zeka çağrı merkezinden verilen siparişler otomatik olarak buraya ulaşacaktır",
        "de": "Von der Kasse oder dem KI-Callcenter aufgegebene Bestellungen treffen hier automatisch ein",
        "es": "Los pedidos realizados desde la caja o el call center de IA llegarán aquí automáticamente"
    },
    "لا توجد طلبات قيد التحضير في المطبخ": {
        "ar": "لا توجد طلبات قيد التحضير في المطبخ",
        "en": "No orders currently being prepared in the kitchen",
        "fr": "Aucune commande en cours de préparation en cuisine",
        "tr": "Şu anda mutfakta hazırlanan sipariş yok",
        "de": "Derzeit werden keine Bestellungen in der Küche zubereitet",
        "es": "No hay pedidos preparándose en la cocina actualmente"
    },
    "لا توجد طلبات جاهزة للتسليم للسائقين": {
        "ar": "لا توجد طلبات جاهزة للتسليم للسائقين",
        "en": "No orders ready for driver pickup",
        "fr": "Aucune commande prête pour les livreurs",
        "tr": "Kuryeler için hazır sipariş yok",
        "de": "Keine Bestellungen zur Abholung durch Fahrer bereit",
        "es": "No hay pedidos listos para entrega a repartidores"
    },
    "لا توجد طلبات في الطريق للتوصيل": {
        "ar": "لا توجد طلبات في الطريق للتوصيل",
        "en": "No orders out for delivery",
        "fr": "Aucune commande en cours de livraison",
        "tr": "Yolda olan sipariş yok",
        "de": "Keine Bestellungen unterwegs",
        "es": "No hay pedidos en camino para entrega"
    },
    "لا توجد طلبات مسلّمة اليوم": {
        "ar": "لا توجد طلبات مسلّمة اليوم",
        "en": "No orders delivered today",
        "fr": "Aucune commande livrée aujourd'hui",
        "tr": "Bugün teslim edilen sipariş yok",
        "de": "Heute keine Bestellungen zugestellt",
        "es": "No hay pedidos entregados hoy"
    },

    # Currencies
    "جنيه مصري": {
        "ar": "جنيه مصري",
        "en": "Egyptian Pound",
        "fr": "Livre égyptienne",
        "tr": "Mısır Lirası",
        "de": "Ägyptisches Pfund",
        "es": "Libra egipcia"
    },
    "درهم إماراتي": {
        "ar": "درهم إماراتي",
        "en": "UAE Dirham",
        "fr": "Dirham des Émirats",
        "tr": "BAE Dirhemi",
        "de": "VAE-Dirham",
        "es": "Dírham de los EAU"
    },
    "دينار كويتي": {
        "ar": "دينار كويتي",
        "en": "Kuwaiti Dinar",
        "fr": "Dinar koweïtien",
        "tr": "Kuveyt Dinarı",
        "de": "Kuwait-Dinar",
        "es": "Dinar kuwaití"
    },
    "ريال قطري": {
        "ar": "ريال قطري",
        "en": "Qatari Riyal",
        "fr": "Riyal qatarien",
        "tr": "Katar Riyali",
        "de": "Katar-Riyal",
        "es": "Riyal catarí"
    },
    "دينار بحريني": {
        "ar": "دينار بحريني",
        "en": "Bahraini Dinar",
        "fr": "Dinar bahreïni",
        "tr": "Bahreyn Dinarı",
        "de": "Bahrain-Dinar",
        "es": "Dinar bareiní"
    },
    "ريال عماني": {
        "ar": "ريال عماني",
        "en": "Omani Rial",
        "fr": "Rial omanais",
        "tr": "Umman Riyali",
        "de": "Omanischer Rial",
        "es": "Rial omaní"
    },
    "دينار أردني": {
        "ar": "دينار أردني",
        "en": "Jordanian Dinar",
        "fr": "Dinar jordanien",
        "tr": "Ürdün Dinarı",
        "de": "Jordanischer Dinar",
        "es": "Dinar jordano"
    },
    "دينار عراقي": {
        "ar": "دينار عراقي",
        "en": "Iraqi Dinar",
        "fr": "Dinar irakien",
        "tr": "Irak Dinarı",
        "de": "Irakischer Dinar",
        "es": "Dinar iraquí"
    },
    "ليرة لبنانية": {
        "ar": "ليرة لبنانية",
        "en": "Lebanese Pound",
        "fr": "Livre libanaise",
        "tr": "Lübnan Lirası",
        "de": "Libanesisches Pfund",
        "es": "Libra libanesa"
    },
    "ليرة سورية": {
        "ar": "ليرة سورية",
        "en": "Syrian Pound",
        "fr": "Livre syrienne",
        "tr": "Suriye Lirası",
        "de": "Syrisches Pfund",
        "es": "Libra siria"
    },
    "دينار ليبي": {
        "ar": "دينار ليبي",
        "en": "Libyan Dinar",
        "fr": "Dinar libyen",
        "tr": "Libya Dinarı",
        "de": "Libyscher Dinar",
        "es": "Dinar libio"
    },
    "دينار تونسي": {
        "ar": "دينار تونسي",
        "en": "Tunisian Dinar",
        "fr": "Dinar tunisien",
        "tr": "Tunus Dinarı",
        "de": "Tunesischer Dinar",
        "es": "Dinar tunecino"
    },
    "دينار جزائري": {
        "ar": "دينار جزائري",
        "en": "Algerian Dinar",
        "fr": "Dinar algérien",
        "tr": "Cezayir Dinarı",
        "de": "Algerischer Dinar",
        "es": "Dinar argelino"
    },
    "درهم مغربي": {
        "ar": "درهم مغربي",
        "en": "Moroccan Dirham",
        "fr": "Dirham marocain",
        "tr": "Fas Dirhemi",
        "de": "Marokkanischer Dirham",
        "es": "Dírham marroquí"
    },
    "جنيه سوداني": {
        "ar": "جنيه سوداني",
        "en": "Sudanese Pound",
        "fr": "Livre soudanaise",
        "tr": "Sudan Sterlini",
        "de": "Sudanesisches Pfund",
        "es": "Libra sudanesa"
    },
    "ريال يمني": {
        "ar": "ريال يمني",
        "en": "Yemeni Rial",
        "fr": "Rial yéménite",
        "tr": "Yemen Riyali",
        "de": "Jemen-Rial",
        "es": "Rial yemení"
    },
    "دولار أمريكي": {
        "ar": "دولار أمريكي",
        "en": "US Dollar",
        "fr": "Dollar américain",
        "tr": "ABD Doları",
        "de": "US-Dollar",
        "es": "Dólar estadounidense"
    },
    "يورو": {
        "ar": "يورو",
        "en": "Euro",
        "fr": "Euro",
        "tr": "Euro",
        "de": "Euro",
        "es": "Euro"
    },
    "جنيه إسترليني": {
        "ar": "جنيه إسترليني",
        "en": "British Pound",
        "fr": "Livre sterling",
        "tr": "İngiliz Sterlini",
        "de": "Britisches Pfund",
        "es": "Libra esterlina"
    },
    "ليرة تركية": {
        "ar": "ليرة تركية",
        "en": "Turkish Lira",
        "fr": "Livre turque",
        "tr": "Türk Lirası",
        "de": "Türkische Lira",
        "es": "Lira turca"
    },

    # Orders & Financials
    "محلي": {
        "ar": "محلي",
        "en": "Dine-In",
        "fr": "Sur place",
        "tr": "Restoranda",
        "de": "Im Restaurant",
        "es": "En sala"
    },
    "سفري": {
        "ar": "سفري",
        "en": "Takeaway",
        "fr": "À emporter",
        "tr": "Paket Servis",
        "de": "Zum Mitnehmen",
        "es": "Para llevar"
    },
    "توصيل": {
        "ar": "توصيل",
        "en": "Delivery",
        "fr": "Livraison",
        "tr": "Teslimat",
        "de": "Lieferung",
        "es": "A domicilio"
    },
    "نقداً": {
        "ar": "نقداً",
        "en": "Cash",
        "fr": "Espèces",
        "tr": "Nakit",
        "de": "Bar",
        "es": "Efectivo"
    },
    "نقداً ✓": {
        "ar": "نقداً ✓",
        "en": "Cash ✓",
        "fr": "Espèces ✓",
        "tr": "Nakit ✓",
        "de": "Bar ✓",
        "es": "Efectivo ✓"
    },
    "بطاقة": {
        "ar": "بطاقة",
        "en": "Card",
        "fr": "Carte",
        "tr": "Kart",
        "de": "Karte",
        "es": "Tarjeta"
    },
    "محفظة رقمية": {
        "ar": "محفظة رقمية",
        "en": "Digital Wallet",
        "fr": "Portefeuille numérique",
        "tr": "Dijital Cüzdan",
        "de": "Digitale Brieftasche",
        "es": "Billetera digital"
    },
    "جديد": {
        "ar": "جديد",
        "en": "New",
        "fr": "Nouveau",
        "tr": "Yeni",
        "de": "Neu",
        "es": "Nuevo"
    },
    "قيد التحضير": {
        "ar": "قيد التحضير",
        "en": "Preparing",
        "fr": "En préparation",
        "tr": "Hazırlanıyor",
        "de": "In Zubereitung",
        "es": "En preparación"
    },
    "جاهز للتسليم": {
        "ar": "جاهز للتسليم",
        "en": "Ready for Delivery",
        "fr": "Prêt pour livraison",
        "tr": "Teslimata Hazır",
        "de": "Bereit zur Lieferung",
        "es": "Listo para entrega"
    },
    "في الطريق": {
        "ar": "في الطريق",
        "en": "On the Way",
        "fr": "En route",
        "tr": "Yolda",
        "de": "Unterwegs",
        "es": "En camino"
    },
    "تم التسليم": {
        "ar": "تم التسليم",
        "en": "Delivered",
        "fr": "Livré",
        "tr": "Teslim Edildi",
        "de": "Zugestellt",
        "es": "Entregado"
    },
    "ملغي": {
        "ar": "ملغي",
        "en": "Cancelled",
        "fr": "Annulé",
        "tr": "İptal Edildi",
        "de": "Storniert",
        "es": "Cancelado"
    },
    "الكاشير": {
        "ar": "الكاشير",
        "en": "Cashier",
        "fr": "Caisse",
        "tr": "Kasiyer",
        "de": "Kasse",
        "es": "Caja"
    },
    "الكول سنتر": {
        "ar": "الكول سنتر",
        "en": "Call Center",
        "fr": "Centre d'appels",
        "tr": "Çağrı Merkezi",
        "de": "Call-Center",
        "es": "Centro de llamadas"
    },
    "المنيو الرقمي (QR)": {
        "ar": "المنيو الرقمي (QR)",
        "en": "Digital Menu (QR)",
        "fr": "Menu numérique (QR)",
        "tr": "Dijital Menü (QR)",
        "de": "Digitale Speisekarte (QR)",
        "es": "Carta Digital (QR)"
    },
    "عميل نقدي": {
        "ar": "عميل نقدي",
        "en": "Cash Customer",
        "fr": "Client comptant",
        "tr": "Nakit Müşteri",
        "de": "Barzahler",
        "es": "Cliente al contado"
    },
    "طلب تجريبي للرفض": {
        "ar": "طلب تجريبي للرفض",
        "en": "Pilot Request for Rejection",
        "fr": "Demande pilote pour rejet",
        "tr": "Red için Pilot Talep",
        "de": "Pilotantrag zur Ablehnung",
        "es": "Solicitud piloto para rechazo"
    },
    "طلب ترقية تجريبي لاختبار Django Admin Action": {
        "ar": "طلب ترقية تجريبي لاختبار Django Admin Action",
        "en": "Pilot Upgrade Request for Django Admin Action",
        "fr": "Demande de mise à niveau pilote",
        "tr": "Pilot Yükseltme Talebi",
        "de": "Pilot-Upgrade-Anfrage",
        "es": "Solicitud de mejora piloto"
    },
    "👤 اختبار العميل": {
        "ar": "👤 اختبار العميل",
        "en": "👤 Test Customer",
        "fr": "👤 Client test",
        "tr": "👤 Test Müşterisi",
        "de": "👤 Testkunde",
        "es": "👤 Cliente de prueba"
    },
    "اختبار العميل": {
        "ar": "اختبار العميل",
        "en": "Test Customer",
        "fr": "Client test",
        "tr": "Test Müşterisi",
        "de": "Testkunde",
        "es": "Cliente de prueba"
    },
    "خصم": {
        "ar": "خصم",
        "en": "Discount",
        "fr": "Remise",
        "tr": "İndirim",
        "de": "Rabatt",
        "es": "Descuento"
    },
    "ج.م": {
        "ar": "ج.م",
        "en": "EGP",
        "fr": "EGP",
        "tr": "EGP",
        "de": "EGP",
        "es": "EGP"
    },
    "د.ت": {
        "ar": "د.ت",
        "en": "TND",
        "fr": "TND",
        "tr": "TND",
        "de": "TND",
        "es": "TND"
    },
    "د.ج": {
        "ar": "د.ج",
        "en": "DZD",
        "fr": "DZD",
        "tr": "DZD",
        "de": "DZD",
        "es": "DZD"
    },
    "د.إ": {
        "ar": "د.إ",
        "en": "AED",
        "fr": "AED",
        "tr": "AED",
        "de": "AED",
        "es": "AED"
    },
    "د.ك": {
        "ar": "د.ك",
        "en": "KWD",
        "fr": "KWD",
        "tr": "KWD",
        "de": "KWD",
        "es": "KWD"
    },
    "د.م": {
        "ar": "د.م",
        "en": "MAD",
        "fr": "MAD",
        "tr": "MAD",
        "de": "MAD",
        "es": "MAD"
    },
    "الراتب": {
        "ar": "الراتب",
        "en": "Salary",
        "fr": "Salaire",
        "tr": "Maaş",
        "de": "Gehalt",
        "es": "Salario"
    },
    "نقداً (Cash)": {
        "ar": "نقداً (Cash)",
        "en": "Cash",
        "fr": "Espèces",
        "tr": "Nakit",
        "de": "Bar",
        "es": "Efectivo"
    },
    "تصنيف المشكلة": {
        "ar": "تصنيف المشكلة",
        "en": "Issue Category",
        "fr": "Catégorie du problème",
        "tr": "Sorun Kategorisi",
        "de": "Problemkategorie",
        "es": "Categoría del problema"
    },
    "مستوى الأولوية": {
        "ar": "مستوى الأولوية",
        "en": "Priority Level",
        "fr": "Niveau de priorité",
        "tr": "Öncelik Düzeyi",
        "de": "Prioritätsstufe",
        "es": "Nivel de prioridad"
    },
    "مرفقات الوسائط (صور / فيديو / مستندات)": {
        "ar": "مرفقات الوسائط (صور / فيديو / مستندات)",
        "en": "Media Attachments (Photos / Video / Documents)",
        "fr": "Pièces jointes multimédias (photos / vidéos / documents)",
        "tr": "Medya Ekleri (Fotoğraf / Video / Belgeler)",
        "de": "Medienanhänge (Fotos / Videos / Dokumente)",
        "es": "Archivos adjuntos (fotos / vídeo / documentos)"
    },
    "اسحب وأفلت الملفات هنا أو انقر للاختيار": {
        "ar": "اسحب وأفلت الملفات هنا أو انقر للاختيار",
        "en": "Drag & drop files here or click to select",
        "fr": "Glissez-déposez les fichiers ici ou cliquez pour sélectionner",
        "tr": "Dosyaları buraya sürükleyip bırakın veya seçmek için tıklayın",
        "de": "Dateien hierher ziehen und ablegen oder zum Auswählen klicken",
        "es": "Arrastra y suelta archivos aquí o haz clic para seleccionar"
    },
    "صور، فيديو، تسجيلات صوتية، ومستندات (بحد أقصى 25 ميجابايت للملف)": {
        "ar": "صور، فيديو، تسجيلات صوتية، ومستندات (بحد أقصى 25 ميجابايت للملف)",
        "en": "Images, video, voice notes, and documents (max 25MB per file)",
        "fr": "Images, vidéos, notes vocales et documents (max 25 Mo par fichier)",
        "tr": "Görseller, videolar, ses kayıtları ve belgeler (dosya başına maks. 25 MB)",
        "de": "Bilder, Videos, Sprachaufnahmen und Dokumente (max. 25 MB pro Datei)",
        "es": "Imágenes, vídeo, notas de voz y documentos (máx. 25 MB por archivo)"
    },
    "إسناد جماعي لسائق": {
        "ar": "إسناد جماعي لسائق",
        "en": "Bulk Assign to Driver",
        "fr": "Attribution groupée à un livreur",
        "tr": "Sürücüye Toplu Ata",
        "de": "Sammelzuweisung an Fahrer",
        "es": "Asignación masiva a repartidor"
    },
    "— إسناد جماعي لسائق —": {
        "ar": "— إسناد جماعي لسائق —",
        "en": "— Bulk Assign to Driver —",
        "fr": "— Attribution groupée à un livreur —",
        "tr": "— Sürücüye Toplu Ata —",
        "de": "— Sammelzuweisung an Fahrer —",
        "es": "— Asignación masiva a repartidor —"
    },
    "الطلبات المسجلة من الكاشير أو مركز الاتصال بالذكاء الاصطناعي ستصل هنا تلقائياً دون ريفريش": {
        "ar": "الطلبات المسجلة من الكاشير أو مركز الاتصال بالذكاء الاصطناعي ستصل هنا تلقائياً دون ريفريش",
        "en": "Orders registered from cashier or AI call center will arrive here live without refresh",
        "fr": "Les commandes enregistrées par la caisse ou le centre d'appels IA arrivent ici en direct sans actualisation",
        "tr": "Kasiyerden veya Yapay Zeka çağrı merkezinden kaydedilen siparişler buraya yenileme olmadan canlı gelir",
        "de": "Bestellungen von der Kasse oder dem KI-Callcenter erscheinen hier live ohne Neuladen",
        "es": "Los pedidos registrados desde caja o call center IA llegarán aquí en vivo sin recargar"
    },
    "عند بدء الطهي ستظهر الطلبات هنا لمتابعة وقت التحضير": {
        "ar": "عند بدء الطهي ستظهر الطلبات هنا لمتابعة وقت التحضير",
        "en": "When cooking starts, orders will appear here to monitor preparation time",
        "fr": "Au début de la préparation, les commandes apparaîtront ici pour suivre le temps de cuisson",
        "tr": "Pişirme başladığında siparişler hazırlık süresini takip etmek için burada görünür",
        "de": "Sobald die Zubereitung beginnt, erscheinen Bestellungen hier zur Zeiterfassung",
        "es": "Al comenzar la preparación, los pedidos aparecerán aquí para monitorear el tiempo"
    },
    "لا توجد طلبات جاهزة للتسليم الآن": {
        "ar": "لا توجد طلبات جاهزة للتسليم الآن",
        "en": "No orders ready for delivery right now",
        "fr": "Aucune commande prête à être livrée pour le moment",
        "tr": "Şu anda teslimata hazır sipariş yok",
        "de": "Derzeit keine abholbereiten Bestellungen",
        "es": "No hay pedidos listos para entrega ahora"
    },
    "عند انتهاء المطبخ من تجهيز أي طلب سيظهر هنا لتعيين السائق": {
        "ar": "عند انتهاء المطبخ من تجهيز أي طلب سيظهر هنا لتعيين السائق",
        "en": "When the kitchen completes any order, it will appear here to assign a driver",
        "fr": "Lorsque la cuisine aura préparé une commande, elle apparaîtra ici pour assigner un livreur",
        "tr": "Mutfak bir siparişi tamamladığında sürücü atamak için burada görünür",
        "de": "Sobald die Küche eine Bestellung fertiggestellt hat, erscheint sie hier zur Fahrerzuweisung",
        "es": "Cuando la cocina termine un pedido, aparecerá aquí para asignar repartidor"
    },
    "لا توجد طلبات في المسار حالياً": {
        "ar": "لا توجد طلبات في المسار حالياً",
        "en": "No orders currently on route",
        "fr": "Aucune commande en cours de livraison actuellement",
        "tr": "Şu anda yolda olan sipariş yok",
        "de": "Derzeit keine Bestellungen unterwegs",
        "es": "No hay pedidos en ruta actualmente"
    },
    "الطلبات المسلمة للسائقين والتي في طريقها للعملاء ستظهر هنا": {
        "ar": "الطلبات المسلمة للسائقين والتي في طريقها للعملاء ستظهر هنا",
        "en": "Orders handed to drivers on their way to customers will appear here",
        "fr": "Les commandes remises aux livreurs en route vers les clients apparaîtront ici",
        "tr": "Sürücülere teslim edilen ve müşterilere giden siparişler burada görünür",
        "de": "Bestellungen, die an Fahrer übergeben wurden und unterwegs sind, erscheinen hier",
        "es": "Los pedidos entregados a repartidores en camino al cliente aparecerán aquí"
    },
    "الإدارة العامة (لكل الفروع)": {
        "ar": "الإدارة العامة (لكل الفروع)",
        "en": "General Headquarters (All Branches)",
        "fr": "Direction générale (toutes les succursales)",
        "tr": "Genel Merkez (Tüm Şubeler)",
        "de": "Hauptverwaltung (Alle Filialen)",
        "es": "Sede Central (Todas las sucursales)"
    },
    "الفرع النشط": {
        "ar": "الفرع النشط",
        "en": "Active Branch",
        "fr": "Succursale active",
        "tr": "Aktif Şube",
        "de": "Aktive Filiale",
        "es": "Sucursal activa"
    },
    "السعر الافتراضي العام (Master)": {
        "ar": "السعر الافتراضي العام (Master)",
        "en": "Master Default Price",
        "fr": "Prix par défaut général (Master)",
        "tr": "Ana Varsayılan Fiyat (Master)",
        "de": "Standardpreis (Master)",
        "es": "Precio predeterminado general (Master)"
    },
    "عميل مطعم": {
        "ar": "عميل مطعم",
        "en": "Restaurant Customer",
        "fr": "Client du restaurant",
        "tr": "Restoran Müşterisi",
        "de": "Restaurantkunde",
        "es": "Cliente del restaurante"
    },
    "منيو رقمي": {
        "ar": "منيو رقمي",
        "en": "Digital Menu",
        "fr": "Menu numérique",
        "tr": "Dijital Menü",
        "de": "Digitales Menü",
        "es": "Menú digital"
    },
    "منيو رقمي (QR)": {
        "ar": "منيو رقمي (QR)",
        "en": "Digital Menu (QR)",
        "fr": "Menu numérique (QR)",
        "tr": "Dijital Menü (QR)",
        "de": "Digitales Menü (QR)",
        "es": "Menú digital (QR)"
    },
    "ملغى": {
        "ar": "ملغى",
        "en": "Cancelled",
        "fr": "Annulé",
        "tr": "İptal Edildi",
        "de": "Storniert",
        "es": "Cancelado"
    },
    "معلق": {
        "ar": "معلق",
        "en": "Pending",
        "fr": "En attente",
        "tr": "Beklemede",
        "de": "Ausstehend",
        "es": "Pendiente"
    },
    "مدفوع": {
        "ar": "مدفوع",
        "en": "Paid",
        "fr": "Payé",
        "tr": "Ödendi",
        "de": "Bezahlt",
        "es": "Pagado"
    },
    "كاشير": {
        "ar": "كاشير",
        "en": "Cashier",
        "fr": "Caisse",
        "tr": "Kasa",
        "de": "Kasse",
        "es": "Caja"
    },
    "هاتف": {
        "ar": "هاتف",
        "en": "Phone",
        "fr": "Téléphone",
        "tr": "Telefon",
        "de": "Telefon",
        "es": "Teléfono"
    },
    "كاش": {
        "ar": "كاش",
        "en": "Cash",
        "fr": "Espèces",
        "tr": "Nakit",
        "de": "Bar",
        "es": "Efectivo"
    },
    "مدى": {
        "ar": "مدى",
        "en": "Mada",
        "fr": "Mada",
        "tr": "Mada",
        "de": "Mada",
        "es": "Mada"
    },
    "تحصيل كاش": {
        "ar": "تحصيل كاش",
        "en": "Collect Cash",
        "fr": "Encaisser en espèces",
        "tr": "Nakit Tahsilat",
        "de": "Bargeld kassieren",
        "es": "Cobrar en efectivo"
    },
    "تحصيل مدى": {
        "ar": "تحصيل مدى",
        "en": "Collect Mada/Card",
        "fr": "Encaisser par carte Mada",
        "tr": "Mada/Kart Tahsilatı",
        "de": "Kartenzahlung (Mada)",
        "es": "Cobrar con tarjeta (Mada)"
    },
    "تحصيل بطريقة الدفع المحددة": {
        "ar": "تحصيل بطريقة الدفع المحددة",
        "en": "Collect with Selected Payment Method",
        "fr": "Encaisser avec le mode de paiement sélectionné",
        "tr": "Seçilen Ödeme Yöntemiyle Tahsil Et",
        "de": "Mit gewählter Zahlungsmethode kassieren",
        "es": "Cobrar con el método de pago seleccionado"
    }
}

def update():
    catalog_path = os.path.join(BASE_DIR, 'core/i18n_catalog.py')
    with open(catalog_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Merge into _RAW_CATALOG
    updated_catalog = dict(_RAW_CATALOG)
    for k, v in NEW_ENTRIES.items():
        updated_catalog[k] = v

    # Write back core/i18n_catalog.py
    # Find start and end of _RAW_CATALOG = { ... }
    start_marker = '_RAW_CATALOG = {'
    end_marker = '\nI18N_CATALOG = I18nCatalogDict(_RAW_CATALOG)'
    idx_start = content.find(start_marker)
    idx_end = content.find(end_marker)
    assert idx_start != -1 and idx_end != -1, "Could not find _RAW_CATALOG boundaries"

    formatted_items = []
    for k, v in updated_catalog.items():
        formatted_items.append(f'    {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, indent=8).strip()}')

    new_dict_str = '_RAW_CATALOG = {\n' + ',\n'.join(formatted_items) + '\n}'
    new_content = content[:idx_start] + new_dict_str + content[idx_end:]

    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"Updated core/i18n_catalog.py with {len(updated_catalog)} entries.")

    # Write static and staticfiles JSON
    static_json_path = os.path.join(BASE_DIR, 'static/js/diyafa_i18n_catalog.json')
    with open(static_json_path, 'w', encoding='utf-8') as f:
        json.dump(updated_catalog, f, ensure_ascii=False, indent=2)
    print(f"Updated {static_json_path}")

    staticfiles_json_path = os.path.join(BASE_DIR, 'staticfiles/js/diyafa_i18n_catalog.json')
    if os.path.exists(staticfiles_json_path):
        with open(staticfiles_json_path, 'w', encoding='utf-8') as f:
            json.dump(updated_catalog, f, ensure_ascii=False, indent=2)
        print(f"Updated {staticfiles_json_path}")

    staticfiles_gz_path = os.path.join(BASE_DIR, 'staticfiles/js/diyafa_i18n_catalog.json.gz')
    if os.path.exists(staticfiles_gz_path):
        with gzip.open(staticfiles_gz_path, 'wt', encoding='utf-8') as f:
            json.dump(updated_catalog, f, ensure_ascii=False)
        print(f"Updated {staticfiles_gz_path}")

if __name__ == '__main__':
    update()
