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
    # إزالة أي نصوص إضافية والبحث عن نمط إحداثيين عشريين
    m = re.search(r'(-?\d{1,2}\.\d{4,}),\s*(-?\d{1,3}\.\d{4,})', text)
    if m:
        try:
            lat = float(m.group(1))
            lng = float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            pass
    return None


def geocode_address(address_text: str, api_key: str, region: str = "eg") -> Optional[Dict[str, Any]]:
    """
    تحويل العنوان النصي أو اسم المعلم إلى إحداثيات وبيانات دقيقة عبر Google Geocoding API.
    """
    if not api_key or not address_text:
        return None

    # التحقق أولاً إن كان النص رابطاً
    coords_from_url = extract_coordinates_from_url(address_text)
    if coords_from_url:
        lat, lng = coords_from_url
        return {
            "lat": lat,
            "lng": lng,
            "formatted_address": "موقع محدد عبر رابط خرائط جوجل",
            "is_from_url": True,
        }

    # التحقق ثانياً إن كان النص إحداثيات مباشرة
    coords_from_text = extract_coordinates_from_text(address_text)
    if coords_from_text:
        lat, lng = coords_from_text
        return {
            "lat": lat,
            "lng": lng,
            "formatted_address": f"إحداثيات ({lat:.4f}, {lng:.4f})",
            "is_from_coords": True,
        }

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
    api_key: str
) -> Optional[Dict[str, Any]]:
    """
    حساب مسافة القيادة الحقيقية ووقت الوصول اللحظي عبر Google Distance Matrix API.
    """
    if not api_key:
        return None

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

    # Fallback to Haversine if matrix fails
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
    if not api_key:
        return None, None, None

    # Geocode customer address
    geo = geocode_address(customer_address, api_key)
    if not geo:
        return None, None, None

    cust_lat = geo["lat"]
    cust_lng = geo["lng"]
    clean_addr_name = geo.get("formatted_address") or customer_address

    # Fetch candidate branches
    if branch_id is not None:
        branches = list(Branch.objects.filter(tenant=tenant, id=branch_id, status="active"))
    else:
        branches = list(Branch.objects.filter(tenant=tenant, status="active"))

    if not branches:
        return None, None, None

    cfg = PlatformConfiguration.get_solo()
    base_fee = float(cfg.default_delivery_base_fee)
    base_km = float(cfg.default_base_distance_km)
    per_km_fee = float(cfg.default_delivery_per_km_fee)
    max_radius_km = float(cfg.max_delivery_radius_km)
    kitchen_prep_min = int(cfg.average_kitchen_prep_minutes)

    best_branch = None
    best_matrix = None
    in_polygon_match = False

    # 1. First check: Point in polygon for any branch
    for b in branches:
        if b.latitude and b.longitude and b.delivery_polygon:
            if is_point_in_polygon(cust_lat, cust_lng, b.delivery_polygon):
                matrix = calculate_driving_distance_matrix(
                    float(b.latitude), float(b.longitude),
                    cust_lat, cust_lng, api_key
                )
                best_branch = b
                best_matrix = matrix
                in_polygon_match = True
                break

    # 2. If not in any explicit polygon, find closest active branch by driving distance
    if not best_branch:
        min_distance = 999999.0
        for b in branches:
            if b.latitude and b.longitude:
                matrix = calculate_driving_distance_matrix(
                    float(b.latitude), float(b.longitude),
                    cust_lat, cust_lng, api_key
                )
                if matrix and matrix["distance_km"] < min_distance:
                    min_distance = matrix["distance_km"]
                    best_branch = b
                    best_matrix = matrix

    if not best_branch or not best_matrix:
        return None, None, None

    distance_km = best_matrix["distance_km"]
    driving_minutes = best_matrix["duration_minutes"]
    branch_radius = float(best_branch.delivery_radius_km or max_radius_km)
    effective_max_km = max(branch_radius, max_radius_km)

    # Check coverage limit
    if not in_polygon_match and distance_km > effective_max_km:
        return None, None, {
            "ok": False,
            "covered": False,
            "is_system_error": False,
            "error": f"الموقع يبعد {distance_km:.1f} كم وهو خارج النطاق الأقصى للتوصيل ({effective_max_km:.0f} كم).",
            "distance_km": distance_km,
            "suggested_action": "takeaway",
            "ai_speech_response": f"بعتذر لحضرتك يا فندم، العنوان يبعد حوالي {distance_km:.0f} كم وهو خارج نطاق التوصيل لفروعنا حالياً. نقدر نجهز لحضرتك الطلب تستلمه سفري من أقرب فرع، تحب نسجله استلام؟",
            "instruction_for_ai": "أبلغ العميل بلطف أن المسافة خارج نطاق التوصيل واقترح عليه الاستلام من الفرع."
        }

    # Calculate dynamic fee
    if distance_km <= base_km:
        delivery_fee = base_fee
    else:
        extra_km = distance_km - base_km
        delivery_fee = base_fee + (extra_km * per_km_fee)

    delivery_fee = round(delivery_fee, 2)
    total_est_minutes = driving_minutes + kitchen_prep_min

    cur_name = best_branch.get_currency_name_ar()
    cur_sym = best_branch.get_currency_symbol_ar()

    delivery_info = {
        "id": None,
        "name": clean_addr_name,
        "area_type": "توصيل ذكي (خرائط جوجل)",
        "delivery_fee": Decimal(str(delivery_fee)),
        "estimated_time_minutes": total_est_minutes,
        "distance_km": distance_km,
        "driving_minutes": driving_minutes,
        "is_google_resolved": True,
        "latitude": cust_lat,
        "longitude": cust_lng,
        "notes": f"المسافة بالقيادة: {distance_km:.1f} كم - زمن الطريق: {driving_minutes} دقيقة",
    }

    speech = (
        f"تمام يا فندم، تم تحديد موقعك «{clean_addr_name}» والتوصيل متاح من {best_branch.name} "
        f"(يبعد {distance_km:.1f} كم)، رسوم التوصيل {delivery_fee:.0f} {cur_name}، "
        f"ووقت الوصول المتوقع بالتحضير حوالي {total_est_minutes} دقيقة."
    )

    instruction = (
        f"أبلغ العميل بأن العنوان مغطى من {best_branch.name} ورسوم التوصيل {delivery_fee:.0f} {cur_name}، "
        f"ووقت الوصول حوالي {total_est_minutes} دقيقة كما في ai_speech_response."
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
