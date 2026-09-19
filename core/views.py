import json
from decimal import Decimal
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.db.models import Sum, Count, F, Q
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import (
    Branch,
    Employee,
    MenuItem,
    InventoryItem,
    Customer,
    Order,
    OrderItem,
    UserProfile,
    BranchMenuAvailability,
)


def get_active_branch(request):
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and profile.role == "owner")
    if not is_owner and profile and profile.branch:
        return profile.branch
    active_id = request.session.get("active_branch_id")
    if active_id:
        return Branch.objects.filter(id=active_id).first()
    return None


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    error_message = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next")
            if next_url:
                return redirect(next_url)
            # Route by role
            profile = getattr(user, "profile", None)
            if profile and profile.role != "owner" and profile.branch:
                request.session["active_branch_id"] = profile.branch.id
                return redirect("branch_dashboard")
            return redirect("dashboard")
        else:
            error_message = "اسم المستخدم أو كلمة المرور غير صحيحة"

    return render(request, "login.html", {"error": error_message})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def switch_branch_view(request, branch_id):
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and profile.role == "owner")
    if not is_owner:
        return redirect("branch_dashboard")

    if branch_id == 0 or str(branch_id) == "all":
        request.session["active_branch_id"] = None
        return redirect("dashboard")
    else:
        branch = get_object_or_404(Branch, id=branch_id)
        request.session["active_branch_id"] = branch.id
        return redirect("branch_dashboard")


# ==========================================
# 1. OWNER / HQ DASHBOARD (ALL BRANCHES)
# ==========================================

@login_required
@ensure_csrf_cookie
def dashboard_view(request):
    active_branch = get_active_branch(request)
    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and profile.role == "owner")

    # If branch-locked or active branch selected, redirect to branch dashboard
    if not is_owner or active_branch is not None:
        return redirect("branch_dashboard")

    now = timezone.now()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = start_of_today - timedelta(days=6)

    # 1. Orders today across all branches
    today_orders = Order.objects.filter(created_at__gte=start_of_today).exclude(status="cancelled")
    sales_today = today_orders.aggregate(total=Sum("total"))["total"] or Decimal("0")
    orders_count_today = today_orders.count()

    # 2. Active deliveries across company
    active_deliveries = Order.objects.filter(
        created_at__gte=start_of_today,
        order_type="delivery",
        status__in=["new", "preparing", "ready", "out_for_delivery"],
    ).count()

    # 3. Low stock count across all branches
    low_stock = InventoryItem.objects.filter(quantity__lte=F("min_quantity")).select_related("branch")
    low_stock_count = low_stock.count()

    # 4. Total employees across all branches
    total_employees = Employee.objects.count()
    total_payroll = Employee.objects.filter(status="active").aggregate(s=Sum("salary"))["s"] or Decimal("0")

    # 5. Last 7 days sales series
    week_orders = Order.objects.filter(created_at__gte=seven_days_ago).exclude(status="cancelled")
    days_data = []
    arabic_days = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    
    max_day_total = Decimal("1")
    for i in range(6, -1, -1):
        d_start = start_of_today - timedelta(days=i)
        d_end = d_start + timedelta(days=1)
        day_total = week_orders.filter(created_at__gte=d_start, created_at__lt=d_end).aggregate(
            t=Sum("total")
        )["t"] or Decimal("0")
        if day_total > max_day_total:
            max_day_total = day_total
        days_data.append({
            "label": "اليوم" if i == 0 else arabic_days[d_start.weekday()],
            "total": float(day_total),
            "is_today": i == 0,
        })

    # 6. Branch performance comparison matrix
    branches = Branch.objects.all().order_by("id")
    branch_matrix = []
    max_branch_sale = Decimal("1")
    for b in branches:
        b_orders = today_orders.filter(branch=b)
        b_total = b_orders.aggregate(t=Sum("total"))["t"] or Decimal("0")
        b_count = b_orders.count()
        b_emps = Employee.objects.filter(branch=b).count()
        b_low_stock = InventoryItem.objects.filter(branch=b, quantity__lte=F("min_quantity")).count()
        if b_total > max_branch_sale:
            max_branch_sale = b_total
        branch_matrix.append({
            "branch": b,
            "sales_today": float(b_total),
            "orders_today": b_count,
            "employees_count": b_emps,
            "low_stock_count": b_low_stock,
        })
    branch_matrix.sort(key=lambda x: x["sales_today"], reverse=True)

    # 7. Recent orders across the chain
    recent_orders = Order.objects.select_related("branch").order_by("-id")[:8]

    # 8. Top items nationwide
    top_items_qs = (
        OrderItem.objects.filter(order__created_at__gte=seven_days_ago)
        .exclude(order__status="cancelled")
        .values("name")
        .annotate(total_qty=Sum("qty"), total_revenue=Sum(F("price") * F("qty")))
        .order_by("-total_qty")[:6]
    )

    week_total = sum(d["total"] for d in days_data)

    context = {
        "sales_today": sales_today,
        "orders_today": orders_count_today,
        "active_deliveries": active_deliveries,
        "low_stock_count": low_stock_count,
        "total_employees": total_employees,
        "total_payroll": total_payroll,
        "days_data": days_data,
        "max_day_total": float(max_day_total),
        "week_total": week_total,
        "branch_matrix": branch_matrix,
        "max_branch_sale": float(max_branch_sale),
        "recent_orders": recent_orders,
        "top_items": top_items_qs,
        "low_stock_items": low_stock[:6],
    }
    return render(request, "hq_dashboard.html", context)


# ==========================================
# 2. BRANCH DASHBOARD (SINGLE BRANCH)
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_dashboard_view(request):
    branch = get_active_branch(request)
    if not branch:
        first_b = Branch.objects.first()
        if first_b:
            request.session["active_branch_id"] = first_b.id
            branch = first_b
        else:
            return redirect("branches")

    now = timezone.now()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Branch orders today
    branch_orders_today = Order.objects.filter(branch=branch, created_at__gte=start_of_today).exclude(status="cancelled")
    sales_today = branch_orders_today.aggregate(t=Sum("total"))["t"] or Decimal("0")
    orders_count_today = branch_orders_today.count()

    # Kitchen active orders (new or preparing)
    kitchen_pending_count = Order.objects.filter(
        branch=branch,
        status__in=["new", "preparing"]
    ).count()

    # Active deliveries for this branch
    active_deliveries_count = Order.objects.filter(
        branch=branch,
        order_type="delivery",
        status__in=["new", "preparing", "ready", "out_for_delivery"]
    ).count()

    # Branch low stock count
    branch_low_stock = InventoryItem.objects.filter(branch=branch, quantity__lte=F("min_quantity"))
    low_stock_count = branch_low_stock.count()

    # Branch employees
    employees_count = Employee.objects.filter(branch=branch).count()

    # Recent orders for this branch
    recent_orders = Order.objects.filter(branch=branch).order_by("-id")[:8]

    # Live kitchen queue preview (up to 4 orders)
    kitchen_preview = Order.objects.filter(
        branch=branch,
        status__in=["new", "preparing"]
    ).prefetch_related("items").order_by("created_at")[:4]

    kitchen_preview_data = []
    for ko in kitchen_preview:
        elapsed = int((now - ko.created_at).total_seconds() / 60)
        kitchen_preview_data.append({
            "order": ko,
            "elapsed_minutes": elapsed,
        })

    context = {
        "branch": branch,
        "sales_today": sales_today,
        "orders_today": orders_count_today,
        "kitchen_pending_count": kitchen_pending_count,
        "active_deliveries_count": active_deliveries_count,
        "low_stock_count": low_stock_count,
        "employees_count": employees_count,
        "recent_orders": recent_orders,
        "kitchen_preview_data": kitchen_preview_data,
        "branch_low_stock": branch_low_stock[:5],
    }
    return render(request, "branch_dashboard.html", context)


# ==========================================
# 3. KITCHEN DISPLAY SCREEN (KDS - المطبخ)
# ==========================================

@login_required
@ensure_csrf_cookie
def kitchen_view(request):
    branch = get_active_branch(request)
    now = timezone.now()

    orders_qs = Order.objects.filter(status__in=["new", "preparing"]).prefetch_related("items").order_by("created_at")
    if branch:
        orders_qs = orders_qs.filter(branch=branch)

    kitchen_orders = []
    for o in orders_qs:
        elapsed = int((now - o.created_at).total_seconds() / 60)
        kitchen_orders.append({
            "order": o,
            "elapsed_minutes": elapsed,
            "items": o.items.all(),
        })

    context = {
        "branch": branch,
        "kitchen_orders": kitchen_orders,
        "total_pending": len(kitchen_orders),
    }
    return render(request, "kitchen.html", context)


# ==========================================
# 4. BRANCH ORDERS VIEW
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_orders_view(request):
    branch = get_active_branch(request)
    status_filter = request.GET.get("status", "all")
    type_filter = request.GET.get("type", "all")
    search = request.GET.get("q", "").strip()

    orders = Order.objects.select_related("branch", "driver").order_by("-id")
    if branch:
        orders = orders.filter(branch=branch)
    if status_filter != "all":
        orders = orders.filter(status=status_filter)
    if type_filter != "all":
        orders = orders.filter(order_type=type_filter)
    if search:
        orders = orders.filter(Q(order_number__icontains=search) | Q(customer_name__icontains=search) | Q(customer_phone__icontains=search))

    context = {
        "branch": branch,
        "orders": orders[:50],
        "status_filter": status_filter,
        "type_filter": type_filter,
        "search_query": search,
        "statuses": Order.STATUS_CHOICES,
        "order_types": Order.TYPE_CHOICES,
    }
    return render(request, "branch_orders.html", context)


# ==========================================
# 5. BRANCH MENU AVAILABILITY VIEW
# ==========================================

@login_required
@ensure_csrf_cookie
def branch_menu_view(request):
    branch = get_active_branch(request)
    categories = ["الكل", "أطباق رئيسية", "مشويات", "ساندويتشات", "مقبلات", "مشروبات", "حلويات"]
    cat_filter = request.GET.get("cat", "الكل")
    search = request.GET.get("q", "").strip()

    menu_qs = MenuItem.objects.all().order_by("category", "name")
    if cat_filter != "الكل":
        menu_qs = menu_qs.filter(category=cat_filter)
    if search:
        menu_qs = menu_qs.filter(name__icontains=search)

    # If in branch context, map availability for this branch
    branch_avail_map = {}
    if branch:
        for av in BranchMenuAvailability.objects.filter(branch=branch):
            branch_avail_map[av.menu_item_id] = av.is_available

    items_data = []
    for item in menu_qs:
        if branch:
            # If explicit record exists use it, else default to item.available
            is_avail = branch_avail_map.get(item.id, item.available)
        else:
            is_avail = item.available

        items_data.append({
            "item": item,
            "is_available": is_avail,
        })

    context = {
        "branch": branch,
        "items_data": items_data,
        "categories": categories,
        "selected_cat": cat_filter,
        "search_query": search,
    }
    return render(request, "branch_menu.html", context)


# ==========================================
# 6. OPERATIONAL SCREENS (BRANCH AWARE)
# ==========================================

@login_required
@ensure_csrf_cookie
def pos_view(request):
    branch = get_active_branch(request)
    categories = ["الكل", "أطباق رئيسية", "مشويات", "ساندويتشات", "مقبلات", "مشروبات", "حلويات"]

    # Filter available items for active branch
    all_menu = MenuItem.objects.all().order_by("category", "name")
    if branch:
        disabled_ids = set(BranchMenuAvailability.objects.filter(branch=branch, is_available=False).values_list("menu_item_id", flat=True))
        menu_items = []
        for m in all_menu:
            m_avail = (m.id not in disabled_ids) and m.available
            menu_items.append({
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "price": m.price,
                "emoji": m.emoji,
                "available": m_avail,
            })
    else:
        menu_items = [
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "price": m.price,
                "emoji": m.emoji,
                "available": m.available,
            }
            for m in all_menu
        ]

    branches = Branch.objects.filter(status="active").order_by("id")

    context = {
        "current_branch": branch,
        "menu_items": menu_items,
        "branches": branches,
        "categories": categories,
    }
    return render(request, "pos.html", context)


@login_required
@ensure_csrf_cookie
def call_center_view(request):
    menu_items = MenuItem.objects.filter(available=True).order_by("category", "name")
    branches = Branch.objects.filter(status="active")
    recent_orders = (
        Order.objects.filter(channel="call_center")
        .select_related("branch")
        .order_by("-id")[:12]
    )

    context = {
        "menu_items": menu_items,
        "branches": branches,
        "recent_orders": recent_orders,
    }
    return render(request, "call_center.html", context)


@login_required
@ensure_csrf_cookie
def delivery_view(request):
    branch = get_active_branch(request)
    start_of_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Scoped drivers
    drivers_qs = Employee.objects.filter(role="driver", status="active").order_by("name")
    if branch:
        drivers_qs = drivers_qs.filter(Q(branch=branch) | Q(branch__isnull=True))

    drivers = list(drivers_qs)

    # Delivery orders
    delivery_orders = Order.objects.filter(
        order_type="delivery",
        created_at__gte=start_of_today - timedelta(days=1),
    ).exclude(status="cancelled").select_related("branch", "driver").order_by("-id")

    if branch:
        delivery_orders = delivery_orders.filter(branch=branch)

    orders_by_status = {
        "new": [],
        "preparing": [],
        "ready": [],
        "out_for_delivery": [],
        "delivered": [],
    }
    for order in delivery_orders:
        if order.status in orders_by_status:
            orders_by_status[order.status].append(order)

    driver_stats = []
    for d in drivers:
        active = Order.objects.filter(driver=d, status="out_for_delivery").count()
        done = Order.objects.filter(driver=d, status="delivered", created_at__gte=start_of_today).count()
        driver_stats.append({
            "id": d.id,
            "name": d.name,
            "phone": d.phone,
            "active": active,
            "done": done,
        })

    active_count = sum(len(orders_by_status[st]) for st in ["new", "preparing", "ready", "out_for_delivery"])

    context = {
        "current_branch": branch,
        "orders_by_status": orders_by_status,
        "drivers": drivers,
        "driver_stats": driver_stats,
        "active_count": active_count,
    }
    return render(request, "delivery.html", context)


@login_required
@ensure_csrf_cookie
def inventory_view(request):
    active_branch = get_active_branch(request)
    branch_id = request.GET.get("branch")
    search = request.GET.get("q", "").strip()

    items = InventoryItem.objects.select_related("branch").order_by("branch__name", "name")

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

    branches = Branch.objects.all().order_by("name")
    low_count = items.filter(quantity__lte=F("min_quantity")).count()

    context = {
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
@ensure_csrf_cookie
def branches_view(request):
    start_of_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    branches = Branch.objects.all().order_by("id")
    branch_list = []
    for b in branches:
        emp_count = Employee.objects.filter(branch=b).count()
        sales = Order.objects.filter(branch=b, created_at__gte=start_of_today).exclude(status="cancelled").aggregate(
            t=Sum("total")
        )["t"] or Decimal("0")
        orders_count = Order.objects.filter(branch=b, created_at__gte=start_of_today).count()
        branch_list.append({
            "branch": b,
            "employees_count": emp_count,
            "sales_today": sales,
            "orders_today": orders_count,
        })

    context = {
        "branches_data": branch_list,
    }
    return render(request, "branches.html", context)


@login_required
@ensure_csrf_cookie
def employees_view(request):
    active_branch = get_active_branch(request)
    role_filter = request.GET.get("role", "all")
    branch_filter = request.GET.get("branch", "all")
    search = request.GET.get("q", "").strip()

    employees = Employee.objects.select_related("branch").order_by("name")

    if active_branch:
        employees = employees.filter(branch=active_branch)
        branch_filter = active_branch.id
    elif branch_filter != "all" and str(branch_filter).isdigit():
        employees = employees.filter(branch_id=int(branch_filter))

    if role_filter != "all":
        employees = employees.filter(role=role_filter)
    if search:
        employees = employees.filter(Q(name__icontains=search) | Q(phone__icontains=search))

    branches = Branch.objects.all().order_by("name")
    
    # Counts by role
    base_qs = Employee.objects.filter(branch=active_branch) if active_branch else Employee.objects.all()
    roles_summary = {
        "all": base_qs.count(),
        "manager": base_qs.filter(role="manager").count(),
        "cashier": base_qs.filter(role="cashier").count(),
        "chef": base_qs.filter(role="chef").count(),
        "driver": base_qs.filter(role="driver").count(),
        "call_center": base_qs.filter(role="call_center").count(),
        "waiter": base_qs.filter(role="waiter").count(),
    }

    context = {
        "current_branch": active_branch,
        "employees": employees,
        "branches": branches,
        "role_filter": role_filter,
        "branch_filter": branch_filter,
        "search_query": search,
        "roles_summary": roles_summary,
    }
    return render(request, "employees.html", context)


# ==========================================
# 7. JSON API ENDPOINTS
# ==========================================

@login_required
def api_create_order(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    items_data = data.get("items", [])
    if not items_data:
        return JsonResponse({"error": "السلة فارغة — أضف أصنافاً أولاً"}, status=400)

    order_type = data.get("type", "dine_in")
    channel = data.get("channel", "cashier")

    active_branch = get_active_branch(request)
    branch_id = active_branch.id if active_branch else data.get("branchId")
    branch = Branch.objects.filter(id=branch_id).first() if branch_id else None

    # Resolve items
    menu_ids = [int(i.get("menuItemId")) for i in items_data if i.get("menuItemId")]
    menu_map = {m.id: m for m in MenuItem.objects.filter(id__in=menu_ids)}

    rows = []
    subtotal = Decimal("0")
    for it in items_data:
        m_id = int(it.get("menuItemId", 0))
        m = menu_map.get(m_id)
        if not m:
            continue
        qty = max(1, int(it.get("qty", 1)))
        subtotal += m.price * qty
        rows.append({"menu_item": m, "name": m.name, "price": m.price, "qty": qty})

    if not rows:
        return JsonResponse({"error": "الأصناف المحددة غير متوفرة"}, status=400)

    delivery_fee = Decimal("8") if order_type == "delivery" else Decimal("0")
    discount = Decimal(str(data.get("discount") or 0))
    discount = max(Decimal("0"), min(discount, subtotal))
    total = max(Decimal("0"), subtotal + delivery_fee - discount)

    # Customer handling
    phone = str(data.get("customerPhone") or "").strip()
    cust_name = str(data.get("customerName") or "").strip() or ("عميل توصيل" if order_type == "delivery" else "عميل نقدي")
    address = str(data.get("address") or "").strip()
    customer = None

    if phone:
        customer, _ = Customer.objects.get_or_create(phone=phone, defaults={"name": cust_name, "address": address})
        if cust_name and customer.name != cust_name:
            customer.name = cust_name
        if address:
            customer.address = address
        customer.save()

    count = Order.objects.count()
    order_number = f"ORD-{1000 + count + 1}"

    order = Order.objects.create(
        order_number=order_number,
        order_type=order_type,
        channel=channel,
        branch=branch,
        customer=customer,
        customer_name=cust_name,
        customer_phone=phone,
        address=address,
        status="new",
        pay_method=data.get("payMethod", "cash"),
        paid=True,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        discount=discount,
        total=total,
        cashier=str(data.get("cashier") or request.user.username),
        notes=str(data.get("notes") or ""),
    )

    for r in rows:
        OrderItem.objects.create(
            order=order,
            menu_item=r["menu_item"],
            name=r["name"],
            price=r["price"],
            qty=r["qty"],
        )

    return JsonResponse({"order": {"id": order.id, "orderNumber": order.order_number}}, status=201)


@login_required
def api_update_order(request, order_id):
    if request.method not in ["PATCH", "POST"]:
        return HttpResponseBadRequest("PATCH or POST required")

    order = get_object_or_404(Order, id=order_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    if "status" in data and data["status"] in dict(Order.STATUS_CHOICES):
        order.status = data["status"]

    if "driverId" in data:
        drv_id = data["driverId"]
        if drv_id:
            order.driver = Employee.objects.filter(id=drv_id, role="driver").first()
        else:
            order.driver = None

    if "paid" in data and isinstance(data["paid"], bool):
        order.paid = data["paid"]

    order.save()
    return JsonResponse({"ok": True, "status": order.status})


@login_required
def api_toggle_branch_menu(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    branch = get_active_branch(request)
    item = get_object_or_404(MenuItem, id=item_id)

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
        item.available = not item.available
        item.save()
        return JsonResponse({"ok": True, "isAvailable": item.available, "itemName": item.name, "branch": "كل الفروع"})


@login_required
def api_search_customers(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 3:
        return JsonResponse({"customers": []})

    customers = Customer.objects.filter(Q(phone__icontains=q) | Q(name__icontains=q))[:8]
    res = []
    for c in customers:
        orders_count = c.orders.count()
        lifetime = c.orders.exclude(status="cancelled").aggregate(t=Sum("total"))["t"] or Decimal("0")
        res.append({
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "address": c.address,
            "ordersCount": orders_count,
            "lifetime": float(lifetime),
        })
    return JsonResponse({"customers": res})


@login_required
def api_toggle_menu_item(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    item = get_object_or_404(MenuItem, id=item_id)
    item.available = not item.available
    item.save()
    return JsonResponse({"id": item.id, "available": item.available, "name": item.name})


@login_required
def api_create_menu_item(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    price = Decimal(str(data.get("price") or 0))
    if not name or price <= 0:
        return JsonResponse({"error": "اسم الصنف والسعر مطلوبان"}, status=400)

    item = MenuItem.objects.create(
        name=name,
        category=data.get("category", "أطباق رئيسية"),
        price=price,
        cost=Decimal(str(data.get("cost") or 0)),
        emoji=data.get("emoji", "🍽️"),
        available=True,
    )

    # Initialize availability for all branches
    for b in Branch.objects.all():
        BranchMenuAvailability.objects.get_or_create(branch=b, menu_item=item, defaults={"is_available": True})

    return JsonResponse({"id": item.id, "name": item.name}, status=201)


@login_required
def api_adjust_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    item = get_object_or_404(InventoryItem, id=item_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

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
    return JsonResponse({"ok": True, "quantity": float(item.quantity), "minQuantity": float(item.min_quantity)})


@login_required
def api_create_inventory(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    branch_id = data.get("branchId")
    branch = get_object_or_404(Branch, id=branch_id)
    if not name:
        return JsonResponse({"error": "اسم الصنف مطلوب"}, status=400)

    item = InventoryItem.objects.create(
        branch=branch,
        name=name,
        unit=data.get("unit", "كجم"),
        quantity=Decimal(str(data.get("quantity") or 0)),
        min_quantity=Decimal(str(data.get("minQuantity") or 0)),
        supplier=str(data.get("supplier", "")),
    )
    return JsonResponse({"id": item.id, "name": item.name}, status=201)


@login_required
def api_delete_inventory(request, item_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    item = get_object_or_404(InventoryItem, id=item_id)
    item.delete()
    return JsonResponse({"ok": True})


@login_required
def api_create_branch(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم الفرع مطلوب"}, status=400)

    branch = Branch.objects.create(
        name=name,
        city=data.get("city", ""),
        address=data.get("address", ""),
        phone=data.get("phone", ""),
        status="active",
    )

    # Initialize menu availability for new branch
    for m in MenuItem.objects.all():
        BranchMenuAvailability.objects.create(branch=branch, menu_item=m, is_available=m.available)

    return JsonResponse({"id": branch.id, "name": branch.name}, status=201)


@login_required
def api_toggle_branch(request, branch_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    branch = get_object_or_404(Branch, id=branch_id)
    branch.status = "closed" if branch.status == "active" else "active"
    branch.save()
    return JsonResponse({"id": branch.id, "status": branch.status})


@login_required
def api_create_employee(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم الموظف مطلوب"}, status=400)

    branch = None
    if data.get("branchId"):
        branch = Branch.objects.filter(id=data["branchId"]).first()

    emp = Employee.objects.create(
        name=name,
        phone=data.get("phone", ""),
        role=data.get("role", "cashier"),
        branch=branch,
        salary=Decimal(str(data.get("salary") or 0)),
        status="active",
    )
    return JsonResponse({"id": emp.id, "name": emp.name}, status=201)


@login_required
def api_update_employee(request, emp_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    emp = get_object_or_404(Employee, id=emp_id)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    if "name" in data and str(data["name"]).strip():
        emp.name = str(data["name"]).strip()
    if "phone" in data:
        emp.phone = str(data["phone"])
    if "role" in data:
        emp.role = data["role"]
    if "salary" in data:
        emp.salary = Decimal(str(data["salary"] or 0))
    if "status" in data:
        emp.status = data["status"]
    if "branchId" in data:
        emp.branch = Branch.objects.filter(id=data["branchId"]).first() if data["branchId"] else None

    emp.save()
    return JsonResponse({"ok": True, "id": emp.id})
