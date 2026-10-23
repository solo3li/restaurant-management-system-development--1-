import json
import logging
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, F, Q
from django.core.cache import cache

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import user_has_perm, _get_client_ip
from apps.menu.models import MenuItem, MenuCategory, MenuItemVariant, BranchMenuAvailability, BranchVariantPrice
from apps.tenants.models import Tenant, Branch, DeliveryArea
from apps.orders.models import Order, OrderItem, Customer
from apps.audit.models import log_audit_event
from apps.kitchen.events import notify_kitchen_order_event

logger = logging.getLogger(__name__)

def branch_menu_view(request):
    if not (
        user_has_perm(request.user, "manage_menu") or
        user_has_perm(request.user, "menu_view") or
        user_has_perm(request.user, "menu_toggle_availability") or
        user_has_perm(request.user, "menu_edit_item")
    ):
        return HttpResponseForbidden("غير مصرح لك باستعراض أو إدارة قائمة الطعام")

    tenant = get_active_tenant(request)
    branch = get_active_branch(request)

    profile = getattr(request.user, "profile", None)
    can_manage_menu = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin)) or user_has_perm(request.user, "manage_menu") or user_has_perm(request.user, "menu_create_item")

    # Dynamic Categories from MenuCategory
    cat_objs = list(MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id"))
    category_names = ["الكل"] + [c.name for c in cat_objs]
    cat_filter = request.GET.get("cat", "الكل")
    search = request.GET.get("q", "").strip()

    menu_qs = MenuItem.objects.filter(tenant=tenant, is_active=True).prefetch_related("variants").order_by("category", "name")
    if cat_filter != "الكل":
        menu_qs = menu_qs.filter(category=cat_filter)
    if search:
        menu_qs = menu_qs.filter(name__icontains=search)

    branch_avail_map = {}
    branch_price_map = {}
    branch_variant_price_map = {}
    if branch:
        for av in BranchMenuAvailability.objects.filter(branch=branch):
            branch_avail_map[av.menu_item_id] = av.is_available
            branch_price_map[av.menu_item_id] = av.custom_price
        for vp in BranchVariantPrice.objects.filter(branch=branch):
            branch_variant_price_map[vp.variant_id] = vp.custom_price

    items_data = []
    for item in menu_qs:
        if branch:
            is_avail = branch_avail_map.get(item.id, item.available)
            custom_price = branch_price_map.get(item.id)
            effective_price = custom_price if custom_price is not None else item.price
            variants_list = []
            for v in item.variants.all():
                v_custom = branch_variant_price_map.get(v.id)
                variants_list.append({
                    "id": v.id,
                    "name": v.name,
                    "name_en": v.name_en,
                    "default_price": v.price,
                    "custom_price": v_custom,
                    "effective_price": v_custom if v_custom is not None else v.price,
                })
        else:
            is_avail = item.available
            custom_price = None
            effective_price = item.price
            variants_list = [{
                "id": v.id,
                "name": v.name,
                "name_en": v.name_en,
                "default_price": v.price,
                "custom_price": None,
                "effective_price": v.price,
            } for v in item.variants.all()]

        items_data.append({
            "item": item,
            "is_available": is_avail,
            "custom_price": custom_price,
            "effective_price": effective_price,
            "effective_min_price": item.get_min_price_for_branch(branch) if branch else item.min_price,
            "variants_data": variants_list,
            "variants": list(item.variants.all()),
        })

    currency_sym = branch.get_currency_symbol_ar() if branch else (tenant.get_currency_symbol_ar() if tenant else "ر.س")

    context = {
        "tenant": tenant,
        "branch": branch,
        "branches": Branch.objects.filter(tenant=tenant, status="active"),
        "items_data": items_data,
        "categories": category_names,
        "category_objs": cat_objs,
        "selected_cat": cat_filter,
        "search_query": search,
        "can_manage_menu": can_manage_menu,
        "branch_currency_symbol": currency_sym,
    }
    return render(request, "branch_menu.html", context)


# ==========================================
# 6. OPERATIONAL SCREENS
# ==========================================

@login_required
@ensure_csrf_cookie


def api_toggle_branch_menu(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_toggle_availability") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بتعديل توفر الأصناف في الفرع"}, status=403)

    branch = get_active_branch(request)
    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)

    if branch:
        avail, _ = BranchMenuAvailability.objects.get_or_create(
            branch=branch,
            menu_item=item,
            defaults={"is_available": item.available}
        )
        avail.is_available = not avail.is_available
        avail.save()
        return JsonResponse({"ok": True, "isAvailable": avail.is_available, "itemName": item.name, "branch": branch.name})
    else:
        if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
            return JsonResponse({"error": "تعطيل الصنف عن كافة الفروع يتطلب صلاحية إدارة المنيو الشاملة أو صفة المالك"}, status=403)
        item.available = not item.available
        item.save()
        return JsonResponse({"ok": True, "isAvailable": item.available, "itemName": item.name, "branch": "كل الفروع"})


@login_required
def api_update_branch_item_price(request, branch_id, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (
        user_has_perm(request.user, "manage_menu") or
        user_has_perm(request.user, "menu_edit_item") or
        user_has_perm(request.user, "manage_branches")
    ):
        return JsonResponse({"error": "غير مصرح لك بتعديل أسعار الأصناف في هذا الفرع"}, status=403)

    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    raw_price = data.get("custom_price")
    custom_price = None
    if raw_price is not None and str(raw_price).strip() != "":
        try:
            custom_price = max(Decimal("0.00"), Decimal(str(raw_price)))
        except Exception:
            return JsonResponse({"error": "قيمة السعر غير صحيحة"}, status=400)

    avail, _ = BranchMenuAvailability.objects.get_or_create(
        branch=branch,
        menu_item=item,
        defaults={"is_available": item.available}
    )
    avail.custom_price = custom_price
    avail.save(update_fields=["custom_price"])

    variants_data = data.get("variants") or []
    if isinstance(variants_data, list):
        for v_item in variants_data:
            v_id = v_item.get("variant_id")
            v_raw = v_item.get("custom_price")
            variant = item.variants.filter(id=v_id).first()
            if variant:
                v_price = None
                if v_raw is not None and str(v_raw).strip() != "":
                    try:
                        v_price = max(Decimal("0.00"), Decimal(str(v_raw)))
                    except Exception:
                        pass
                vp, _ = BranchVariantPrice.objects.get_or_create(
                    branch=branch,
                    variant=variant,
                    defaults={"is_available": True}
                )
                vp.custom_price = v_price
                vp.save(update_fields=["custom_price"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="branch_item_price_updated",
        target_model="MenuItem",
        target_id=item.id,
        description=f"تعديل سعر الصنف «{item.name}» في فرع «{branch.name}» إلى {custom_price if custom_price is not None else 'السعر الافتراضي'} {branch.get_currency_symbol_ar()}",
        ip_address=_get_client_ip(request),
    )

    effective_price = item.get_price_for_branch(branch)
    effective_min_price = item.get_min_price_for_branch(branch)
    return JsonResponse({
        "ok": True,
        "item_id": item.id,
        "branch_id": branch.id,
        "custom_price": float(custom_price) if custom_price is not None else None,
        "effective_price": float(effective_price),
        "effective_min_price": float(effective_min_price),
        "currency_symbol": branch.get_currency_symbol_ar(),
        "message": f"تم تحديث سعر «{item.name}» لفرع «{branch.name}» بنجاح."
    })


@login_required
def api_get_item_branch_prices(request, item_id):
    tenant = get_active_tenant(request)
    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    branches = Branch.objects.filter(tenant=tenant, status="active").order_by("id")

    b_avails = {av.branch_id: av for av in BranchMenuAvailability.objects.filter(menu_item=item)}
    b_v_prices = {}
    for vp in BranchVariantPrice.objects.filter(variant__menu_item=item):
        b_v_prices.setdefault(vp.branch_id, {})[vp.variant_id] = vp.custom_price

    branches_data = []
    item_variants = list(item.variants.all())

    for b in branches:
        av = b_avails.get(b.id)
        c_price = av.custom_price if av else None
        eff_price = c_price if c_price is not None else item.price

        v_list = []
        for v in item_variants:
            v_custom = b_v_prices.get(b.id, {}).get(v.id)
            v_eff = v_custom if v_custom is not None else v.price
            v_list.append({
                "variant_id": v.id,
                "name": v.name,
                "default_price": float(v.price),
                "custom_price": float(v_custom) if v_custom is not None else None,
                "effective_price": float(v_eff),
            })

        branches_data.append({
            "branch_id": b.id,
            "branch_name": b.name,
            "currency": b.currency,
            "currency_symbol": b.get_currency_symbol_ar(),
            "currency_name": b.get_currency_name_ar(),
            "custom_price": float(c_price) if c_price is not None else None,
            "effective_price": float(eff_price),
            "is_available": av.is_available if av else item.available,
            "variants": v_list,
        })

    return JsonResponse({
        "ok": True,
        "item": {
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "default_price": float(item.price),
            "has_variants": item.has_variants,
            "tenant_currency": tenant.default_currency if tenant else "SAR",
            "tenant_currency_symbol": tenant.get_currency_symbol_ar() if tenant else "ر.س",
        },
        "branches": branches_data,
    })


@login_required
def api_update_item_branch_prices(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بتعديل أسعار الفروع المجمعة"}, status=403)

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    branches_data = data.get("branches") or []
    updated_count = 0

    for b_entry in branches_data:
        b_id = b_entry.get("branch_id")
        branch = Branch.objects.filter(tenant=tenant, id=b_id).first()
        if not branch:
            continue

        raw_price = b_entry.get("custom_price")
        custom_price = None
        if raw_price is not None and str(raw_price).strip() != "":
            try:
                custom_price = max(Decimal("0.00"), Decimal(str(raw_price)))
            except Exception:
                pass

        avail, _ = BranchMenuAvailability.objects.get_or_create(
            branch=branch,
            menu_item=item,
            defaults={"is_available": item.available}
        )
        avail.custom_price = custom_price
        avail.save(update_fields=["custom_price"])
        updated_count += 1

        v_entries = b_entry.get("variants") or []
        for ve in v_entries:
            v_id = ve.get("variant_id")
            v_raw = ve.get("custom_price")
            variant = item.variants.filter(id=v_id).first()
            if variant:
                v_price = None
                if v_raw is not None and str(v_raw).strip() != "":
                    try:
                        v_price = max(Decimal("0.00"), Decimal(str(v_raw)))
                    except Exception:
                        pass
                vp, _ = BranchVariantPrice.objects.get_or_create(
                    branch=branch,
                    variant=variant,
                    defaults={"is_available": True}
                )
                vp.custom_price = v_price
                vp.save(update_fields=["custom_price"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="item_branch_prices_bulk_updated",
        target_model="MenuItem",
        target_id=item.id,
        description=f"تحديث أسعار الصنف «{item.name}» المخصصة لـ {updated_count} فروع",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "message": f"تم تحديث أسعار الصنف «{item.name}» لـ {updated_count} فروع بنجاح.",
        "updated_count": updated_count
    })


@login_required



@login_required
def api_toggle_menu_item(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "تعطيل أو تفعيل الصنف عن كامل المطعم مقتصر على إدارة المنيو العامة أو المالك"}, status=403)

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    item.available = not item.available
    item.save()
    return JsonResponse({"ok": True, "available": item.available})


@login_required
def api_create_menu_item(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_create_item") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بإضافة أصناف جديدة للمنيو"}, status=403)

    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    if is_multipart:
        data = request.POST
    else:
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else request.POST
        except Exception:
            data = request.POST

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم الصنف مطلوب"}, status=400)

    category_id = data.get("category_id")
    category_name = str(data.get("category", "")).strip()
    cat_obj = None
    if category_id:
        cat_obj = MenuCategory.objects.filter(tenant=tenant, id=category_id).first()
        if cat_obj:
            category_name = cat_obj.name
    elif category_name:
        cat_obj = MenuCategory.objects.filter(tenant=tenant, name__iexact=category_name).first()
        if not cat_obj:
            cat_obj = MenuCategory.objects.create(tenant=tenant, name=category_name)

    if not category_name:
        category_name = "أطباق رئيسية"

    price = Decimal(str(data.get("price") or 0))
    cost = Decimal(str(data.get("cost") or 0))
    description = str(data.get("description", "")).strip()
    name_en = str(data.get("name_en", "")).strip()
    description_en = str(data.get("description_en", "")).strip()
    emoji = str(data.get("emoji", "🍽️")).strip()

    # Parse Variants (Sizes) if provided
    variants_raw = data.get("variants")
    variants_list = []
    if variants_raw:
        if isinstance(variants_raw, str):
            try:
                variants_list = json.loads(variants_raw)
            except Exception:
                variants_list = []
        elif isinstance(variants_raw, list):
            variants_list = variants_raw

    has_variants = bool(variants_list)
    if has_variants:
        valid_prices = [Decimal(str(v.get("price", 0))) for v in variants_list if float(v.get("price", 0)) > 0]
        if valid_prices:
            price = min(valid_prices)

    if not has_variants and price <= 0:
        return JsonResponse({"error": "يرجى تحديد سعر صالح للصنف"}, status=400)

    item = MenuItem.objects.create(
        tenant=tenant,
        name=name,
        name_en=name_en,
        description=description,
        description_en=description_en,
        category=category_name,
        category_rel=cat_obj,
        price=price,
        cost=cost,
        emoji=emoji,
        available=True,
        has_variants=has_variants,
        is_active=True,
    )

    if "image" in request.FILES:
        item.image = request.FILES["image"]
        item.save(update_fields=["image"])

    # Create variant sizes
    has_any_default = any(bool(v.get("is_default")) for v in variants_list)
    for idx, v in enumerate(variants_list):
        v_name = str(v.get("name", "")).strip()
        v_name_en = str(v.get("name_en", "")).strip()
        v_price = Decimal(str(v.get("price", 0)))
        v_cost = Decimal(str(v.get("cost", 0)))
        is_def = bool(v.get("is_default")) if has_any_default else (idx == 0)
        if v_name and v_price > 0:
            MenuItemVariant.objects.create(
                menu_item=item,
                name=v_name,
                name_en=v_name_en,
                price=v_price,
                cost=v_cost,
                is_default=is_def,
                ordering=(idx + 1) * 10,
            )

    price_scope = request.POST.get("price_scope", "all")
    branch_id = request.POST.get("branch_id")
    target_branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else None

    for b in Branch.objects.filter(tenant=tenant):
        c_price = price if (price_scope == "branch" and target_branch and b == target_branch) else None
        BranchMenuAvailability.objects.get_or_create(branch=b, menu_item=item, defaults={"is_available": True, "custom_price": c_price})

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="menu_item_created",
        target_model="MenuItem",
        target_id=item.id,
        description=f"إضافة الصنف «{item.name}» إلى قائمة الطعام (السعر: {item.price} ر.س، القسم: {item.category})",
        ip_address=_get_client_ip(request),
    )

    return JsonResponse({
        "status": "success",
        "id": item.id,
        "name": item.name,
        "price": float(item.price),
        "category": item.category,
        "image_url": item.image.url if item.image else "",
    }, status=201)


@login_required
def api_update_menu_item(request, item_id):
    if request.method not in ["POST", "PUT", "PATCH"]:
        return HttpResponseBadRequest("POST/PUT required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)

    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    if is_multipart:
        data = request.POST
    else:
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else request.POST
        except Exception:
            data = request.POST

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_edit_item") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بتعديل بيانات أصناف المنيو"}, status=403)

    if "name" in data and str(data["name"]).strip():
        item.name = str(data["name"]).strip()

    if "name_en" in data:
        item.name_en = str(data["name_en"]).strip()

    if "description" in data:
        item.description = str(data["description"]).strip()

    if "description_en" in data:
        item.description_en = str(data["description_en"]).strip()

    if "category_id" in data and data["category_id"]:
        cat = MenuCategory.objects.filter(tenant=tenant, id=data["category_id"]).first()
        if cat:
            item.category_rel = cat
            item.category = cat.name
    elif "category" in data and str(data["category"]).strip():
        item.category = str(data["category"]).strip()
        cat = MenuCategory.objects.filter(tenant=tenant, name__iexact=item.category).first()
        if cat:
            item.category_rel = cat

    if "cost" in data:
        item.cost = Decimal(str(data["cost"] or 0))

    if "emoji" in data:
        item.emoji = str(data["emoji"])

    if "image" in request.FILES:
        item.image = request.FILES["image"]

    # Handle pricing scope: branch-specific vs all branches (master)
    price_scope = data.get("price_scope", "all")
    branch_id = data.get("branch_id")
    target_branch = Branch.objects.filter(tenant=tenant, id=branch_id).first() if branch_id else None

    # Handle variants if provided
    variants_raw = data.get("variants")
    variants_list = []
    if variants_raw:
        if isinstance(variants_raw, str):
            try:
                variants_list = json.loads(variants_raw)
            except Exception:
                variants_list = []
        elif isinstance(variants_raw, list):
            variants_list = variants_raw

    if price_scope == "branch" and target_branch:
        # 1. Save core item details without touching master item.price
        item.save()

        # 2. Update BranchMenuAvailability.custom_price for single-price items
        if not item.has_variants and "price" in data:
            raw_p = data.get("price")
            b_custom_price = None
            if raw_p is not None and str(raw_p).strip() != "":
                try:
                    b_custom_price = max(Decimal("0.00"), Decimal(str(raw_p)))
                except Exception:
                    pass
            avail, _ = BranchMenuAvailability.objects.get_or_create(
                branch=target_branch,
                menu_item=item,
                defaults={"is_available": item.available}
            )
            avail.custom_price = b_custom_price
            avail.save(update_fields=["custom_price"])

        # 3. If item has variants, update BranchVariantPrice for target_branch
        if item.has_variants and variants_list:
            for v_entry in variants_list:
                v_id = v_entry.get("id")
                v_price = v_entry.get("price")
                if v_id and v_price is not None:
                    var_obj = item.variants.filter(id=v_id).first()
                    if var_obj:
                        try:
                            vp_price = max(Decimal("0.00"), Decimal(str(v_price)))
                            vp, _ = BranchVariantPrice.objects.get_or_create(
                                branch=target_branch,
                                variant=var_obj,
                                defaults={"is_available": True}
                            )
                            vp.custom_price = vp_price
                            vp.save(update_fields=["custom_price"])
                        except Exception:
                            pass

        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="branch_item_price_updated",
            target_model="MenuItem",
            target_id=item.id,
            description=f"تخصيص سعر الصنف «{item.name}» في فرع «{target_branch.name}» فقط إلى {data.get('price')} {target_branch.get_currency_symbol_ar()}",
            ip_address=_get_client_ip(request),
        )

        effective_price = item.get_price_for_branch(target_branch)
        return JsonResponse({
            "ok": True,
            "status": "success",
            "id": item.id,
            "name": item.name,
            "price": float(effective_price),
            "master_price": float(item.price),
            "price_scope": "branch",
            "branch_id": target_branch.id,
            "category": item.category,
            "image_url": item.image.url if item.image else "",
        })
    else:
        # price_scope == "all": Master price update for all branches
        if "variants" in data:
            if variants_list:
                item.has_variants = True
                item.variants.all().delete()
                has_any_default = any(bool(v.get("is_default")) for v in variants_list)
                for idx, v in enumerate(variants_list):
                    v_name = str(v.get("name", "")).strip()
                    v_name_en = str(v.get("name_en", "")).strip()
                    v_price = Decimal(str(v.get("price", 0)))
                    v_cost = Decimal(str(v.get("cost", 0)))
                    is_def = bool(v.get("is_default")) if has_any_default else (idx == 0)
                    if v_name and v_price > 0:
                        MenuItemVariant.objects.create(
                            menu_item=item,
                            name=v_name,
                            name_en=v_name_en,
                            price=v_price,
                            cost=v_cost,
                            is_default=is_def,
                            ordering=(idx + 1) * 10,
                        )
                valid_prices = [Decimal(str(v.get("price", 0))) for v in variants_list if float(v.get("price", 0)) > 0]
                if valid_prices:
                    item.price = min(valid_prices)
            else:
                item.has_variants = False
                item.variants.all().delete()
                if "price" in data:
                    item.price = Decimal(str(data["price"] or 0))
        elif "price" in data:
            new_price = Decimal(str(data["price"] or 0))
            if new_price > 0:
                item.price = new_price

        item.save()

        # If user explicitly updated all branches from a branch view, clear that branch's custom override
        if target_branch:
            BranchMenuAvailability.objects.filter(branch=target_branch, menu_item=item).update(custom_price=None)
            for v_obj in item.variants.all():
                BranchVariantPrice.objects.filter(branch=target_branch, variant=v_obj).update(custom_price=None)

        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="menu_item_updated",
            target_model="MenuItem",
            target_id=item.id,
            description=f"تحديث السعر العام للصنف «{item.name}» لجميع الفروع إلى {item.price} {tenant.get_currency_symbol_ar() if tenant else 'ر.س'}",
            ip_address=_get_client_ip(request),
        )

        return JsonResponse({
            "ok": True,
            "status": "success",
            "id": item.id,
            "name": item.name,
            "price": float(item.price),
            "price_scope": "all",
            "category": item.category,
            "image_url": item.image.url if item.image else "",
        })


@login_required
def api_delete_menu_item(request, item_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST/DELETE required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if not is_owner_or_super and not (user_has_perm(request.user, "menu_delete_item") or user_has_perm(request.user, "manage_menu")):
        return JsonResponse({"error": "غير مصرح لك بحذف أصناف من المنيو"}, status=403)

    item = get_object_or_404(MenuItem, tenant=tenant, id=item_id)
    item_name = item.name
    item_id_val = item.id
    item_price = item.price

    # Safe Soft Delete
    item.is_active = False
    item.available = False
    item.save(update_fields=["is_active", "available"])

    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="menu_item_deleted",
        target_model="MenuItem",
        target_id=item_id_val,
        description=f"أرشفة/حذف الصنف «{item_name}» من قائمة الطعام (السعر: {item_price} ر.س)",
        ip_address=_get_client_ip(request),
    )
    return JsonResponse({"ok": True, "message": f"تم حذف الصنف «{item_name}» بنجاح"})


# ----------------------------------------------------
# Dynamic Category Management APIs
# ----------------------------------------------------

@login_required
def api_list_categories(request):
    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "منشأة غير موجودة"}, status=400)
    cats = MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id")
    data = []
    for c in cats:
        data.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "ordering": c.ordering,
            "image_url": c.image.url if c.image else "",
            "items_count": c.items.filter(is_active=True).count(),
        })
    return JsonResponse({"ok": True, "categories": data})


@login_required
def api_create_category(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بإضافة تصنيفات"}, status=403)

    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    data = request.POST if is_multipart else (json.loads(request.body.decode("utf-8")) if request.body else request.POST)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم التصنيف مطلوب"}, status=400)

    ordering = int(data.get("ordering", 10) or 10)
    existing_cat = MenuCategory.objects.filter(tenant=tenant, name=name).first()
    if existing_cat:
        if existing_cat.is_active:
            return JsonResponse({"error": "يوجد قسم نشط بهذا الاسم مسبقاً"}, status=400)
        else:
            cat = existing_cat
            cat.is_active = True
            cat.ordering = ordering
    else:
        cat = MenuCategory.objects.create(
            tenant=tenant,
            name=name,
            ordering=ordering,
            is_active=True
        )

    if "description" in data:
        cat.description = str(data["description"]).strip()

    if "name_en" in data:
        cat.name_en = str(data["name_en"]).strip()

    if "description_en" in data:
        cat.description_en = str(data["description_en"]).strip()

    if "image" in request.FILES:
        cat.image = request.FILES["image"]

    cat.save()
    return JsonResponse({
        "status": "success",
        "id": cat.id,
        "name": cat.name,
        "name_en": cat.name_en,
        "ordering": cat.ordering,
        "image_url": cat.image.url if cat.image else "",
    }, status=201)


@login_required
def api_update_category(request, cat_id):
    if request.method not in ["POST", "PUT", "PATCH"]:
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بتعديل التصنيفات"}, status=403)

    cat = get_object_or_404(MenuCategory, tenant=tenant, id=cat_id)
    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    data = request.POST if is_multipart else (json.loads(request.body.decode("utf-8")) if request.body else request.POST)

    if "name" in data and str(data["name"]).strip():
        new_name = str(data["name"]).strip()
        if MenuCategory.objects.filter(tenant=tenant, name=new_name).exclude(id=cat.id).exists():
            return JsonResponse({"error": "يوجد قسم آخر بنفس هذا الاسم مسبقاً"}, status=400)
        old_name = cat.name
        cat.name = new_name
        MenuItem.objects.filter(tenant=tenant, category=old_name).update(category=cat.name)

    if "name_en" in data:
        cat.name_en = str(data["name_en"]).strip()

    if "description" in data:
        cat.description = str(data["description"]).strip()

    if "description_en" in data:
        cat.description_en = str(data["description_en"]).strip()

    if "ordering" in data:
        cat.ordering = int(data["ordering"] or 10)

    if "image" in request.FILES:
        cat.image = request.FILES["image"]

    cat.save()
    return JsonResponse({
        "status": "success",
        "id": cat.id,
        "name": cat.name,
        "ordering": cat.ordering,
        "image_url": cat.image.url if cat.image else "",
    })


@login_required
def api_delete_category(request, cat_id):
    if request.method not in ["POST", "DELETE"]:
        return HttpResponseBadRequest("POST/DELETE required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner_or_super and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بحذف التصنيفات"}, status=403)

    cat = get_object_or_404(MenuCategory, tenant=tenant, id=cat_id)
    cat_name = cat.name
    cat.is_active = False
    cat.save(update_fields=["is_active"])
    return JsonResponse({"status": "success", "message": f"تم حذف التصنيف «{cat_name}» بنجاح"})



def digital_menu_view(request, slug=None, branch_id=None):
    """
    Public digital menu view for customers.
    Accessed via /m/<slug>/ or /m/<slug>/branch/<branch_id>/ or custom domain.
    """
    tenant = None
    if slug:
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
    elif getattr(request, "custom_domain_tenant", None):
        tenant = request.custom_domain_tenant
    else:
        return HttpResponseNotFound("لم يتم العثور على قائمة طعام المطعم")

    # Determine active language for digital menu
    active_lang = None
    if hasattr(request, "LANGUAGE_CODE") and request.LANGUAGE_CODE:
        active_lang = request.LANGUAGE_CODE
    elif hasattr(request, "session") and request.session.get("django_language"):
        active_lang = request.session.get("django_language")
    elif request.COOKIES.get("django_language"):
        active_lang = request.COOKIES.get("django_language")
    else:
        active_lang = translation.get_language() or "ar"

    if "-" in active_lang:
        active_lang = active_lang.split("-")[0]
    if active_lang not in ["ar", "en"]:
        active_lang = "ar"

    branches = list(Branch.objects.filter(tenant=tenant, status="active").order_by("id"))
    for b in branches:
        b.display_name = b.get_display_name(active_lang)

    if not branches:
        # Fallback to any branches configured for this restaurant so menu items remain browsable
        all_branches = list(Branch.objects.filter(tenant=tenant).order_by("id"))
        if all_branches:
            branches = all_branches
            for b in branches:
                b.display_name = b.get_display_name(active_lang)

    if not branches:
        return render(request, "qr_menu.html", {
            "tenant": tenant,
            "branches": [],
            "selected_branch": None,
            "no_branches": True,
            "categories": [],
            "categorized_items": {},
            "CURRENT_LANG": active_lang,
            "DIR": "rtl" if active_lang == "ar" else "ltr",
            "IS_RTL": active_lang == "ar",
        })

    # Determine selected branch
    selected_branch = None
    if branch_id:
        selected_branch = next((b for b in branches if b.id == branch_id), None)
    if not selected_branch:
        req_bid = request.GET.get("branch")
        if req_bid and str(req_bid).isdigit():
            selected_branch = next((b for b in branches if b.id == int(req_bid)), None)
    if not selected_branch:
        selected_branch = branches[0]

    selected_branch.display_name = selected_branch.get_display_name(active_lang)

    # Disabled items in this branch
    disabled_ids = set(
        BranchMenuAvailability.objects.filter(
            branch=selected_branch, is_available=False
        ).values_list("menu_item_id", flat=True)
    )

    # Dynamic Categories
    cat_objs = list(MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id"))
    categories_data = []
    cat_id_to_display = {}
    for c in cat_objs:
        disp_name = c.get_display_name(active_lang)
        cat_id_to_display[c.id] = disp_name
        categories_data.append({
            "id": c.id,
            "name": disp_name,
            "raw_name": c.name,
            "name_en": c.name_en,
            "image_url": c.image.url if c.image else "",
        })

    # Categories and items
    raw_items = MenuItem.objects.filter(tenant=tenant, is_active=True).prefetch_related("variants").order_by("category", "name")
    categories_set = [c["name"] for c in categories_data]
    categorized_items = {}

    for item in raw_items:
        if item.category_rel and item.category_rel.id in cat_id_to_display:
            cat = cat_id_to_display[item.category_rel.id]
        else:
            cat = item.category or ("General Dishes" if active_lang == "en" else "أطباق عامة")

        if cat not in categorized_items:
            categorized_items[cat] = []
            if cat not in categories_set:
                categories_set.append(cat)
                categories_data.append({
                    "id": None,
                    "name": cat,
                    "raw_name": item.category or cat,
                    "name_en": "",
                    "image_url": "",
                })

        is_avail = item.available and (item.id not in disabled_ids)
        item_variants = []
        for v in item.variants.all():
            v_eff_price = v.get_price_for_branch(selected_branch)
            item_variants.append({
                "id": v.id,
                "name": v.get_display_name(active_lang),
                "raw_name": v.name,
                "name_en": v.name_en,
                "price": float(v_eff_price),
                "is_default": v.is_default,
            })

        eff_price = item.get_price_for_branch(selected_branch)
        eff_min_price = item.get_min_price_for_branch(selected_branch)

        categorized_items[cat].append({
            "id": item.id,
            "name": item.get_display_name(active_lang),
            "raw_name": item.name,
            "name_en": item.name_en,
            "description": item.get_display_description(active_lang),
            "description_en": item.description_en,
            "price": float(eff_price),
            "min_price": float(eff_min_price),
            "has_variants": item.has_variants and len(item_variants) > 0,
            "variants": item_variants,
            "emoji": item.emoji or "🍽️",
            "image_url": item.image.url if item.image else "",
            "is_available": is_avail,
            "category": cat,
        })

    # Prepare sections list matching category_objs
    sections = []
    for c in categories_data:
        c_items = categorized_items.get(c["name"], [])
        if c_items:
            sections.append({
                "id": c["id"],
                "name": c["name"],
                "image_url": c["image_url"],
                "items": c_items,
            })

    # Delivery areas for selected branch
    areas = []
    for a in DeliveryArea.objects.filter(branch=selected_branch, is_active=True).order_by("delivery_fee", "name"):
        est_time = f"{a.estimated_time_minutes} min" if active_lang == "en" else f"{a.estimated_time_minutes} دقيقة"
        if not a.estimated_time_minutes:
            est_time = "30-45 min" if active_lang == "en" else "30-45 دقيقة"
        areas.append({
            "id": a.id,
            "name": a.name,
            "fee": float(a.delivery_fee or 0),
            "estimated_time": est_time,
        })

    is_open = selected_branch.is_currently_open()
    cur_sym = selected_branch.get_currency_symbol_ar() if active_lang == "ar" else selected_branch.get_currency_symbol_en()
    cur_name = selected_branch.get_currency_name_ar()
    context = {
        "tenant": tenant,
        "branches": branches,
        "selected_branch": selected_branch,
        "is_open": is_open,
        "min_delivery_order": float(selected_branch.min_delivery_order or 0),
        "branch_currency": selected_branch.currency,
        "branch_currency_symbol": cur_sym,
        "branch_currency_name": cur_name,
        "categories": categories_set,
        "category_objs": categories_data,
        "sections": sections,
        "categorized_items": categorized_items,
        "delivery_areas": areas,
        "brand_color": tenant.brand_color or "#0E382A",
        "CURRENT_LANG": active_lang,
        "DIR": "rtl" if active_lang == "ar" else "ltr",
        "IS_RTL": active_lang == "ar",
    }
    return render(request, "qr_menu.html", context)



def api_digital_menu_branch_areas(request, slug, branch_id):
    """Return JSON list of delivery areas for chosen branch."""
    tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id, status="active")
    areas = []
    for a in DeliveryArea.objects.filter(branch=branch, is_active=True).order_by("delivery_fee", "name"):
        areas.append({
            "id": a.id,
            "name": a.name,
            "fee": float(a.delivery_fee or 0),
            "estimated_time": f"{a.estimated_time_minutes} دقيقة" if a.estimated_time_minutes else "30-45 دقيقة",
        })
    return JsonResponse({"status": "success", "areas": areas})


@csrf_exempt
def api_digital_menu_place_order(request, slug):
    """
    Public self-ordering endpoint for digital menu customers.
    Strictly accepts Takeaway (سفري) or Delivery (توصيل) orders only.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "بيانات غير صالحة"}, status=400)

    branch_id = data.get("branch_id")
    order_type = str(data.get("order_type", "takeaway")).strip().lower()
    customer_name = str(data.get("customer_name", "")).strip()
    customer_phone = str(data.get("customer_phone", "")).strip()
    delivery_area_id = data.get("delivery_area_id")
    address = str(data.get("address", "")).strip()
    notes = str(data.get("notes", "")).strip()
    items_data = data.get("items", [])

    # Strict Validation: Takeaway and Delivery ONLY
    if order_type not in ["takeaway", "delivery"]:
        return JsonResponse({
            "status": "error",
            "message": "نوع الطلب غير صالح. الطلبات المتاحة هي: سفري أو توصيل فقط."
        }, status=400)

    if not customer_name or len(customer_name) < 2:
        return JsonResponse({"status": "error", "message": "يرجى كتابة اسم العميل بشكل صحيح."}, status=400)

    if not customer_phone or len(customer_phone) < 7:
        return JsonResponse({"status": "error", "message": "يرجى كتابة رقم هاتف صالح للتواصل."}, status=400)

    if order_type == "delivery":
        if not address:
            return JsonResponse({"status": "error", "message": "يرجى إدخال عنوان التوصيل المفصل."}, status=400)
        if not delivery_area_id:
            return JsonResponse({"status": "error", "message": "يرجى اختيار منطقة التوصيل من القائمة."}, status=400)

    branch = Branch.objects.filter(tenant=tenant, id=branch_id, status="active").first()
    if not branch:
        return JsonResponse({"status": "error", "message": "الفرع المحدد غير متاح لاستقبال الطلبات حالياً."}, status=400)

    # Check Branch Operating Hours
    if not branch.is_currently_open():
        time_info = ""
        if branch.opening_time and branch.closing_time:
            time_info = f" (ساعات العمل: {branch.opening_time.strftime('%I:%M %p')} إلى {branch.closing_time.strftime('%I:%M %p')})"
        return JsonResponse({
            "status": "error",
            "message": f"عذراً، فرع «{branch.name}» مغلق حالياً ولا يستقبل طلبات جديدة{time_info}."
        }, status=400)

    if not items_data or not isinstance(items_data, list):
        return JsonResponse({"status": "error", "message": "سلة الطلب فارغة. يرجى اختيار وجبات من المنيو أولاً."}, status=400)

    # Validate items and calculate totals strictly from DB
    menu_ids = [int(i.get("menuItemId") or i.get("id") or 0) for i in items_data if (i.get("menuItemId") or i.get("id"))]
    menu_map = {m.id: m for m in MenuItem.objects.filter(tenant=tenant, id__in=menu_ids)}
    disabled_ids = set(
        BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True)
    )

    order_items_to_create = []
    subtotal = Decimal("0.00")
    for it in items_data:
        m_id = int(it.get("menuItemId") or it.get("id") or 0)
        m = menu_map.get(m_id)
        if not m or not m.available or m_id in disabled_ids:
            return JsonResponse({
                "status": "error",
                "message": f"الصنف «{m.name if m else m_id}» غير متاح للطلب في هذا الفرع حالياً."
            }, status=400)
        qty = max(1, int(it.get("qty", 1)))

        # Check variant (size) if selected
        v_id = it.get("variantId") or it.get("variant_id")
        variant_obj = None
        item_price = m.get_price_for_branch(branch)
        item_title = m.name
        if v_id and m.has_variants:
            variant_obj = MenuItemVariant.objects.filter(id=v_id, menu_item=m).first()
            if variant_obj:
                item_price = variant_obj.get_price_for_branch(branch)
                item_title = f"{m.name} ({variant_obj.name})"
        elif m.has_variants:
            variant_obj = m.variants.filter(is_default=True).first() or m.variants.first()
            if variant_obj:
                item_price = variant_obj.get_price_for_branch(branch)
                item_title = f"{m.name} ({variant_obj.name})"

        note_str = str(it.get("notes", "")).strip()[:200]
        if note_str:
            item_title = f"{item_title} [{note_str}]"

        subtotal += item_price * qty
        order_items_to_create.append({
            "item": m,
            "variant": variant_obj,
            "variant_name": variant_obj.name if variant_obj else "",
            "title": item_title,
            "qty": qty,
            "price": item_price,
        })

    # Validate Minimum Delivery Order
    if order_type == "delivery" and branch.min_delivery_order > 0 and subtotal < branch.min_delivery_order:
        cur_sym = branch.get_currency_symbol_ar()
        return JsonResponse({
            "status": "error",
            "message": f"الحد الأدنى لطلب التوصيل من هذا الفرع هو {branch.min_delivery_order} {cur_sym}. (المجموع الحالي: {subtotal} {cur_sym})."
        }, status=400)

    delivery_fee = Decimal("0.00")
    area = None
    if order_type == "delivery" and delivery_area_id:
        area = DeliveryArea.objects.filter(branch=branch, id=delivery_area_id, is_active=True).first()
        if area and area.delivery_fee:
            delivery_fee = Decimal(str(area.delivery_fee))

    total = subtotal + delivery_fee

    # Generate unique order number
    import secrets
    ord_number = f"QR-{secrets.token_hex(3).upper()}"
    while Order.objects.filter(tenant=tenant, order_number=ord_number).exists():
        ord_number = f"QR-{secrets.token_hex(3).upper()}"

    # Customer record
    cust, _ = Customer.objects.get_or_create(
        tenant=tenant,
        phone=customer_phone,
        defaults={"name": customer_name, "address": address}
    )

    order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number=ord_number,
        order_type=order_type,
        channel="qr_menu",
        status="new",
        pay_method="cash",
        paid=False,
        customer=cust,
        customer_name=customer_name,
        customer_phone=customer_phone,
        address=address,
        delivery_area=area,
        delivery_fee=delivery_fee,
        subtotal=subtotal,
        total=total,
        notes=notes,
    )

    for row in order_items_to_create:
        OrderItem.objects.create(
            order=order,
            menu_item=row["item"],
            variant=row["variant"],
            variant_name=row["variant_name"],
            name=row["title"],
            price=row["price"],
            qty=row["qty"],
        )

    # Broadcast real-time SSE event to kitchen display screens (0ms dispatch)
    try:
        notify_kitchen_order_event(order, "new_order")
        if order.order_type == "delivery":
            from apps.orders.events import notify_delivery_order_event
            notify_delivery_order_event(order, "delivery_new_order")
    except Exception as e:
        logger.warning(f"Failed to dispatch kitchen SSE for QR order {order.order_number}: {e}")

    active_lang = request.session.get("django_language") or request.COOKIES.get("django_language") or "ar"
    if hasattr(request, "LANGUAGE_CODE") and request.LANGUAGE_CODE:
        active_lang = request.LANGUAGE_CODE
    if "-" in active_lang:
        active_lang = active_lang.split("-")[0]
    is_en = (active_lang == "en")

    return JsonResponse({
        "status": "success",
        "message": "Your order has been received successfully! Preparing in the kitchen." if is_en else "تم استلام طلبك بنجاح! جاري تحضيره في المطبخ.",
        "order_id": order.id,
        "order_number": order.order_number,
        "order_type": ("Takeaway Pickup" if order.order_type == "takeaway" else "Home Delivery") if is_en else order.get_order_type_display(),
        "branch_name": branch.get_display_name(active_lang),
        "total": float(order.total),
        "subtotal": float(order.subtotal),
        "delivery_fee": float(order.delivery_fee),
    }, status=201)

