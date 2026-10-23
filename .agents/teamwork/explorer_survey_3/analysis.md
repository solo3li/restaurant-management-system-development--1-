# RBAC, Multi-Tenant Isolation, and Test Infrastructure Survey

**Target System**: Motaem Cloud Restaurant OS (منظومة مطاعم السحابية)  
**Survey Agent**: `explorer_survey_3`  
**Date**: 2026-10-23  

---

## Executive Summary
This survey provides an in-depth technical analysis of:
1. Multi-tenant isolation and active tenant resolution mechanisms.
2. Role-Based Access Control (RBAC), native Django permission integration, role scopes, and HTTP 403 Forbidden enforcement patterns.
3. Existing test suites, verification pipelines (`./init.sh`, `manage.py check`, `test_system.py`, `test_e2e_rbac.py`), and feature tracking (`feature_list.json`).
4. Exact verification criteria, test matrices, and test automation patterns for the new **HQ Restaurant Profile** feature.

---

## 1. Multi-Tenant Isolation & Active Tenant Resolution

### 1.1 Architectural Topology
Multi-tenancy in Motaem is implemented at the schema/shared-database level with strict logical tenant partitioning. Every domain entity references `Tenant` (`apps/tenants/models.py`) via a foreign key:
- `Branch.tenant` (`apps/tenants/models.py:168`)
- `UserProfile.tenant` (`apps/accounts/models.py:446`)
- `Employee.tenant` (`apps/accounts/models.py:302`)
- `JobRole.tenant` (`apps/accounts/models.py:188`)
- `MenuItem.tenant`, `MenuCategory.tenant` (`apps/menu/models.py`)
- `Order.tenant`, `Customer.tenant` (`apps/orders/models.py`)
- `InventoryItem.tenant` (`apps/inventory/models.py`)
- `AuditLog.tenant` (`apps/audit/models.py`)

### 1.2 Tenant Resolution Pipeline (`TenantMiddleware`)
Located in `core/middleware.py:7-95`:
```
Incoming HTTP Request
   │
   ├── 1. Custom Domain Inspection (`core/middleware.py:16-29`)
   │      Checks Host header against `Tenant.objects.filter(custom_domain__iexact=host, is_active=True)`
   │      If matched: `request.custom_domain_tenant = custom_t`.
   │      If unauthenticated: `request.tenant = custom_t` (Used for public digital menu).
   │
   ├── 2. User Authentication Resolution (`core/middleware.py:31-55`)
   │      If `request.user.is_authenticated`:
   │         profile = getattr(request.user, "profile", None)
   │         is_platform_admin = request.user.is_superuser or (profile and profile.is_platform_admin)
   │         request.is_platform_admin = is_platform_admin
   │
   │         IF Platform Admin:
   │            Active tenant resolved from:
   │            1. `request.session.get("active_tenant_id")` (allows cross-tenant switching)
   │            2. `profile.tenant`
   │            3. Fallback: `Tenant.objects.filter(is_active=True).first()`
   │
   │         ELSE (Regular Tenant Users: Owner, Manager, Cashier, Chef, Driver):
   │            1. `profile.tenant`
   │            2. `request.user.employee_profile.tenant`
   │            3. None (request.tenant = None)
   │            -> Regular users CANNOT switch tenants via session; they are strictly hard-bound.
   │
   └── 3. Tenant Suspension Lifecycle (`core/middleware.py:56-91`)
          If `request.tenant and not request.tenant.is_active and not is_platform_admin`:
             Exempt paths: `/logout/`, `/set-language/`, `/admin/`
             If Owner: redirect to `owner_subscription` (or 403 JSON if AJAX/API).
             If Staff/Employee: forced logout, redirect to `/login/?suspended=1` (or 403 JSON).
```

### 1.3 View-Level Tenant Resolution Helper
`get_active_tenant(request)` in `apps/tenants/helpers.py:5-28`:
- Priority 1: `request.tenant` (set by middleware).
- Priority 2: `request.user.profile.tenant`.
- Priority 3: `request.user.employee_profile.tenant`.
- Priority 4: `request.session.get("active_tenant_id")` (only if platform admin / superuser).
- Priority 5: Fallback first active tenant for superusers.
- Returns `None` if unresolvable.

### 1.4 Multi-Tenant Data Isolation Enforcement
- **QuerySet scoping**: Every view and API endpoint restricts database operations strictly using `tenant = get_active_tenant(request)`. Example: `Tenant.objects.get(id=tenant.id)` or `branches = Branch.objects.filter(tenant=tenant)`.
- **Cross-tenant modification prevention**: Object mutations retrieve models by composite primary/tenant keys: e.g., `Order.objects.filter(id=order_id, tenant=tenant)`. Attempts by Tenant A to access or mutate objects belonging to Tenant B resolve to 404 Not Found or 403 Forbidden.
- **Session isolation**: `active_tenant_id` session mutation endpoint `switch_tenant_view` (`apps/tenants/views.py:76`) strictly validates `request.user.is_superuser or profile.is_platform_admin`.

---

## 2. RBAC Architecture & 403 Forbidden Enforcement

### 2.1 Role Hierarchy & Personas
| Role | Model Role Key | JobRole Scope | Typical Default Permissions | Default Login Redirect | HQ Access? |
|---|---|---|---|---|---|
| **Platform Superadmin** | `platform_admin` / superuser | Global | All permissions (`is_superuser=True`) | `/admin/` | Yes |
| **Restaurant Owner** | `owner` | HQ (`scope='hq'`) | Full tenant ownership, all 40 permissions | `dashboard` (HQ) | Yes |
| **HQ General Manager** | `branch_manager` / staff | HQ (`scope='hq'`) | `view_hq_dashboard`, `hq_view_orders`, `manage_branches`, `manage_roles` | `dashboard` (HQ) | Yes |
| **Branch Manager** | `branch_manager` | Branch (`scope='branch'`) | `branch_view_dashboard`, `branch_view_orders`, `branch_edit_orders`, `menu_view`, `inventory_view` | `branch_dashboard` | No |
| **Cashier (POS)** | `cashier` | Branch (`scope='branch'`) | `pos_access`, `pos_create_order`, `pos_reprint_receipt`, `branch_view_orders` | `pos` | No |
| **Kitchen Chef (KDS)**| `chef` | Branch (`scope='branch'`) | `kds_access`, `kds_recall_order`, `kds_pause_item`, `kds_update_status` | `kitchen` | No |
| **Delivery Driver** | `driver` | Branch (`scope='branch'`) | `delivery_access`, `delivery_track_drivers`, `delivery_override_status` | `delivery` | No |
| **Call Center Agent**| `call_center` | HQ (`scope='hq'`) | `call_center_access`, `call_center_create_order`, `call_center_view_customers` | `call_center` | Specific |

### 2.2 Permissions Engine & Native Django Integration
- **Permissions Registry**: `RESTAURANT_PERMISSIONS` (`apps/accounts/models.py:7-65`) defines 40 discrete permissions across POS, KDS, Delivery, Branch Orders, Menu & Pricing, Inventory, HQ Orders, and Call Center.
- **Granular Scope Partitioning**:
  - `BRANCH_PERMISSIONS` (`apps/accounts/models.py:162-170`)
  - `HQ_PERMISSIONS` (`apps/accounts/models.py:172-176`)
  - Strict validation in `api_job_roles` (`apps/accounts/views.py:1149-1156`) blocks assigning HQ permissions to branch-scoped roles and vice versa.
- **Dynamic Group Synchronization**:
  - Every tenant custom role is an instance of `JobRole` (`apps/accounts/models.py:182-280`).
  - Automatically linked 1:1 with standard `django.contrib.auth.models.Group` named `t{tenant_id}_role_{role_id}`.
  - Role permissions are set directly on the backing Django Group via `job_role.set_permissions([...])`.
  - When an `Employee` is created or updated, `employee.user.groups` is updated to the `JobRole.group`, syncing with Django's native authentication system.
- **Unified Permission Check (`user_has_perm`)**:
  - Defined in `apps/accounts/helpers.py:42-130`.
  - Superusers and Owners (`profile.role == "owner"`) bypass checks (always return `True`).
  - For staff, checks:
    1. Native Django check `user.has_perm(f"core.{perm}")`.
    2. Group permissions lookup `user.groups.filter(permissions__codename=perm).exists()`.
    3. `SYNONYM_MAP` resolution (e.g. `manage_branches` <-> `branch_manage_branches`, `view_hq_dashboard` <-> `hq_view_master_dashboard`).
    4. Implied permissions mapping (e.g. `manage_menu` implies `menu_view`).
    5. Self-healing fallback: synchronizes user groups from `JobRole` if out of sync.

### 2.3 403 Forbidden Enforcement Patterns
Across the application, two canonical enforcement patterns are utilized:

#### A. HTML Views Pattern:
```python
if not is_owner and not user_has_perm(request.user, "<required_permission>"):
    return HttpResponseForbidden("غير مصرح لك بالوصول إلى هذه الصفحة")
```
Used in:
- `core/views.py:249`: `dashboard_view` (blocks non-HQ users with `HttpResponseForbidden`)
- `apps/tenants/views.py:179`: `branches_view` (`manage_branches`)
- `apps/accounts/views.py:334`: `employees_view` (`manage_employees`, `hr_view_employees`)

#### B. JSON API Endpoints Pattern:
```python
if not is_owner and not user_has_perm(request.user, "<required_permission>"):
    return JsonResponse({
        "status": "error",
        "error": "غير مصرح لك بتنفيذ هذا الإجراء"
    }, status=403)
```
Used in:
- `apps/tenants/views.py:248`: `api_create_branch`
- `apps/tenants/views.py:698`: `api_update_tenant_branding`
- `apps/accounts/views.py:1098`, `1125`: `api_job_roles`
- `apps/orders/views.py`: `api_cancel_order`, `api_delete_order`

---

## 3. Existing Test Infrastructure & Harness Verification

### 3.1 Verification Runner: `./init.sh`
The repository's official verification script (`init.sh`) executes three consecutive gates with `set -e`:
```bash
#!/bin/bash
set -e
venv/bin/python manage.py check
venv/bin/python test_system.py
venv/bin/python test_e2e_rbac.py
```
Verification baseline: **100% PASS** with 0 warnings/errors.

### 3.2 Test Suites Breakdown
1. **`manage.py check`**:
   - Validates Django system integrity, model relationships, database field configurations, URLconf routing, and settings without hitting DB.
2. **`test_system.py`** (Core Functional CRUD & Workflow Suite):
   - Unauthenticated redirects (302 -> `/login/`).
   - Admin authentication (`admin/admin123`).
   - Authenticated access to core views: `/dashboard/`, `/pos/`, `/call-center/`, `/delivery/`, `/inventory/`, `/branches/`, `/employees/`, `/admin/`.
   - Order creation API (`/api/orders/`, dine_in channel cashier).
   - Customer search API (`/api/customers/search/`).
   - Order status progression (`/api/orders/{id}/` -> preparing).
   - Menu item availability toggle (`/api/menu/toggle/{id}/`).
   - Inventory item stock adjustment (`/api/inventory/adjust/{id}/`).
3. **`test_e2e_rbac.py`** (Multi-Tenant RBAC & Isolation Suite):
   - Section 1: Verifies all 40 `RESTAURANT_PERMISSIONS` registered in `auth_permission`.
   - Section 2: Validates deprecation of preset roles and creation of custom `JobRole` instances with Django `Group` sync.
   - Section 3: User-Group integration testing (`User.has_perm` vs `user_has_perm`).
   - Section 4: Post-login redirect tests across 7 roles (Cashier -> `pos`, Senior Cashier -> `pos`, Chef -> `kitchen`, Driver -> `delivery`, Call Center -> `call_center`, Branch Manager -> `branch_dashboard`, HQ General Manager -> `dashboard`).
   - Section 5: HTTP Client E2E 403 denial verification:
     - Floor Cashier: 200 on `/pos/`, 403 on `/kitchen/`, `/call-center/`, `/employees/`, `/api/orders/{id}/cancel/`, `/api/orders/{id}/delete/`.
     - Senior Cashier: 200 on cancel, 403 on delete.
     - Kitchen Chef: 200 on `/kitchen/`, 403 on `/pos/`.
     - Delivery Driver: 200 on `/delivery/`, 403 on `/pos/`.
     - Call Center Agent: 200 on `/call-center/`, 403 on `/kitchen/`.
     - Branch Manager: 403 on `/employees/`.
     - Owner: 200 on `/employees/`, 200 on `/api/employees/create/`, update role and sync groups.
   - Section 6: Multi-tenant isolation verification: Tenant A manager attempting to cancel Tenant B order returns 403/404.
   - Section 7: Clean-up of test artifacts.
4. **`feature_list.json`**:
   - Master feature tracker. Contains 5 standard lifecycle items (`feat-001` through `feat-005`).

---

## 4. Restaurant Profile Feature: Verification Criteria & Test Patterns

### 4.1 Requirement Alignment
According to `ORIGINAL_REQUEST.md`:
- **R1: HQ Restaurant Profile View and Navigation**
  - Dedicated page in HQ portal (`الإدارة العامة`).
  - Accessible via `_admin_nav_tabs.html` and sidebar (`base.html`).
  - Renders: Restaurant name, bio, phone, email, address, logo (`logo_image`), and cover (`cover_image`).
  - Responsive Tailwind CSS layout supporting RTL (Arabic) & LTR (English).
- **R2: Profile Data & Media Management Endpoints**
  - Backend handlers for retrieving and updating:
    - Basic: `name`, `bio`
    - Contact: `phone`, `email`, `address`
    - Branding: `brand_color`, `logo_image`, `cover_image`
  - Proper validation (valid email format, non-empty name, hex color format, image file validation).
- **R3: Permissions and Multi-Tenant Isolation**
  - Only authenticated users with HQ management permissions (`profile.role == 'owner'` / superuser or HQ Manager) can access and update.
  - Branch staff (`cashier`, `chef`, `driver`, branch-only manager) must receive **HTTP 403 Forbidden**.
  - Updates strictly scope to active authenticated tenant (`get_active_tenant(request)`).
  - Cross-tenant mutations strictly rejected.

### 4.2 Data Model State
`Tenant` model in `apps/tenants/models.py:25-35` already includes all required fields:
```python
name = models.CharField(max_length=255, verbose_name="اسم المطعم / المنشأة")
slug = models.SlugField(max_length=100, unique=True, verbose_name="المعرف اللاتيني (Slug)")
logo_emoji = models.CharField(max_length=20, default="🍽️", blank=True)
logo_image = models.FileField(upload_to="tenant_logos/", blank=True, null=True)
cover_image = models.FileField(upload_to="tenant_covers/", blank=True, null=True)
custom_domain = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
brand_color = models.CharField(max_length=20, default="#0E382A", blank=True)
bio = models.CharField(max_length=255, default="", blank=True)
phone = models.CharField(max_length=50, default="", blank=True)
email = models.EmailField(blank=True, default="")
address = models.CharField(max_length=255, default="", blank=True)
```
No schema migrations are required unless additional fields are requested.

### 4.3 Existing Backend Handler vs Gap Analysis
In `apps/tenants/views.py:686-735`, `api_update_tenant_branding` currently exists:
- **Gap 1**: Only accepts `name`, `bio`, `brand_color`, `logo_emoji`, `logo_image`, `cover_image`. It does **not** handle `phone`, `email`, `address`.
- **Gap 2**: Permission check is:
  `if not is_owner and not user_has_perm(request.user, "manage_menu"): return 403`
  This allows branch menu managers to edit restaurant-wide branding, violating R3! Must be restricted strictly to `is_owner` or users with HQ management permissions (`view_hq_dashboard` / `manage_branches`).
- **Gap 3**: There is currently no dedicated HTML view (e.g. `restaurant_profile_view` at `/profile/` or `/settings/profile/`), nor a template `restaurant_profile.html`.
- **Gap 4**: `_admin_nav_tabs.html` and `base.html` do not yet feature a link to the Restaurant Profile.

### 4.4 Test Verification Matrix & Test Patterns

| Test ID | Test Scenario | Actor / Credentials | Request | Expected Status | Expected Outcome |
|---|---|---|---|---|---|
| **TP-01** | Unauthenticated Page Access | Anonymous | `GET /profile/` | `302 Found` | Redirect to `/login/?next=/profile/` |
| **TP-02** | Unauthenticated API Update | Anonymous | `POST /api/settings/profile/` | `302 Found` or `401/403` | Rejection, no DB mutation |
| **TP-03** | Cashier Access Rejection | Cashier (`role='cashier'`) | `GET /profile/` | `403 Forbidden` | Access denied |
| **TP-04** | Cashier API Update Rejection | Cashier (`role='cashier'`) | `POST /api/settings/profile/` | `403 Forbidden` | JSON error, DB untouched |
| **TP-05** | Kitchen Chef Rejection | Chef (`role='chef'`) | `POST /api/settings/profile/` | `403 Forbidden` | JSON error, DB untouched |
| **TP-06** | Delivery Driver Rejection | Driver (`role='driver'`) | `POST /api/settings/profile/` | `403 Forbidden` | JSON error, DB untouched |
| **TP-07** | Branch Manager Rejection | Branch Manager (no HQ perm) | `POST /api/settings/profile/` | `403 Forbidden` | JSON error, DB untouched |
| **TP-08** | Owner Profile View Access | Restaurant Owner | `GET /profile/` | `200 OK` | Renders HTML with current tenant data |
| **TP-09** | HQ Manager Profile View Access | HQ Manager (`view_hq_dashboard`) | `GET /profile/` | `200 OK` | Renders HTML with current tenant data |
| **TP-10** | Owner Profile Update (Text & Contact) | Restaurant Owner | `POST /api/settings/profile/` | `200 OK` | `name`, `bio`, `phone`, `email`, `address`, `brand_color` updated in DB |
| **TP-11** | Media Asset Upload (Logo & Cover) | Restaurant Owner | `POST /api/settings/profile/` (multipart) | `200 OK` | `logo_image` & `cover_image` saved to media storage |
| **TP-12** | Validation: Empty Restaurant Name | Restaurant Owner | `POST` with `name=""` | `400 Bad Request` | JSON error message |
| **TP-13** | Validation: Invalid Email Address | Restaurant Owner | `POST` with `email="invalid-email"` | `400 Bad Request` | JSON error message |
| **TP-14** | Multi-Tenant Isolation | Owner of Tenant A | `POST /api/settings/profile/` | `200 OK` | Only Tenant A updated; Tenant B strictly unmodified |
| **TP-15** | Cross-Tenant Spoof Prevention | Owner of Tenant A | `POST` with `tenant_id=B.id` | `200 OK` or `403` | Ignores payload tenant ID, modifies ONLY `request.tenant` |
| **TP-16** | System Integrity Pipeline | Automated | `./init.sh` | `Exit Code 0` | All checks & E2E tests pass 100% |

### 4.5 Recommended Test Implementation Structure
To maintain repo layout compliance, the test suite for this feature should be implemented as a dedicated test runner `test_restaurant_profile.py` in the root directory (alongside `test_e2e_rbac.py` and `test_system.py`), and wired into `./init.sh` or integrated into `test_e2e_rbac.py`.

Key test pattern snippet:
```python
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from core.models import Tenant, UserProfile

# Media upload pattern
logo = SimpleUploadedFile("test_logo.png", b"\x89PNG\r\n\x1a\n...", content_type="image/png")
cover = SimpleUploadedFile("test_cover.jpg", b"\xff\xd8\xff...", content_type="image/jpeg")

payload = {
    "name": "مطعم النخيل الجديد",
    "bio": "أشهى المأكولات العربية والخليجية",
    "phone": "0114455667",
    "email": "hq@nakheel-dining.sa",
    "address": "الرياض - حي العليا - شارع التحلية",
    "brand_color": "#0E382A",
    "logo_image": logo,
    "cover_image": cover,
}
client.force_login(owner_user)
response = client.post("/api/settings/profile/", payload)
assert response.status_code == 200
```
