import json
from decimal import Decimal
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q

from apps.tenants.helpers import get_active_tenant, get_active_branch
from apps.accounts.helpers import user_has_perm, _get_client_ip
from apps.inventory.models import InventoryItem
from apps.tenants.models import Branch
from apps.audit.models import log_audit_event


def inventory_view(request):
    tenant = get_active_tenant(request)
    if tenant and not tenant.has_feature("inventory"):
        return HttpResponseForbidden("ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم. يرجى ترقية الباقة لتفعيلها.")

    if not (
        user_has_perm(request.user, "manage_inventory") or
        user_has_perm(request.user, "inventory_view") or
        user_has_perm(request.user, "inventory_add_stock") or
        user_has_perm(request.user, "inventory_adjust_stock")
    ):
        return HttpResponseForbidden("غير مصرح لك بالوصول لإدارة أو استعراض المخزون")
    active_branch = get_active_branch(request)
    branch_id = request.GET.get("branch")
    search = request.GET.get("q", "").strip()

    items = InventoryItem.objects.filter(tenant=tenant).select_related("branch").order_by("branch__name", "name")

    if active_branch:
        items = items.filter(branch=active_branch)
        selected_branch = active_branch.id
    elif branch_id and branch_id.isdigit():
        items = items.filter(branch_id=int(branch_id))
        selected_branch = int(branch_id)
    else:
        selected_branch = "all"

    if search:
        items = items.filter(Q(name__icontains=search) | Q(supplier__icontains=search))

    branches = Branch.objects.filter(tenant=tenant).order_by("name")
    low_count = items.filter(quantity__lte=F("min_quantity")).count()

    context = {
        "tenant": tenant,
        "current_branch": active_branch,
        "items": items,
        "branches": branches,
        "low_count": low_count,
        "selected_branch": selected_branch,
        "search_query": search,
        "units": ["كجم", "لتر", "علبة", "قطعة", "كرتون", "حبة"],
    }
    return render(request, "inventory.html", context)


@login_required
def api_adjust_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if tenant and not tenant.has_feature("inventory") and not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return JsonResponse({"error": "ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not is_owner_or_super and not (user_has_perm(request.user, "inventory_adjust_stock") or user_has_perm(request.user, "manage_inventory")):
        return JsonResponse({"error": "غير مصرح لك بتسوية أو تعديل كميات المخزون"}, status=403)

    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    with transaction.atomic():
        item = InventoryItem.objects.select_for_update().filter(tenant=tenant, id=item_id).first()
        if not item:
            return JsonResponse({"error": "عنصر المخزون غير موجود"}, status=404)

        if not can_cross and user_branch and item.branch and item.branch != user_branch:
            return JsonResponse({"error": "غير مصرح لك بتسوية مخزون الفروع الأخرى"}, status=403)

        if "delta" in data:
            delta = Decimal(str(data["delta"]))
            item.quantity = max(Decimal("0"), item.quantity + delta)
        elif "quantity" in data:
            item.quantity = max(Decimal("0"), Decimal(str(data["quantity"])))

        if "minQuantity" in data:
            item.min_quantity = max(Decimal("0"), Decimal(str(data["minQuantity"])))
        if "supplier" in data:
            item.supplier = str(data["supplier"])

        item.save()
        log_audit_event(
            tenant=tenant,
            user=request.user,
            action="inventory_stock_adjusted",
            target_model="InventoryItem",
            target_id=item.id,
            description=f"تسوية مخزون المادة «{item.name}» إلى {item.quantity} {item.unit} في فرع «{item.branch.name if item.branch else ''}»",
            ip_address=_get_client_ip(request),
        )
        return JsonResponse({"ok": True, "quantity": float(item.quantity), "minQuantity": float(item.min_quantity)})


@login_required
def api_create_inventory(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if tenant and not tenant.has_feature("inventory") and not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return JsonResponse({"error": "ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not is_owner_or_super and not (user_has_perm(request.user, "inventory_add_stock") or user_has_perm(request.user, "manage_inventory")):
        return JsonResponse({"error": "غير مصرح لك بإضافة مواد جديدة للمخزون"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    branch_id = data.get("branchId")
    if not name or not branch_id:
        return JsonResponse({"error": "اسم المادة والفرع مطلوبان"}, status=400)

    branch = get_object_or_404(Branch, tenant=tenant, id=branch_id)
    if branch.status != "active":
        return JsonResponse({"error": "لا يمكن إضافة مخزون لفرع مغلق أو غير نشط"}, status=400)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    if not can_cross and user_branch and branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بإضافة مخزون في الفروع الأخرى"}, status=403)

    item = InventoryItem.objects.create(
        tenant=tenant,
        branch=branch,
        name=name,
        unit=data.get("unit", "كجم"),
        quantity=max(Decimal("0"), Decimal(str(data.get("quantity") or 0))),
        min_quantity=max(Decimal("0"), Decimal(str(data.get("minQuantity") or 5))),
        supplier=data.get("supplier", ""),
    )
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="inventory_item_created",
        target_model="InventoryItem",
        target_id=item.id,
        description=f"إضافة المادة «{item.name}» برصيد أولي {item.quantity} {item.unit} لفرع «{branch.name}»",
        ip_address=_get_client_ip(request),
    )
    return JsonResponse({"ok": True, "id": item.id})


@login_required
def api_delete_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    tenant = get_active_tenant(request)
    profile = getattr(request.user, "profile", None)
    emp = getattr(request.user, "employee_profile", None)
    is_owner_or_super = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))

    if tenant and not tenant.has_feature("inventory") and not (request.user.is_superuser or (profile and profile.is_platform_admin)):
        return JsonResponse({"error": "ميزة إدارة المخزون غير مفعلة في باقة اشتراك هذا المطعم"}, status=403)

    if not is_owner_or_super and not user_has_perm(request.user, "manage_inventory"):
        return JsonResponse({"error": "غير مصرح لك بحذف مواد من المخزون (يتطلب صلاحية إدارة المخزون)"}, status=403)

    item = get_object_or_404(InventoryItem, tenant=tenant, id=item_id)
    user_branch = profile.branch if profile and profile.branch else (emp.branch if emp and emp.branch else None)
    can_cross = (
        is_owner_or_super
        or user_has_perm(request.user, "branch_switch_branches")
        or user_has_perm(request.user, "manage_branches")
        or user_has_perm(request.user, "view_hq_dashboard")
        or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
        or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
    )
    if not can_cross and user_branch and item.branch and item.branch != user_branch:
        return JsonResponse({"error": "غير مصرح لك بحذف مخزون الفروع الأخرى"}, status=403)

    item_name = item.name
    item_id_val = item.id
    item_qty = item.quantity
    item_unit = item.unit
    b_name = item.branch.name if item.branch else "الفرع"
    item.delete()
    log_audit_event(
        tenant=tenant,
        user=request.user,
        action="inventory_item_deleted",
        target_model="InventoryItem",
        target_id=item_id_val,
        description=f"حذف عنصر المخزون «{item_name}» (الكمية: {item_qty} {item_unit}) من فرع «{b_name}»",
        ip_address=_get_client_ip(request),
    )
    return JsonResponse({"ok": True, "message": f"تم حذف عنصر المخزون «{item_name}» بنجاح"})
