import logging
import math
import re
import urllib.parse
import urllib.request
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from django.conf import settings

logger = logging.getLogger(__name__)


def get_active_google_maps_key(tenant=None) -> str:
    """
    استرجاع مفتاح Google Maps API النشط بالأولويات التالية:
    1. مفتاح المنشأة المخصص (Tenant.google_maps_api_key) إن وجد.
    2. المفتاح المركزي العام للمنصة (PlatformConfiguration.google_maps_api_key).
    3. متغير البيئة GOOGLE_MAPS_API_KEY أو settings.GOOGLE_MAPS_API_KEY.
    """
    if tenant and getattr(tenant, "google_maps_api_key", None):
        key = str(tenant.google_maps_api_key).strip()
        if key:
            return key

    try:
        from core.models import PlatformConfiguration
        cfg = PlatformConfiguration.get_solo()
        if cfg and cfg.google_maps_api_key:
            key = str(cfg.google_maps_api_key).strip()
            if key:
                return key
    except Exception as e:
        logger.debug(f"Failed to fetch PlatformConfiguration: {e}")

    return getattr(settings, "GOOGLE_MAPS_API_KEY", "") or ""


def is_point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    """
    فحص خوارزمي (Ray Casting Algorithm) لتحديد هل النقطة (lat, lng) تقع داخل مضلع التغطية (Geofence).
    يدعم صيغ النقاط: [[lat, lng], ...] أو [{'lat': ..., 'lng': ...}, ...]
    """
    if not polygon or len(polygon) < 3:
        return False

    pts: List[Tuple[float, float]] = []
    for p in polygon:
        try:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append((float(p[0]), float(p[1])))
            elif isinstance(p, dict) and "lat" in p and "lng" in p:
                pts.append((float(p["lat"]), float(p["lng"])))
        except (ValueError, TypeError):
            continue

    if len(pts) < 3:
        return False

    n = len(pts)
    inside = False
    p1x, p1y = pts[0]
    for i in range(1, n + 1):
        p2x, p2y = pts[i % n]
        if lat > min(p1x, p2x):
            if lat <= max(p1x, p2x):
                if lng <= max(p1y, p2y):
                    if p1x != p2x:
                        xinters = (lat - p1x) * (p2y - p1y) / (p2x - p1x) + p1y
                    else:
                        xinters = p1y
                    if p1y == p2y or lng <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """حساب المسافة الجغرافية المستقيمة بالكيلومتر بين نقطتين (Haversine Formula)."""
    r = 6371.0  # نصف قطر الأرض بالكيلومتر
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(r * c, 2)


def extract_coordinates_from_url(url: str) -> Optional[Tuple[float, float]]:
    """
    استخراج الإحداثيات (lat, lng) من روابط خرائط جوجل (Google Maps URLs):
    يدعم:
      - روابط قصيرة مثل: https://maps.app.goo.gl/... أو https://goo.gl/maps/...
      - روابط مباشرة تحتوي على: @30.0444,31.2357 أو ?q=30.0444,31.2357 أو destination=...
    """
    clean_url = str(url or "").strip()
    if not clean_url:
        return None

    # إذا كان رابطاً مختصراً، نتتبع التوجيه (Redirect)
    if "maps.app.goo.gl" in clean_url or "goo.gl/maps" in clean_url:
        try:
            req = urllib.request.Request(
                clean_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=4) as response:
                clean_url = response.geturl()
        except Exception as e:
            logger.warning(f"Failed to resolve short Google Maps URL {clean_url}: {e}")

    # 1. البحث عن نمط @lat,lng
    m_at = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', clean_url)
    if m_at:
        return float(m_at.group(1)), float(m_at.group(2))

    # 2. البحث عن نمط q=lat,lng أو ll=lat,lng أو destination=lat,lng
    m_q = re.search(r'[?&](?:q|ll|destination)=(-?\d+\.\d+),(-?\d+\.\d+)', clean_url)
    if m_q:
        return float(m_q.group(1)), float(m_q.group(2))

    return None


def extract_coordinates_from_text(text: str) -> Optional[Tuple[float, float]]:
    """
    فحص ما إذا كان النص يحتوي مباشرة على إحداثيات (lat, lng) مثل '30.0444, 31.2357'.
    """
    if not text:
        return None
    m = re.search(r'(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)', text)
    if m:
        try:
            lat = float(m.group(1))
            lng = float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            pass
    return None


def geocode_address(address_text: str, api_key: str = "", region: str = "eg") -> Optional[Dict[str, Any]]:
    """
    تحويل العنوان النصي أو اسم المعلم إلى إحداثيات وبيانات دقيقة عبر Google Geocoding API.
    يدعم الروابط المباشرة والإحداثيات النصية حتى بدون وجود مفتاح API.
    """
    if not address_text:
        return None

    # التحقق أولاً إن كان النص رابطاً لخرائط جوجل (لا يتطلب مفتاح API)
    coords_from_url = extract_coordinates_from_url(address_text)
    if coords_from_url:
        lat, lng = coords_from_url
        return {
            "lat": lat,
            "lng": lng,
            "formatted_address": "موقع محدد عبر رابط خرائط جوجل",
            "is_from_url": True,
        }

    # التحقق ثانياً إن كان النص إحداثيات مباشرة (لا يتطلب مفتاح API)
    coords_from_text = extract_coordinates_from_text(address_text)
    if coords_from_text:
        lat, lng = coords_from_text
        return {
            "lat": lat,
            "lng": lng,
            "formatted_address": f"إحداثيات ({lat:.4f}, {lng:.4f})",
            "is_from_coords": True,
        }

    # التحقق من وجود مفتاح API للعناوين النصية الصرفة
    if not api_key:
        return None

    encoded_address = urllib.parse.quote(address_text)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}&language=ar&region={region}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Motaem-Voice-AI/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("status") == "OK" and data.get("results"):
            res = data["results"][0]
            loc = res["geometry"]["location"]
            return {
                "lat": loc["lat"],
                "lng": loc["lng"],
                "formatted_address": res.get("formatted_address", address_text),
                "place_id": res.get("place_id"),
                "types": res.get("types", []),
            }
        else:
            logger.warning(f"Google Geocoding failed for '{address_text}': status={data.get('status')}")
            return None
    except Exception as e:
        logger.error(f"Error calling Google Geocoding API: {e}")
        return None


def calculate_driving_distance_matrix(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    api_key: str = ""
) -> Optional[Dict[str, Any]]:
    """
    حساب مسافة القيادة ووقت الوصول: عبر Google Distance Matrix API عند توفر المفتاح،
    أو عبر مسافة هاڤرسين التقديرية (× 1.3) كبديل فوري آمن ومجاني.
    """
    if api_key:
        origins = f"{origin_lat},{origin_lng}"
        destinations = f"{dest_lat},{dest_lng}"
        url = (
            f"https://maps.googleapis.com/maps/api/distancematrix/json?"
            f"origins={origins}&destinations={destinations}&mode=driving&language=ar&key={api_key}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Motaem-Voice-AI/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("status") == "OK" and data.get("rows"):
                element = data["rows"][0]["elements"][0]
                if element.get("status") == "OK":
                    distance_meters = element["distance"]["value"]
                    duration_seconds = element["duration"]["value"]
                    return {
                        "distance_km": round(distance_meters / 1000.0, 2),
                        "duration_minutes": math.ceil(duration_seconds / 60.0),
                        "distance_text": element["distance"]["text"],
                        "duration_text": element["duration"]["text"],
                    }
        except Exception as e:
            logger.error(f"Error calling Google Distance Matrix API: {e}")

    # Fallback to Haversine if matrix fails or if no API key
    dist_straight = haversine_distance_km(origin_lat, origin_lng, dest_lat, dest_lng)
    # تقدير تقريبي للطريق: المسافة الفعلية = المسافة المستقيمة × 1.3
    est_driving_km = round(dist_straight * 1.3, 2)
    # سرعة متوسطة 30 كم/س في المدينة
    est_minutes = math.ceil((est_driving_km / 30.0) * 60)
    return {
        "distance_km": est_driving_km,
        "duration_minutes": max(5, est_minutes),
        "distance_text": f"{est_driving_km} كم تقريباً",
        "duration_text": f"{est_minutes} دقيقة تقريباً",
        "is_fallback": True,
    }


def resolve_smart_delivery_with_google(
    tenant,
    customer_address: str,
    branch_id: Optional[int] = None
) -> Tuple[Optional[Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    محرك الذكاء الجغرافي المتقدم لطلبات التوصيل (Google Maps + Geofencing + Dynamic Pricing):
    1. يستخرج مفتاح Google Maps (سواء كان خاصاً بالمنشأة أو عاماً للمنصة).
    2. يحول العنوان أو الرابط أو الإحداثيات إلى موقع جغرافي دقيق (Lat/Lng).
    3. يفحص مضلعات التغطية (Polygons) لجميع فروع المنشأة النشطة.
    4. يحسب مسافة القيادة الحقيقية ووقت الوصول اللحظي عبر Google Distance Matrix.
    5. يحسب رسوم التوصيل ديناميكياً (فتحة العداد + رسوم الكيلومتر الإضافي) بناءً على إعدادات المنصة.
    6. يعيد الفرع الأنسب ورسوم التوصيل والوقت الإجمالي (وقت الطريق + وقت المطبخ) مع نص صوتي جاهز للـ AI.
    """
    from core.models import Branch, PlatformConfiguration

    api_key = get_active_google_maps_key(tenant)

    # Geocode customer address (works with URLs/coordinates even without API key)
    geo = geocode_address(customer_address, api_key)
    if not geo:
        return None, None, None

    cust_lat = geo["lat"]
    cust_lng = geo["lng"]
    clean_addr_name = geo.get("formatted_address") or customer_address

    # 1. Enforce mandatory polygon rule: only branches with a drawn polygon (>=3 points) are delivery-enabled
    all_active_branches = list(Branch.objects.filter(tenant=tenant, status="active"))
    poly_branches = [
        b for b in all_active_branches
        if b.delivery_polygon and isinstance(b.delivery_polygon, list) and len(b.delivery_polygon) >= 3
    ]

    if not poly_branches:
        return None, None, {
            "ok": False,
            "covered": False,
            "is_system_error": False,
            "status": "no_polygons_configured",
            "suggested_action": "takeaway",
            "error": "خدمة التوصيل غير مفعلة لعدم اكتمال رسم زون التوصيل الجغرافي (المضلع) على الخريطة.",
            "ai_speech_response": "يا فندم خدمة التوصيل غير مفعلة حالياً لفروعنا لعدم اكتمال تحديد النطاق، لكن يشرفنا نجهز لحضرتك الطلب تستلمه بنفسك من الفرع (سفري). تحب نسجله استلام؟",
            "instruction_for_ai": "أبلغ العميل بلطف أن خدمة التوصيل غير متاحة واقترح عليه الاستلام من الفرع سفري."
        }

    cfg = PlatformConfiguration.get_solo()
    kitchen_prep_min = int(cfg.average_kitchen_prep_minutes)

    best_branch = None

    # 2. If branch_id was specified
    if branch_id is not None:
        target_b = next((b for b in all_active_branches if b.id == branch_id), None)
        in_target = (
            target_b is not None
            and target_b.delivery_polygon
            and isinstance(target_b.delivery_polygon, list)
            and len(target_b.delivery_polygon) >= 3
            and is_point_in_polygon(cust_lat, cust_lng, target_b.delivery_polygon)
        )

        if in_target:
            best_branch = target_b
        else:
            # Check if any OTHER branch covers this customer location
            other_matches = [
                b for b in poly_branches
                if b.id != branch_id and is_point_in_polygon(cust_lat, cust_lng, b.delivery_polygon)
            ]

            if other_matches:
                suggested_b = other_matches[0]
                target_name = target_b.name if target_b else "الفرع المطلوب"
                return None, None, {
                    "ok": False,
                    "is_system_error": False,
                    "status": "branch_switch_suggested",
                    "covered": True,
                    "requested_branch_id": target_b.id if target_b else branch_id,
                    "requested_branch_name": target_name,
                    "suggested_branch_id": suggested_b.id,
                    "suggested_branch_name": suggested_b.name,
                    "ai_speech_response": f"يا فندم عنوان حضرتك خارج نطاق زون توصيل «{target_name}»، لكنه مغطى بالكامل من خلال «{suggested_b.name}». تحب نحول طلبك لـ «{suggested_b.name}» ونكمله مع حضرتك؟",
                    "instruction_for_ai": f"أبلغ العميل بلطف أن عنوانه خارج تغطية «{target_name}» لكنه مغطى من «{suggested_b.name}»، واطلب موافقته الصريحة على تحويل الطلب لـ «{suggested_b.name}» ولا تنفذ الأوردر إلا بعد موافقته."
                }
            else:
                # STRICT GEOFENCE: Outside coverage completely!
                target_name = target_b.name if target_b else "فروعنا"
                return None, None, {
                    "ok": False,
                    "covered": False,
                    "is_system_error": False,
                    "status": "outside_coverage",
                    "suggested_action": "takeaway",
                    "error": f"العنوان المحدد «{clean_addr_name}» يقع خارج زون التوصيل الجغرافي المعتمد لـ {target_name}.",
                    "ai_speech_response": f"بعتذر لحضرتك جداً يا فندم، العنوان يقع خارج زون التوصيل المعتمد لفرعنا. نقدر نجهز لحضرتك الطلب تستلمه بنفسك من الفرع (سفري)، تحب نعمل كده؟",
                    "instruction_for_ai": "أبلغ العميل بلطف أن العنوان خارج زون التوصيل الجغرافي للفرع واقترح عليه الاستلام من الفرع سفري."
                }

    # 3. If branch_id was NOT specified: find which branch's polygon contains the customer
    if not best_branch:
        matches = [b for b in poly_branches if is_point_in_polygon(cust_lat, cust_lng, b.delivery_polygon)]
        if not matches:
            # STRICT GEOFENCE: Not in any branch's polygon!
            return None, None, {
                "ok": False,
                "covered": False,
                "is_system_error": False,
                "status": "outside_coverage",
                "suggested_action": "takeaway",
                "error": f"العنوان المحدد «{clean_addr_name}» يقع خارج زون التوصيل الجغرافي المعتمد لجميع فروعنا.",
                "ai_speech_response": "بعتذر لحضرتك جداً يا فندم، عنوانك خارج نطاق زون التوصيل المعتمد لفروعنا حالياً. نقدر نجهز لحضرتك الطلب تستلمه بنفسك من أقرب فرع (سفري)، تحب نعمل كده؟",
                "instruction_for_ai": "أبلغ العميل بلطف أن العنوان خارج زون التوصيل المعتمد واقترح عليه الاستلام من الفرع سفري."
            }
        elif len(matches) == 1:
            best_branch = matches[0]
        else:
            # Multiple polygons overlap: pick branch with closest distance
            min_dist = 999999.0
            for b in matches:
                matrix = calculate_driving_distance_matrix(
                    float(b.latitude or 0), float(b.longitude or 0),
                    cust_lat, cust_lng, api_key
                )
                if matrix and matrix["distance_km"] < min_dist:
                    min_dist = matrix["distance_km"]
                    best_branch = b

    # 4. Calculate driving distance & duration for the confirmed in-polygon branch
    matrix = calculate_driving_distance_matrix(
        float(best_branch.latitude or 0), float(best_branch.longitude or 0),
        cust_lat, cust_lng, api_key
    ) or {
        "distance_km": 3.0,
        "duration_minutes": 15,
        "distance_text": "3 كم",
        "duration_text": "15 دقيقة",
    }

    distance_km = matrix["distance_km"]
    driving_minutes = matrix["duration_minutes"]

    # 5. Delivery Pricing inside the Polygon (أولوية الكمبوند المحدد أولاً، ثم تسعير عداد المسافة للفرع)
    branch_areas = list(best_branch.delivery_areas.filter(is_active=True))
    matched_area_obj = None

    if branch_areas:
        # Check if address text matches a specific compound / area name
        norm_addr = customer_address.replace("،", " ").replace("-", " ")
        for a in branch_areas:
            # If area name is distinct (not generic like 'داخل الشروق' or 'نطاق الفرع') and in address
            if len(a.name) > 2 and (a.name in norm_addr or norm_addr in a.name):
                matched_area_obj = a
                break

    if matched_area_obj:
        delivery_fee = matched_area_obj.delivery_fee
        estimated_time_minutes = matched_area_obj.estimated_time_minutes
        area_name_display = matched_area_obj.name
        area_db_id = matched_area_obj.id
        notes_str = f"كمبوند معتمد: {matched_area_obj.name} (المسافة: {distance_km:.1f} كم - زمن الطريق: {driving_minutes} دقيقة)"
    else:
        # Dynamic distance-based formula from the branch itself!
        base_fee = float(best_branch.delivery_base_fee if best_branch.delivery_base_fee is not None else cfg.default_delivery_base_fee)
        base_km = float(best_branch.delivery_base_km if best_branch.delivery_base_km is not None else cfg.default_base_distance_km)
        per_km = float(best_branch.delivery_per_km_fee if best_branch.delivery_per_km_fee is not None else cfg.default_delivery_per_km_fee)

        if distance_km <= base_km:
            raw_fee = base_fee
        else:
            extra_km = distance_km - base_km
            raw_fee = base_fee + (extra_km * per_km)

        # Rule A2: Ceil rounding to whole integer
        delivery_fee = Decimal(str(math.ceil(raw_fee)))
        estimated_time_minutes = driving_minutes + kitchen_prep_min
        area_name_display = f"زون {best_branch.name}"
        area_db_id = None
        notes_str = f"تسعير ديناميكي بالمسافة: {distance_km:.1f} كم (الأساس: {base_fee:.0f} لأول {base_km:.0f} كم + {per_km:.0f}/كم)"

    cur_name = best_branch.get_currency_name_ar()
    cur_sym = best_branch.get_currency_symbol_ar()

    delivery_info = {
        "id": area_db_id,
        "name": area_name_display,
        "area_type": "داخل زون التوصيل",
        "delivery_fee": Decimal(str(delivery_fee)),
        "estimated_time_minutes": estimated_time_minutes,
        "distance_km": distance_km,
        "driving_minutes": driving_minutes,
        "is_google_resolved": True,
        "in_polygon": True,
        "latitude": cust_lat,
        "longitude": cust_lng,
        "notes": notes_str,
    }

    speech = (
        f"تمام يا فندم، عنوان حضرتك داخل زون توصيل «{best_branch.name}»، "
        f"ورسوم التوصيل {delivery_fee:.0f} {cur_name}، "
        f"ووقت الوصول المتوقع حوالي {estimated_time_minutes} دقيقة."
    )

    instruction = (
        f"أبلغ العميل بأن العنوان داخل زون التوصيل لـ «{best_branch.name}» ورسوم التوصيل {delivery_fee:.0f} {cur_name}، "
        f"ووقت الوصول حوالي {estimated_time_minutes} دقيقة كما في ai_speech_response."
    )

    result = {
        "ok": True,
        "covered": True,
        "branch_id": best_branch.id,
        "branch_name": best_branch.name,
        "currency": best_branch.currency,
        "currency_name": cur_name,
        "currency_symbol": cur_sym,
        "matched_area": delivery_info,
        "ai_speech_response": speech,
        "instruction_for_ai": instruction,
    }

    return best_branch, delivery_info, result
