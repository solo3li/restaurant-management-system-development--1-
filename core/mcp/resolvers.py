import re
import json
import logging
from typing import List, Dict, Any, Optional, Union
from decimal import Decimal

logger = logging.getLogger(__name__)

def _normalize_digits(text: Any) -> str:
    """تحويل الأرقام المشرقية والعربية (٠-٩) إلى أرقام قياسية (0-9)."""
    if not text:
        return ""
    hindi_to_arabic = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return str(text).translate(hindi_to_arabic)


def _strip_al(w: str) -> str:
    """إزالة أداة التعريف (ال) للمقارنة الدقيقة للأطعمة والمناطق دون كسر الكلمات الأصلية."""
    if not w:
        return ""
    preserved_roots = {
        "البان", "الوان", "الماس", "الم", "الياس", "الف", "الوف", "الكترونيات",
        "الام", "الولايات", "اله", "اليف"
    }
    if w in preserved_roots:
        return w
    if w.startswith("ال") and len(w) > 4:
        return w[2:]
    return w


def _normalize_arabic_text(text: str) -> str:
    """تسوية النصوص العربية للمطابقة الدقيقة مع الأصناف والمناطق."""
    if not text:
        return ""
    t = _normalize_digits(str(text)).strip().lower()
    t = re.sub(r'[\u064B-\u0652]', '', t)
    t = re.sub(r'[أإآٱ]', 'ا', t)
    t = re.sub(r'[ىي]', 'ي', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _canonical_food_name(text: str) -> str:
    """
    محرك المرادفات اللغوية والشعبية للأطعمة والمشروبات:
    يوحد لهجات العملاء الشائعة (فراخ -> دجاج، لحمه -> لحم) مع الحفاظ التام على هوية البراندات والمشروبات.
    """
    norm = _normalize_arabic_text(text)
    words = norm.split()

    synonyms = {
        "فراخ": "دجاج",
        "فرخه": "دجاج",
        "دجاجه": "دجاج",
        "تشيكن": "دجاج",
        "تشكن": "دجاج",
        "لحمه": "لحم",
        "برجر": "برجر",
        "بورجر": "برجر",
        "سنجل": "سينجل",
        "دبل": "دبل",
        "دابل": "دبل",
        "بطاطس": "بطاطس",
        "فرنش": "بطاطس",
        "فرايز": "بطاطس",
        "حار": "حار",
        "سبايسي": "حار",
        "حاره": "حار",
        "موتزاريلا": "موزاريلا",
        "موتزريلا": "موزاريلا",
        "موزريلا": "موزاريلا",
        "ضاني": "غنم",
        "ضان": "غنم",
        "خروف": "غنم",
        # الحفاظ على هوية البراندات المنفصلة للمشروبات
        "بيبسي": "بيبسي",
        "كولا": "كولا",
        "كوكاكولا": "كولا",
        "كوكا": "كولا",
        "سفن": "سفن",
        "سفن اب": "سفن",
        "سبرايت": "سبرايت",
        "فانتا": "فانتا",
        "ميرندا": "ميرندا",
        "ميراندا": "ميرندا",
        "شويبس": "شويبس",
        "ديو": "ديو",
        "ماونتن ديو": "ديو",
        "كانز": "مشروب غازي",
        "صودا": "مشروب غازي",
        "مشروب غازي": "مشروب غازي",
        "ميه": "ماء",
        "مياه": "ماء",
        "مويه": "ماء",
        "ماء صحي": "ماء",
        "صياد": "صياديه",
        "سمكه": "سمك",
        "شيش": "شيش طاووق",
    }

    fillers = {"وجبه", "ساندوتش", "سندوتش", "سندوتشات", "ساندويتش", "ساندويتشات", "طبق", "علبه", "طلب", "واحد", "اثنين", "عدد"}
    cleaned = []
    for w in words:
        base_w = _strip_al(w)
        if base_w in fillers and len(words) > 1:
            continue
        cleaned.append(synonyms.get(base_w, synonyms.get(w, base_w)))

    res = " ".join(cleaned)
    res = res.replace("صياد سمك", "صياديه سمك")
    return re.sub(r'\s+', ' ', res).strip()


def _clean_phone(phone: Any) -> str:
    """تنظيف وتوحيد رقم الهاتف لتسهيل البحث والمطابقة."""
    if not phone:
        return ""
    p = _normalize_digits(str(phone)).strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if p.startswith("+"):
        p = p[1:]
    return p


def _parse_natural_order_text(text: str, tenant=None, branch=None) -> List[Dict[str, Any]]:
    """تحليل النص العامي إلى قائمة أصناف وكميات مرنة للمكالمات الصوتية دون قص الحروف الأصلية."""
    if not text or not isinstance(text, str):
        return []

    clean_text = _normalize_arabic_text(str(text))
    num_map = {
        "واحد": 1, "واحده": 1, "واحدة": 1, "١": 1, "1": 1,
        "اتنين": 2, "اثنين": 2, "إثنين": 2, "٢": 2, "2": 2,
        "تلاتة": 3, "ثلاثة": 3, "٣": 3, "3": 3,
        "اربعة": 4, "أربعة": 4, "٤": 4, "4": 4,
        "خمسة": 5, "٥": 5, "5": 5,
        "ستة": 6, "٦": 6, "6": 6,
    }

    split_pattern = r'[,،\n\+]|\s+(?:مع|\+)\s*|\s+و\s+|\s+و(?=\d|واحد|اتنين|اثنين|تلاتة|ثلاثة|اربعة|خمسة|ستة)|\s+و(?=ورق|وافل|وينجز|وجب|ووك)|\s+و(?!(?:ورق|وافل|وينجز|وجب|ووك|ويفر|ورد))\b'
    segments = re.split(split_pattern, clean_text)
    items = []

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        qty = 1
        name_candidate = seg
        m_lead = re.match(r'^(?:عدد\s+)?(\d+|واحد|واحده|واحدة|اتنين|اثنين|إثنين|تلاتة|ثلاثة|اربعة|أربعة|خمسة|ستة)\s*(?:من\s+)?(?:قطع\s+|قطعة\s+|وجبة\s+|ساندوتش\s+)?(.+)$', seg)
        if m_lead:
            raw_qty, name_candidate = m_lead.group(1), m_lead.group(2)
            qty = num_map.get(raw_qty, int(raw_qty) if raw_qty.isdigit() else 1)
        else:
            m_trail = re.match(r'^(.+?)\s+(\d+|واحد|واحده|واحدة|اتنين|اثنين|تلاتة|ثلاثة)$', seg)
            if m_trail:
                name_candidate, raw_qty = m_trail.group(1), m_trail.group(2)
                qty = num_map.get(raw_qty, int(raw_qty) if raw_qty.isdigit() else 1)

        name_candidate = name_candidate.strip()
        if name_candidate:
            items.append({"name": name_candidate, "quantity": max(1, qty)})

    return items


def _resolve_item_variant(item, branch, item_spec: dict, raw_name: str) -> tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """
    فحص ومطابقة أحجام وخيارات الصنف (MenuItemVariant):
    إذا كان للصنف أحجام ولم يحدد العميل الحجم المطلوب، يُرجع دليلاً للذكاء الاصطناعي لسؤال العميل مع توضيح الأسعار.
    """
    if not getattr(item, "has_variants", False) or not item.variants.exists():
        return None, None

    variants = list(item.variants.all())
    if not variants:
        return None, None

    req_var = str(item_spec.get("variant") or item_spec.get("size") or "").strip()
    norm_req = _normalize_arabic_text(req_var) if req_var else ""
    norm_name = _normalize_arabic_text(raw_name)

    matched_var = None
    if norm_req:
        for v in variants:
            nv = _normalize_arabic_text(v.name)
            if nv == norm_req or nv in norm_req or norm_req in nv:
                matched_var = v
                break

    if not matched_var and norm_name:
        for v in variants:
            nv = _normalize_arabic_text(v.name)
            if nv in norm_name:
                matched_var = v
                break

    if matched_var:
        return matched_var, None

    cur_sym = branch.get_currency_symbol_ar() if branch else "ر.س"
    variants_summary = "، ".join([f"«{v.name}» ({v.get_price_for_branch(branch):.0f} {cur_sym})" for v in variants])
    return None, {
        "ok": False,
        "is_system_error": False,
        "status": "variant_selection_required",
        "item_id": item.id,
        "item_name": item.name,
        "available_variants": [
            {"id": v.id, "name": v.name, "price": float(v.get_price_for_branch(branch))}
            for v in variants
        ],
        "ai_speech_response": f"صنف «{item.name}» متاح منه خيارات: {variants_summary}. تحب أي حجم؟",
        "instruction_for_ai": f"لا تسجل الطلب الآن! اسأل العميل بلطف عن الحجم المطلوب لصنف «{item.name}» من بين الخيارات المتاحة ({variants_summary}) كما في ai_speech_response."
    }


def _find_menu_item(tenant, branch, item_spec: Any, disabled_item_ids: set, all_tenant_items: Optional[List[Any]] = None) -> tuple[Optional[Any], Optional[Any], Optional[Union[str, Dict[str, Any]]]]:
    """
    محرك بحث ومطابقة ذكي وشامل للأصناف والأحجام:
    1. التحقق بواسطة item_id أو id المباشر.
    2. التحقق الدقيق بواسطة الاسم وقاموس مرادفات اللهجات (فراخ -> دجاج، لحمة -> لحم).
    3. التحقق بتطابق الكلمات والكلمات الجزئية.
    4. فحص توفر الصنف في الفرع الحالي.
    5. مطابقة الحجم والخيارات (Variant) واسترجاع توجيه للـ AI إن لم يُحدد الحجم.
    """
    from core.models import MenuItem

    if hasattr(item_spec, "model_dump"):
        item_spec = item_spec.model_dump()
    elif hasattr(item_spec, "dict"):
        item_spec = item_spec.dict()
    elif isinstance(item_spec, str):
        try:
            item_spec = json.loads(item_spec)
        except Exception:
            item_spec = {"name": item_spec}

    if not isinstance(item_spec, dict):
        item_spec = {"name": str(item_spec)}

    raw_id = item_spec.get("item_id") if item_spec.get("item_id") is not None else item_spec.get("id")
    raw_name = str(item_spec.get("name") or item_spec.get("item_name") or "").strip()

    if all_tenant_items is None:
        all_tenant_items = list(MenuItem.objects.filter(tenant=tenant, available=True).prefetch_related("variants"))

    # 1. البحث برقم الصنف (ID)
    if raw_id is not None:
        try:
            m_id = int(raw_id)
            item = next((m for m in all_tenant_items if m.id == m_id), None)
            if not item:
                item = MenuItem.objects.filter(tenant=tenant, id=m_id, available=True).first()
            if not item:
                return None, None, f"الصنف برقم #{m_id} غير موجود في قائمة طعام المنشأة."
            if item.id in disabled_item_ids:
                return None, None, f"الصنف «{item.name}» (رقم #{item.id}) غير متوفر حالياً في فرع «{branch.name}»."
            v_obj, v_err = _resolve_item_variant(item, branch, item_spec, raw_name or item.name)
            if v_err:
                return item, None, v_err
            return item, v_obj, None
        except (ValueError, TypeError):
            pass

    # 2. البحث بالاسم
    if not raw_name:
        return None, None, "يجب تحديد رقم الصنف (item_id) أو اسمه (name) في عناصر الطلب."

    norm_query = _normalize_arabic_text(raw_name)
    canon_query = _canonical_food_name(raw_name)

    matched_item = None

    # 2.1 المطابقة التامة المباشرة بالاسم
    for m in all_tenant_items:
        if _normalize_arabic_text(m.name) == norm_query:
            if m.id in disabled_item_ids:
                return None, None, f"الصنف «{m.name}» غير متوفر حالياً في فرع «{branch.name}»."
            matched_item = m
            break

    # 2.2 المطابقة بعد تطبيق قاموس المرادفات واللهجات
    if not matched_item:
        for m in all_tenant_items:
            if _canonical_food_name(m.name) == canon_query:
                if m.id in disabled_item_ids:
                    return None, None, f"الصنف «{m.name}» غير متوفر حالياً في فرع «{branch.name}»."
                matched_item = m
                break

    # 2.3 المطابقة بمجموعة الكلمات الأساسية
    if not matched_item:
        q_tokens = set(canon_query.split())
        if q_tokens:
            token_matches = [m for m in all_tenant_items if q_tokens.issubset(set(_canonical_food_name(m.name).split()))]
            if len(token_matches) == 1:
                matched_item = token_matches[0]
                if matched_item.id in disabled_item_ids:
                    return None, None, f"الصنف «{matched_item.name}» غير متوفر حالياً في فرع «{branch.name}»."
            elif len(token_matches) > 1:
                matching_names = " أو ".join([f"«{m.name}» (رقم #{m.id})" for m in token_matches[:4]])
                return None, None, f"اسم الصنف «{raw_name}» غير محدد بدقة ويطابق أكثر من صنف: ({matching_names}). يرجى تحديد الاسم بالكامل أو استخدام رقم الصنف."

    # 2.4 مطابقة الاحتواء الجزئي
    if not matched_item:
        contains_matches = [
            m for m in all_tenant_items
            if (canon_query in _canonical_food_name(m.name) or _canonical_food_name(m.name) in canon_query)
        ]
        if len(contains_matches) == 1:
            matched_item = contains_matches[0]
            if matched_item.id in disabled_item_ids:
                return None, None, f"الصنف «{matched_item.name}» غير متوفر حالياً في فرع «{branch.name}»."

    # 2.5 في حال عدم العثور عليه
    if not matched_item:
        available_branch_items = [m.name for m in all_tenant_items if m.id not in disabled_item_ids][:5]
        suggest_str = "، ".join(available_branch_items)
        return None, None, f"الصنف «{raw_name}» غير موجود في قائمة طعام المطعم. من الأصناف المتوفرة: {suggest_str}."

    # 2.6 مطابقة الحجم والخيارات (Variant)
    v_obj, v_err = _resolve_item_variant(matched_item, branch, item_spec, raw_name)
    if v_err:
        return matched_item, None, v_err
    return matched_item, v_obj, None


def _validate_delivery_address_completeness(
    clean_addr: str,
    matched_area_name: str = ""
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """التحقق المرن المتكيف من اكتمال عنوان التوصيل وفقاً للمعايير القياسية."""
    raw_addr = str(clean_addr or "").strip()
    if not raw_addr:
        return False, {
            "ok": False,
            "is_system_error": False,
            "status": "address_details_required",
            "error": "عنوان التوصيل فارغ أو غير محدد.",
            "ai_speech_response": "فضلاً تزويدنا بعنوان التوصيل بالتفصيل لنتمكن من توصيل الطلب لحضرتك.",
            "instruction_for_ai": "اطلب من العميل تزويدك بعنوان التوصيل بالتفصيل كما في ai_speech_response."
        }

    norm_addr = _normalize_arabic_text(raw_addr)
    norm_area = _normalize_arabic_text(matched_area_name)
    combined = f"{norm_area} {norm_addr}".strip()
    words = norm_addr.split()

    area_label = matched_area_name.strip() if matched_area_name.strip() else raw_addr.split("،")[0].split("-")[0].strip()

    bldg_tokens = [
        "عماره", "عمارة", "فيلا", "بلوك", "قطعه", "قطعة", "منزل", "بيت", "برج", "مبني", "مبنى",
        "مجمع", "كمبوند", "كومبوند", "قصر", "استراحه", "استراحة"
    ]
    has_bldg = any(t in norm_addr for t in bldg_tokens)

    unit_tokens = [
        "شقه", "شقة", "دور", "طابق", "ارضي", "أرضي", "وحده", "وحدة", "سويت", "مكتب", "استوديو",
        "جناح", "بوابه", "بوابة", "ملحق", "سطح"
    ]
    has_unit = any(t in norm_addr for t in unit_tokens)

    loc_tokens = ["شارع", "طريق", "حي", "حاره", "حارة", "زقاق", "ميدان", "تقاطع", "مجاوره", "مجاورة"]
    has_loc = any(t in norm_addr for t in loc_tokens)

    comm_tokens = ["محل", "معرض", "شركه", "شركة", "مكتب", "عياده", "عيادة", "كافيه", "مطعم", "فرع", "بنك", "معمل", "ستور", "store", "فندق", "hotel"]
    has_comm = any(t in norm_addr for t in comm_tokens)

    has_num = bool(
        re.search(r'\d+', norm_addr) or
        re.search(r'\b(اول|الاول|تاني|التاني|ثاني|الثاني|تالت|التالت|ثالث|الثالث|رابع|الرابع|خامس|الخامس|سادس|السادس|سابع|السابع|تامن|التامن|ثامن|الثامن|تاسع|التاسع|عاشر|العاشر|ارضي|الارضي|اخير|الاخير)\b', norm_addr)
    )

    is_explicit_residential = (has_bldg and (has_unit or "فيلا" in norm_addr or "منزل" in norm_addr) and has_num)

    landmark_keywords = [
        "الرياض بارك", "النخيل مول", "بانوراما", "العرب مول", "رد سي", "الظهران مول", "الأندلس مول",
        "برج المملكه", "برج المملكة", "برج الفيصليه", "برج الفيصلية", "بوليفارد", "العثيم", "التميمي",
        "بنده", "الدانوب", "السدحان", "لولو", "غرناطة مول", "الحمراء مول", "تالا مول",
        "كارفور", "carrefour", "هايبر", "سوبر ماركت", "ماركت", "خير زمان", "اولاد رجب", "أولاد رجب",
        "فتح الله", "كازيون", "بيم", "سعودي", "سبينس", "مول", "mall", "كايرو فيستيفال",
        "سيتي ستارز", "اركان", "القريه الذكيه", "داون تاون", "سنتر", "بيزنس بارك", "مبني اداري",
        "مجمع البنوك", "بوينت 90", "امريكانا بلازا", "ميدتاون", "سيتي سنتر", "سيتي ووك",
        "نادي", "نادى", "استاد", "مستشفي", "مستشفى", "عيادات", "مركز طبي", "جامعه", "جامعة",
        "كليه", "كلية", "مدرسه", "مدرسة", "محطه", "محطة", "مترو", "قطار", "مسجد", "جامع"
    ]
    is_landmark = any(k in combined for k in landmark_keywords)

    if is_landmark and not is_explicit_residential:
        clean_landmark = re.sub(
            r'^(هستلمه\s+من|هستلم\s+من|استلام\s+من|من|عند|في|بجوار|جنب|قصاد|امام|أمام|قدام)\s+',
            '',
            raw_addr.strip(),
            flags=re.IGNORECASE
        ).strip()
        landmark_label = clean_landmark if (clean_landmark and len(clean_landmark) <= 45) else (area_label or raw_addr.strip())

        outdoor_tokens = [
            "بره", "برة", "خارجي", "خارج", "في الشارع", "عالشارع", "على الشارع", "بالشارع", "في شارع",
            "قدام", "امام", "أمام", "قصاد", "على الرصيف", "عالرصيف", "عند البوابه", "عند البوابة",
            "في العربيه", "في العربية", "عالعربيه", "عالعربية", "عالسياره", "عالسيارة", "على السياره", "على السيارة",
            "على البوابه", "على البوابة", "قدام البوابه", "قدام البوابة", "على الباب", "قدام الباب", "عند المدخل"
        ]
        has_outdoor = any(t in norm_addr for t in outdoor_tokens)

        indoor_tokens = [
            "محل", "معرض", "شركه", "شركة", "مكتب", "عياده", "عيادة", "فرع", "ستور", "store",
            "جوه", "جوا", "داخل", "طابق", "دور", "سويت", "كشك"
        ]
        has_indoor = any(t in norm_addr for t in indoor_tokens)

        if has_outdoor and len(words) >= 2:
            return True, None

        if has_indoor:
            indoor_complete = has_comm and (has_unit or "بوابه" in norm_addr or has_num or "دور" in norm_addr or "طابق" in norm_addr) and len(words) >= 3
            if not indoor_complete:
                speech = f"فضلاً تزويدنا باسم المحل أو المكتب داخل {landmark_label} ورقم الدور أو البوابة."
                return False, {
                    "ok": False,
                    "is_system_error": False,
                    "status": "address_details_required",
                    "typology": "commercial_indoor",
                    "area_name": area_label,
                    "error": f"العنوان داخل المعلم «{landmark_label}» يتطلب اسم المحل/المكتب ورقم الدور أو البوابة.",
                    "ai_speech_response": speech,
                    "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل: «{speech}»."
                }
            return True, None

        speech = f"فضلاً هل الاستلام بالخارج أمام {landmark_label}، أم بمحل أو مكتب بالداخل؟"
        return False, {
            "ok": False,
            "is_system_error": False,
            "status": "disambiguation_required",
            "typology": "landmark_disambiguation",
            "area_name": area_label,
            "error": f"العنوان عند المعلم «{landmark_label}» يتطلب حسم ما إذا كان الاستلام بالخارج أم بالداخل.",
            "ai_speech_response": speech,
            "instruction_for_ai": f"لا تسجل الطلب الآن! اسأل العميل: «{speech}»."
        }

    compound_keywords = [
        "كمبوند", "كومبوند", "مدينتي", "مدينتى", "الرحاب", "رحاب", "هايد بارك",
        "ميفيدا", "باديه", "بادية", "سوديك", "بالم هيلز", "ماونتن فيو", "بيفرلي",
        "سوان ليك", "اب تاون", "تاج سيتي", "زاد", "zed", "المجمع السكني"
    ]
    is_compound = any(k in combined for k in compound_keywords)
    if is_compound:
        cmpnd_group_tokens = ["مجموعه", "مجموعة", "مرحله", "مرحلة", "زون", "zone", "قطاع", "جروب", "group", "فيلات", "عمارات", "حرف",
                              "b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8", "b9", "b10", "b11", "b12"]
        has_group = any(t in norm_addr for t in cmpnd_group_tokens)
        compound_complete = (
            (has_group or has_bldg) and
            (has_unit or "فيلا" in norm_addr or "بوابه" in norm_addr) and
            has_num and
            len(words) >= 3
        )
        if not compound_complete:
            speech = f"فضلاً في {area_label} تحديد رقم المرحلة أو المجموعة، ورقم العمارة والشقة لوصول المندوب لحضرتك."
            return False, {
                "ok": False,
                "is_system_error": False,
                "status": "address_details_required",
                "typology": "gated_compound",
                "area_name": area_label,
                "error": f"العنوان في المجمع/الكمبوند «{area_label}» يتطلب رقم المجموعة/المرحلة والعمارة ورقم الشقة.",
                "ai_speech_response": speech,
                "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل: «{speech}»."
            }
        return True, None

    is_street_complete = (
        (has_bldg or "فيلا" in norm_addr or "منزل" in norm_addr or "برج" in norm_addr) and
        (has_unit or "فيلا" in norm_addr or "منزل" in norm_addr or has_loc) and
        has_num and
        len(words) >= 3
    )

    if not is_street_complete:
        speech = "فضلاً تزويدنا باسم الشارع، رقم المبنى، ورقم الطابق أو الشقة لتوصيل الطلب بسهولة."
        if area_label and not area_label.startswith("شارع"):
            speech = f"فضلاً في {area_label} تحديد اسم الشارع، رقم المبنى، ورقم الدور أو الشقة لتوصيل الطلب."
        return False, {
            "ok": False,
            "is_system_error": False,
            "status": "address_details_required",
            "typology": "standard_street",
            "area_name": area_label,
            "error": "العنوان يتطلب تحديد اسم الشارع ورقم المبنى والدور والشقة.",
            "ai_speech_response": speech,
            "instruction_for_ai": f"لا تسجل الطلب الآن! انطق للعميل: «{speech}»."
        }

    return True, None


def _format_branch_closed_err(branch):
    """صياغة رد صوتي ونظامي مهذب وواضح للذكاء الاصطناعي عند إغلاق الفرع أو تعليق استقبال الطلبات."""
    if not getattr(branch, "is_accepting_orders", True):
        reason = f"فرع «{branch.name}» موقف استقبال الطلبات مؤقتاً في الوقت الحالي."
        speech = f"بعتذر لحضرتك يا فندم، فرع «{branch.name}» موقف استقبال الطلبات مؤقتاً حالياً."
    elif branch.opening_time and branch.closing_time:
        op_str = f"من {branch.opening_time.strftime('%I:%M %p')} إلى {branch.closing_time.strftime('%I:%M %p')}"
        reason = f"فرع «{branch.name}» مغلق حالياً، أوقات العمل الرسمية {op_str}."
        speech = f"بعتذر جداً لحضرتك يا فندم، فرع «{branch.name}» مغلق حالياً، ومواعيد العمل {op_str}."
    else:
        reason = f"فرع «{branch.name}» مغلق حالياً."
        speech = f"بعتذر لحضرتك يا فندم، فرع «{branch.name}» مغلق حالياً لاستقبال الطلبات."
    return {
        "ok": False,
        "is_system_error": False,
        "status": "branch_closed",
        "branch_id": branch.id,
        "branch_name": branch.name,
        "error": reason,
        "ai_speech_response": speech,
        "instruction_for_ai": "أبلغ العميل بلطف بأن الفرع مغلق حالياً كما في ai_speech_response."
    }


def _resolve_delivery_coverage_and_branch(
    tenant,
    customer_address: str,
    branch_id: Optional[int] = None,
    delivery_area_id: Optional[int] = None,
    delivery_area_name: Optional[str] = None
) -> tuple[Optional[Any], Optional[Any], Optional[Dict[str, Any]]]:
    """محرك التوجيه الجغرافي الشامل وفحص التغطية لجميع الفروع."""
    from core.models import Branch, DeliveryArea

    clean_addr = str(customer_address or "").strip()
    if not clean_addr:
        return None, None, {
            "ok": False,
            "is_system_error": False,
            "error": "عنوان التوصيل مطلوب لتنفيذ طلبات التوصيل (Delivery).",
            "ai_speech_response": "يا فندم محتاجة أعرف عنوان التوصيل بالتفصيل عشان أقدر أأكد لحضرتك الطلب وأشوف أقرب فرع.",
            "instruction_for_ai": "اطلب من العميل تزويدك بعنوان التوصيل بالحي والشارع كما في ai_speech_response ولا تقل إن هناك عطلاً بالسيستم."
        }

    norm_addr = _normalize_arabic_text(clean_addr)

    if branch_id is not None:
        candidate_branches = list(Branch.objects.filter(tenant=tenant, id=branch_id, status="active"))
        if candidate_branches and not candidate_branches[0].is_currently_open():
            return None, None, _format_branch_closed_err(candidate_branches[0])
    else:
        candidate_branches = list(Branch.objects.filter(tenant=tenant, status="active"))

    if not candidate_branches:
        return None, None, {
            "ok": False,
            "is_system_error": False,
            "error": "لا توجد فروع نشطة متاحة للمنشأة حالياً.",
            "ai_speech_response": "بعتذر لحضرتك، فروعنا مغلقة حالياً لاستقبال الطلبات، نسعد بخدمتك في أوقات العمل الرسمية.",
            "instruction_for_ai": "أبلغ العميل بلطف أن الفروع مغلقة حالياً."
        }

    if not any(b.is_currently_open() for b in candidate_branches):
        return None, None, _format_branch_closed_err(candidate_branches[0])

    candidate_branches.sort(key=lambda b: (not b.is_currently_open()))

    poly_branches = [
        b for b in candidate_branches
        if b.delivery_polygon and isinstance(b.delivery_polygon, list) and len(b.delivery_polygon) >= 3
    ]

    if poly_branches:
        candidate_branches = poly_branches
    else:
        has_named_areas = DeliveryArea.objects.filter(branch__in=candidate_branches, is_active=True).exists()
        if not has_named_areas:
            return None, None, {
                "ok": False,
                "is_system_error": False,
                "status": "no_polygons_configured",
                "error": "خدمة التوصيل غير مفعلة لعدم اكتمال رسم زون التوصيل الجغرافي (المضلع) أو تحديد مناطق التوصيل.",
                "ai_speech_response": "يا فندم خدمة التوصيل غير مفعلة حالياً لفروعنا لعدم اكتمال تحديد النطاق، لكن يشرفنا نجهز لحضرتك الطلب سفري تستلمه من أقرب فرع.",
                "suggested_action": "takeaway",
                "instruction_for_ai": "أبلغ العميل بلطف أن خدمة التوصيل غير متاحة واقترح عليه الاستلام من الفرع سفري."
            }

    all_areas = list(DeliveryArea.objects.filter(branch__in=candidate_branches, is_active=True).select_related("branch"))
    matched_area = None

    if delivery_area_id:
        matched_area = next((a for a in all_areas if a.id == delivery_area_id), None)

    if not matched_area and delivery_area_name:
        norm_param_area = _normalize_arabic_text(delivery_area_name)
        for a in all_areas:
            norm_a = _normalize_arabic_text(a.name)
            if norm_a == norm_param_area or norm_param_area in norm_a or norm_a in norm_param_area:
                matched_area = a
                break

    if not matched_area:
        for a in all_areas:
            norm_a = _normalize_arabic_text(a.name)
            if norm_a in norm_addr or norm_addr in norm_a:
                matched_area = a
                break

    if not matched_area:
        stop_words = {
            "مدينه", "مدينة", "حي", "الحي", "منطقه", "منطقة", "كمبوند", "شارع", "طريق",
            "عمارة", "عماره", "شقه", "شقة", "رقم", "مجاورة", "مجاوره", "بجوار", "امام", "أمام",
            "خلف", "قريب", "عند", "في", "من", "على", "الى", "إلى", "حدائق", "شمال", "جنوب", "شرق", "غرب", "ميدان", "برج", "دور"
        }
        best_score = 0
        best_candidate = None
        addr_tokens = set(w for w in norm_addr.split() if w not in stop_words and len(w) >= 3)
        for a in all_areas:
            area_tokens = set(w for w in _normalize_arabic_text(a.name).split() if w not in stop_words and len(w) >= 3)
            overlap = len(area_tokens & addr_tokens)
            if overlap > best_score:
                best_score = overlap
                best_candidate = a
        if best_candidate and best_score >= 1:
            matched_area = best_candidate

    if matched_area:
        if not matched_area.branch.is_currently_open():
            return None, None, _format_branch_closed_err(matched_area.branch)
        return matched_area.branch, matched_area, None

    try:
        from core.google_maps_service import resolve_smart_delivery_with_google
        g_branch, g_area_info, g_res = resolve_smart_delivery_with_google(tenant, clean_addr, branch_id=branch_id)
        if g_branch and g_res and g_res.get("ok"):
            if not g_branch.is_currently_open():
                return None, None, _format_branch_closed_err(g_branch)

            class DynamicDeliveryArea:
                def __init__(self, data, branch_obj):
                    self.id = None
                    self.pk = None
                    self.name = data["name"]
                    self.branch = branch_obj
                    self.area_type = data.get("area_type", "zone")
                    self.delivery_fee = Decimal(str(data["delivery_fee"]))
                    self.estimated_time_minutes = int(data.get("estimated_time_minutes", 35))
                    self.notes = data.get("notes", "")

                def get_area_type_display(self):
                    return self.area_type

                def __str__(self):
                    return f"{self.name} - {self.branch.name}"

            dyn_area = DynamicDeliveryArea(g_area_info, g_branch)
            return g_branch, dyn_area, None
        elif g_res and not g_res.get("ok"):
            return None, None, g_res
    except Exception as e:
        logger.warning(f"Error in smart Google Maps delivery resolution: {e}")

    covered_names = list(dict.fromkeys(a.name for a in all_areas))
    covered_str = "، ".join(covered_names[:5])
    return None, None, {
        "ok": False,
        "is_system_error": False,
        "error": f"العنوان المحدد «{clean_addr}» خارج نطاق تغطية التوصيل لفروعنا حالياً. المناطق المغطاة: {covered_str}.",
        "available_areas": covered_names,
        "suggested_action": "takeaway",
        "ai_speech_response": f"يا فندم عنوان حضرتك خارج نطاق التوصيل المباشر لفروعنا حالياً. من المناطق اللي بنوصلها: {covered_str}. تحب نجهزه لحضرتك استلام من أقرب فرع (سفري)؟",
        "instruction_for_ai": "أبلغ العميل بلطف أن العنوان خارج نطاق التوصيل واقترح عليه الاستلام من الفرع كما في ai_speech_response."
    }
