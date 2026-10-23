# Survey Analysis: Backend Models, Data Storage, and Endpoints for Restaurant Profile

**Agent**: `explorer_survey_2`  
**Date**: 2026-10-23  
**Target Workspace**: `/root/motaem`  
**Objective**: Survey backend models, storage, endpoints, and validation for Central HQ Restaurant Profile (R1, R2, R3).

---

## 1. Executive Summary

- **Single Core Model**: The restaurant organization is modeled exclusively by `Tenant` in `apps/tenants/models.py` (with `app_label = 'core'`, re-exported via `core/models.py`). No separate `Restaurant`, `Company`, or `Organization` model exists.
- **Zero Schema Migrations Needed**: All 8 fields required by R1 and R2 (`name`, `bio`, `phone`, `email`, `address`, `brand_color`, `logo_image`, `cover_image`) **already exist** on the `Tenant` model and are active in the SQLite database (introduced in migrations `0003` and `0015`).
- **Media Configuration**: `MEDIA_URL = '/media/'`, `MEDIA_ROOT = BASE_DIR / 'media'`. Media files are served via `re_path(r'^media/(?P<path>.*)$', serve, ...)` in `restaurant_system/urls.py`. The models utilize `models.FileField` because `Pillow` is not installed; custom validation on size and extension/MIME type must be enforced in the view/form handler.
- **Existing View Patterns**: 100% Function-Based Views (FBVs) across modular domain apps under `apps/` with facade exports in `core/views.py`. Form inputs are parsed directly from `request.POST` and `request.FILES`.
- **Existing Branding Endpoint**: `api_update_tenant_branding` in `apps/tenants/views.py:685` partially updates branding (`name`, `bio`, `brand_color`, `logo_image`, `cover_image`) but omits `phone`, `email`, and `address`, and permits users with `manage_menu` (violating strict HQ-only profile permissions in R3).
- **Recommended Implementation Path**:
  1. Add dedicated FBV `restaurant_profile_view` in `apps/tenants/views.py` (re-exported in `core/views.py`) handling GET (render `restaurant_profile.html`) and POST (update all 8 fields + validation + audit log).
  2. Map routes `restaurant/profile/` and `api/restaurant/profile/` (with backwards compatibility for `api/settings/branding/`).
  3. Strict RBAC enforcement: verify user is Owner (`role == 'owner'`) or HQ Manager (`view_hq_dashboard` / `scope == 'hq'`), returning HTTP 403 for branch-only staff (Cashier, Kitchen, Driver).
  4. Link the profile page in `templates/_admin_nav_tabs.html` and `templates/base.html` sidebar.

---

## 2. Existing Model Definitions and Data Storage

### 2.1 The `Tenant` Model
File: `/root/motaem/apps/tenants/models.py` (lines 6–161)  
Facade: `/root/motaem/core/models.py` (line 16)

```python
class Tenant(models.Model):
    PLAN_CHOICES = [
        ("trial", "تجريبي"),
        ("standard", "أساسي"),
        ("premium", "متقدم"),
        ("enterprise", "شركات"),
    ]
    # ... choices ...

    name = models.CharField(max_length=255, verbose_name="اسم المطعم / المنشأة")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="المعرف اللاتيني (Slug)")
    logo_emoji = models.CharField(max_length=20, default="🍽️", blank=True, verbose_name="شعار / أيقونة")
    logo_image = models.FileField(upload_to="tenant_logos/", blank=True, null=True, verbose_name="شعار المطعم (Logo)")
    cover_image = models.FileField(upload_to="tenant_covers/", blank=True, null=True, verbose_name="صورة الغلاف (Cover)")
    custom_domain = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True, verbose_name="النطاق المخصص (Custom Domain)")
    brand_color = models.CharField(max_length=20, default="#0E382A", blank=True, verbose_name="اللون الأساسي للهوية")
    bio = models.CharField(max_length=255, default="", blank=True, verbose_name="نبذة عن المطعم")
    phone = models.CharField(max_length=50, default="", blank=True, verbose_name="رقم الهاتف")
    email = models.EmailField(blank=True, default="", verbose_name="البريد الإلكتروني")
    address = models.CharField(max_length=255, default="", blank=True, verbose_name="المقر الرئيسي")
    plan = models.CharField(max_length=30, choices=PLAN_CHOICES, default="standard", verbose_name="خطة الاشتراك")

    subscription_plan = models.ForeignKey(
        'core.SubscriptionPlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenants",
        verbose_name="باقة الاشتراك",
    )
    # ... subscription dates, PBX settings, currencies ...
    default_currency = models.CharField(max_length=10, default="SAR", verbose_name="العملة الافتراضية للمنشأة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسجيل")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")

    class Meta:
        app_label = 'core'
        verbose_name = "مستأجر / منشأة"
        verbose_name_plural = "المستأجرون (المنشآت والمطاعم)"
        ordering = ["name"]
```

### 2.2 Field Inventory vs Requirements (R1 / R2)

| Required Field | Field on Tenant Model | Type | DB Column Exists? | Notes |
|---|---|---|---|---|
| Restaurant Name | `tenant.name` | `CharField(max_length=255)` | Yes (0003_initial) | Primary business title |
| Bio / Description | `tenant.bio` | `CharField(max_length=255)` | Yes (0015_migration) | Slogan / short summary |
| Phone Number | `tenant.phone` | `CharField(max_length=50)` | Yes (0003_initial) | Central contact phone |
| Email Address | `tenant.email` | `EmailField(max_length=254)` | Yes (0003_initial) | Central contact email |
| Physical HQ Address | `tenant.address` | `CharField(max_length=255)` | Yes (0003_initial) | Physical HQ address |
| Primary Brand Color | `tenant.brand_color` | `CharField(max_length=20)` | Yes (0015_migration) | Default `#0E382A`, hex format |
| Logo Image Upload | `tenant.logo_image` | `FileField(upload_to="tenant_logos/")` | Yes (0015_migration) | Target path: `media/tenant_logos/` |
| Cover Banner Upload | `tenant.cover_image` | `FileField(upload_to="tenant_covers/")` | Yes (0015_migration) | Target path: `media/tenant_covers/` |
| Fallback Emoji | `tenant.logo_emoji` | `CharField(max_length=20)` | Yes (0003_initial) | Default `🍽️` |
| Custom Domain | `tenant.custom_domain` | `CharField(max_length=255)` | Yes (0015_migration) | Optional domain binding |

**Migration Conclusion**:
No new migrations or schema alterations are needed. The database is 100% prepared to store all profile data.

---

## 3. Media Configuration and Upload Architecture

### 3.1 Settings Configuration
File: `/root/motaem/restaurant_system/settings.py` (lines 214–215):
```python
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
```

File: `/root/motaem/restaurant_system/urls.py` (lines 35–37):
```python
from django.urls import re_path
from django.views.static import serve

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
```

### 3.2 File Storage & Pillow Dependency
- Running `python -c "import PIL"` confirmed: `ModuleNotFoundError: No module named 'PIL'`.
- Because `Pillow` is not installed, Django's `models.ImageField` cannot be used without breaking system checks.
- Django's `models.FileField` is already used in `Tenant` (`upload_to="tenant_logos/"` and `upload_to="tenant_covers/"`) and `MenuItem` (`upload_to="menu_items/"`).
- When saved via `tenant.logo_image = request.FILES["logo_image"]`, Django's `FileSystemStorage` saves files into `/root/motaem/media/tenant_logos/<filename>`.

### 3.3 Recommended Upload Validation Rules
To ensure secure and reliable media handling without `Pillow`:
1. **File Size Limits**:
   - `logo_image`: Max 2 MB (`2 * 1024 * 1024` bytes)
   - `cover_image`: Max 5 MB (`5 * 1024 * 1024` bytes)
2. **File Extension Whitelist**:
   - Logo: `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`
   - Cover: `.png`, `.jpg`, `.jpeg`, `.webp`
3. **MIME / Content-Type Check**:
   - Logo: `image/png`, `image/jpeg`, `image/webp`, `image/svg+xml`
   - Cover: `image/png`, `image/jpeg`, `image/webp`
4. **Validation Failure Handling**:
   - Return HTTP 400 with a localized error string:
     - `{"status": "error", "error": "حجم ملف الشعار يتجاوز الحد المسموح به (2 ميجابايت)"}`
     - `{"status": "error", "error": "صيغة الملف غير مدعومة. يرجى رفع ملف بصيغة PNG أو JPG أو WEBP"}`

---

## 4. View Patterns and Endpoint Architecture

### 4.1 Existing Implementation: `api_update_tenant_branding`
File: `/root/motaem/apps/tenants/views.py` (lines 685–735)

```python
@login_required
def api_update_tenant_branding(request):
    """Update restaurant logo, cover, bio, brand color, and name."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    tenant = get_active_tenant(request)
    if not tenant:
        return JsonResponse({"error": "منشأة غير موجودة"}, status=400)

    profile = getattr(request.user, "profile", None)
    is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
    if not is_owner and not user_has_perm(request.user, "manage_menu"):
        return JsonResponse({"error": "غير مصرح لك بتعديل هوية المطعم"}, status=403)

    name = request.POST.get("name", "").strip()
    if name:
        tenant.name = name

    bio = request.POST.get("bio", "").strip()
    if bio is not None:
        tenant.bio = bio

    brand_color = request.POST.get("brand_color", "").strip()
    if brand_color:
        tenant.brand_color = brand_color

    logo_emoji = request.POST.get("logo_emoji", "").strip()
    if logo_emoji:
        tenant.logo_emoji = logo_emoji

    if "logo_image" in request.FILES:
        tenant.logo_image = request.FILES["logo_image"]

    if "cover_image" in request.FILES:
        tenant.cover_image = request.FILES["cover_image"]

    tenant.save()
    return JsonResponse({...})
```

**Limitations of Current Endpoint**:
1. Does not accept or save `phone`, `email`, or `address`.
2. Permissive access: checks `user_has_perm(request.user, "manage_menu")`, which permits branch menu managers to alter chain-wide branding.
3. No dedicated GET view for the Restaurant Profile page.

### 4.2 Recommended Architecture for R1, R2, R3

#### 1. Page View (`restaurant_profile_view`)
- **Route**: `GET /restaurant/profile/` (name: `"restaurant_profile"`)
- **Permissions (R3)**:
  - Must be authenticated (`@login_required`). Unauthenticated redirects to `/login/`.
  - Authorized users:
    - Superuser / Platform Admin (`request.user.is_superuser or profile.is_platform_admin`)
    - Restaurant Owner (`profile.role == "owner"`)
    - HQ Managers (`user_has_perm(request.user, "view_hq_dashboard")` or `profile.job_role.scope in ["hq", "both"]` or `emp.job_role.scope in ["hq", "both"]`)
  - Denied users (HTTP 403 Forbidden):
    - Branch-only staff: Cashier, Kitchen Chef, Delivery Driver, Waiter, or Branch Manager lacking HQ permission.
- **Context Provided**:
  - `tenant`: `get_active_tenant(request)`
  - `tenant_subscription`: active plan info
  - `is_owner`: boolean

#### 2. Update Endpoint (`api_update_restaurant_profile`)
- **Route**: `POST /api/restaurant/profile/` and `POST /restaurant/profile/`
- **Fields Processed**:
  - `name`: String, required.
  - `bio`: String, optional, max 255 chars.
  - `phone`: String, optional, max 50 chars.
  - `email`: String, optional, validated with `django.core.validators.validate_email`.
  - `address`: String, optional, max 255 chars.
  - `brand_color`: String, optional, validated as hex color (`^#(?:[0-9a-fA-F]{3}){1,2}$`).
  - `logo_emoji`: String, optional.
  - `logo_image`: File, optional, max 2MB, allowed extensions (.png, .jpg, .jpeg, .webp, .svg).
  - `cover_image`: File, optional, max 5MB, allowed extensions (.png, .jpg, .jpeg, .webp).
- **Tenant Isolation**:
  - `tenant = get_active_tenant(request)`. All modifications are applied strictly to the active tenant instance.
- **Audit Logging**:
  - Call `log_audit_event(tenant=tenant, user=request.user, action="update_restaurant_profile", target_model="Tenant", target_id=tenant.id, description="تحديث بيانات وهوية المطعم", ip_address=_get_client_ip(request))`.
- **Response**:
  - On AJAX / multipart fetch: Returns `JsonResponse({"status": "success", "message": "تم تحديث الملف التعريفي للمطعم بنجاح", "tenant": {...}})`
  - On standard form submit: Redirects to `restaurant_profile` with success message or renders form with errors.

---

## 5. UI and Navigation Integration Plan

### 5.1 Admin Tabs (`templates/_admin_nav_tabs.html`)
Add a new tab for "الملف التعريفي والهوية" (Restaurant Profile) alongside existing tabs:
1. **الملف التعريفي والهوية** (`restaurant_profile`) -> `{% url 'restaurant_profile' %}`
2. **إدارة الفروع والمواقع** (`branches`) -> `{% url 'branches' %}`
3. **قائمة الأطباق والأسعار** (`branch_menu`) -> `{% url 'branch_menu' %}`
4. **جرد المخزون والمستودعات** (`inventory`) -> `{% url 'inventory' %}`
5. **فريق العمل والرواتب** (`employees`) -> `{% url 'employees' %}`
6. **الاشتراكات والتقارير المالية** (`owner_subscription`) -> `{% url 'owner_subscription' %}`

### 5.2 Sidebar Navigation (`templates/base.html`)
In `templates/base.html:724`:
Under General Administration, include `restaurant_profile` in the active link matcher:
`{% if request.resolver_match.url_name in 'restaurant_profile,branches,branch_menu,inventory,employees,owner_subscription' %}`.

### 5.3 HQ Command Dashboard (`templates/dashboard.html`)
In the top command toolbar (`templates/dashboard.html:29–45`), add a direct action button:
```html
<a href="{% url 'restaurant_profile' %}" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white hover:bg-slate-50 border border-slate-200/80 text-xs font-medium text-slate-700 hover:text-slate-900 transition shadow-xs">
    <svg class="w-4 h-4 text-violet-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
    </svg>
    <span>الملف التعريفي</span>
</a>
```

---

## 6. Verification and Test Architecture

1. **Unauthenticated Redirect**:
   - `client.get('/restaurant/profile/')` -> HTTP 302 -> `/login/?next=/restaurant/profile/`
2. **Strict RBAC Enforcement (R3)**:
   - Cashier, Kitchen Chef, Delivery Driver accessing `GET /restaurant/profile/` or `POST /api/restaurant/profile/` receive HTTP 403 Forbidden with clear Arabic message.
   - Owner and HQ General Manager receive HTTP 200 OK.
3. **Multi-Tenant Isolation (R3)**:
   - Tenant A's owner submits update -> Tenant A's record updates; Tenant B remains unchanged.
4. **Data Persistence (R2)**:
   - Submitting updated `name`, `bio`, `phone`, `email`, `address`, `brand_color` persists to DB.
5. **Media Upload & Preview (R2)**:
   - Uploading `SimpleUploadedFile("logo.png", ...)` and `SimpleUploadedFile("cover.jpg", ...)` stores files under `/root/motaem/media/` and updates `logo_image` and `cover_image` URLs.
6. **Validation Error Checks**:
   - Oversized images (>2MB for logo, >5MB for cover) return HTTP 400.
   - Invalid file extensions return HTTP 400.
   - Invalid email format returns HTTP 400.
