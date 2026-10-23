# Handoff Report — Central HQ Portal Architecture & Restaurant Profile Survey

**Agent**: explorer_survey_1  
**Working Directory**: `/root/motaem/.agents/teamwork/explorer_survey_1`  
**Milestone**: Survey frontend architecture and UI structure for Central HQ management portal (الإدارة العامة) for Restaurant Profile integration.

---

## 1. Observation

1. **Central HQ Layout & Base Shell**:
   - `templates/base.html:3`: `<html lang="{{ CURRENT_LANG|default:'ar' }}" dir="{{ DIR|default:'rtl' }}">`
   - `templates/base.html:27-101`: Tailwind CDN configured with custom `brand` / `blue` color palette (violet-600 `#6366F1`, hover `#4F46E5`), `paper` (`#F8FAFC`), `card` (`#FFFFFF`), `ink` (`#0F172A`), `good` (`#16A34A`), `warn` (`#D97706`), `bad` (`#DC2626`).
   - `templates/base.html:127-137`: Standard card class `.card, .classic-card` with `#FFFFFF` background, `border: 1px solid #CBD5E1`, `border-radius: 0.75rem`, `box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03)`.
   - `templates/base.html:192-206`: Standard input class `.input` with `rounded-lg border border-slate-200 outline-none focus:border-violet-500 focus:ring-3 focus:ring-violet-500/15`.
   - `templates/base.html:535`: Fixed toast notification container `<div id="toast-container" class="fixed top-5 left-5 z-50 flex flex-col gap-2 pointer-events-none"></div>`.
   - `templates/base.html:905-924`: Global `showToast(message, type = 'success')` function supporting `'success'` and `'error'` styles.

2. **Sidebar Navigation & Routing**:
   - `templates/base.html:546-804`: `#app-sidebar` with slate-900 `#0F172A` theme.
   - `templates/base.html:723-735`: Link item for General Administration ("الإدارة العامة"):
     ```django
     {% if is_owner or 'manage_branches' in user_perms or 'manage_menu' in user_perms or 'manage_inventory' in user_perms or 'inventory_view' in user_perms or 'manage_employees' in user_perms or 'hr_view_employees' in user_perms or 'system_manage_billing' in user_perms %}
     <div class="nav-item-wrapper relative">
         <a href="{% url 'branches' %}" class="m3-nav-item flex items-center justify-between px-3 py-2.5 rounded-lg transition-all duration-150 group {% if request.resolver_match.url_name in 'branches,branch_menu,inventory,employees,owner_subscription' %}m3-active bg-violet-600/20 text-violet-300 font-semibold border border-violet-500/30 shadow-xs{% else %}text-slate-400 hover:bg-slate-800/60 hover:text-white font-medium border border-transparent{% endif %}">
     ```
   - `restaurant_system/urls.py:29`: `path('', include('core.urls'))`.
   - `core/urls.py:4-35`: URLs for existing HQ management views:
     - Line 8: `path("subscription/", views.owner_subscription_view, name="owner_subscription")`
     - Line 9: `path("hq/orders/", views.hq_orders_view, name="hq_orders")`
     - Line 26: `path("branches/", views.branches_view, name="branches")`
     - Line 27: `path("employees/", views.employees_view, name="employees")`

3. **Secondary HQ Admin Navigation**:
   - `templates/_admin_nav_tabs.html:1-65`: Included across all General Admin templates (`branches.html:29`, `branch_menu.html:7`, `employees.html:6`, `inventory.html:6`, `owner_subscription.html:6`).
   - Contains 5 existing tabs:
     1. `branches` — إدارة الفروع والمواقع
     2. `branch_menu` — قائمة الأطباق والأسعار
     3. `inventory` — جرد المخزون والمستودعات
     4. `employees` — فريق العمل والرواتب
     5. `owner_subscription` — الاشتراكات والتقارير المالية
   - Active tab style: `bg-violet-50 text-violet-700 font-semibold border border-violet-200/60 shadow-xs`.
   - Inactive tab style: `text-slate-600 hover:text-slate-900 hover:bg-slate-100/70 font-medium border border-transparent`.

4. **Branding & Media Inputs in Codebase**:
   - `apps/tenants/models.py:25-36`: `Tenant` model already possesses all needed fields:
     `name` (CharField), `slug` (SlugField), `logo_emoji` (CharField), `logo_image` (FileField to `tenant_logos/`), `cover_image` (FileField to `tenant_covers/`), `brand_color` (CharField, default `#0E382A`), `bio` (CharField), `phone` (CharField), `email` (EmailField), `address` (CharField).
   - `templates/branch_menu.html:586-646`: Existing implementation of `brandingForm` contains:
     - Logo upload with preview `<img>` and fallback placeholder (lines 589-602).
     - Cover banner upload with preview `<img>` (lines 604-618).
     - Color picker input `type="color"` bound to text input with hex code (lines 627-633).
     - JavaScript handler `submitBrandingForm(event)` posting to `/api/settings/branding/` (lines 420-467).
   - `apps/tenants/views.py:685-735`: `api_update_tenant_branding(request)` updates `name`, `bio`, `brand_color`, `logo_emoji`, `logo_image`, `cover_image`, but currently omits `phone`, `email`, and `address`, and checks `not is_owner and not user_has_perm(request.user, "manage_menu")`.

5. **RBAC and Multi-Tenant Isolation**:
   - `apps/accounts/helpers.py:146`: HQ access checks `is_owner or user_has_perm(user, "view_hq_dashboard") or (profile and profile.job_role and profile.job_role.name in ["مدير عام / إدارة عليا", "مشرف عمليات عامة / HQ"])`.
   - `apps/tenants/helpers.py:5-28`: `get_active_tenant(request)` resolves the active authenticated tenant strictly from user profile / employee profile / session.
   - Core permissions in `JobRole`: `system_manage_settings` ('تعديل بيانات المنشأة والهوية والرقم الضريبي واللوجو') and `view_hq_dashboard` ('لوحة الإدارة العامة (HQ)').
   - Verification suite `./init.sh` runs `manage.py check`, `test_system.py`, and `test_e2e_rbac.py` with 100% PASS result.

---

## 2. Logic Chain

1. **Requirement R1 (HQ Restaurant Profile View & Navigation)** requires a dedicated Restaurant Profile view accessible from the central HQ dashboard and navigation bar:
   - Observation 2 & 3 show that all HQ administrative sections live under the "الإدارة العامة" category in `templates/base.html` and are linked via `templates/_admin_nav_tabs.html`.
   - Adding a new tab for Restaurant Profile ("هوية وبيانات المطعم") in `templates/_admin_nav_tabs.html` ensures seamless discoverability across all admin screens without disrupting layout.
   - Updating the sidebar check in `templates/base.html:726` to include `'restaurant_profile'` ensures the "الإدارة العامة" sidebar drawer item remains active when navigating this page.
   - Adding a direct button in `templates/hq_dashboard.html:29-45` links the HQ command toolbar directly to the new view.

2. **Requirement R2 (Profile Data & Media Management Endpoints)** requires updating basic info (`name`, `bio`), contact info (`phone`, `email`, `address`), and visual branding (`brand_color`, `logo_image`, `cover_image`):
   - Observation 4 confirms that `Tenant` model in `apps/tenants/models.py` already includes every single one of these fields.
   - Existing endpoint `api_update_tenant_branding` partially handles branding (`name`, `bio`, `brand_color`, `logo_image`, `cover_image`), but lacks `phone`, `email`, `address`.
   - Creating/enhancing a dedicated endpoint `api_restaurant_profile_update` (or updating `api_update_tenant_branding` and routing `api/restaurant/profile/` to it) will accept `multipart/form-data`, validate all fields, and persist them cleanly.

3. **Requirement R3 (Permissions & Multi-Tenant Isolation)** requires that only HQ Managers or Owners can update profile settings, while branch-locked staff (Cashier, Kitchen, Delivery) receive HTTP 403:
   - Observation 5 confirms `test_e2e_rbac.py` tests strict 403 enforcement for non-HQ roles on `/employees/` and other administrative endpoints.
   - Checking `is_owner or user_has_perm(request.user, "view_hq_dashboard") or user_has_perm(request.user, "system_manage_settings")` in both the view and the API endpoint guarantees strict HTTP 403 denial for Cashiers, Kitchen Chefs, and Drivers.
   - Persisting updates only through `tenant = get_active_tenant(request)` guarantees multi-tenant isolation.

4. **UI Styling Consistency**:
   - Observation 1 & 4 show that using `.card` containers, `.input` controls with `dir="ltr"` on technical inputs, paired color picker/hex inputs, client-side `URL.createObjectURL` image previews, and `showToast` messages perfectly replicates the existing frontend experience.

---

## 3. Caveats

- **Media Storage**: Uploaded files (`logo_image`, `cover_image`) are written to `settings.MEDIA_ROOT` (`tenant_logos/` and `tenant_covers/`). Existing URL routing in `restaurant_system/urls.py:36` serves media via Django's `serve` view in development.
- **Slug Immutability**: The tenant `slug` is used for digital menu routing (`/m/<slug>/`). The profile form should display the slug as a read-only badge to prevent breaking existing QR codes.
- **Color Format**: Brand color is stored as a hex string (e.g., `#0E382A` or `#6366F1`). Validation must ensure a valid 7-character `#RRGGBB` format.

---

## 4. Conclusion

The Central HQ management portal is structured cleanly for the immediate integration of the Restaurant Profile view.
1. **Target View**: `restaurant_profile_view` in `apps/tenants/views.py` (exposed via `core/views.py`), registered at `restaurant/profile/` (named `restaurant_profile`).
2. **Target Template**: `templates/restaurant_profile.html`, extending `base.html` and including `_admin_nav_tabs.html`.
3. **Target Navigation**:
   - Tab in `templates/_admin_nav_tabs.html` with title "هوية وبيانات المطعم".
   - Active URL match in `templates/base.html:726` expanded with `'restaurant_profile'`.
   - Command toolbar link in `templates/hq_dashboard.html`.
4. **Target API Endpoint**: `api/restaurant/profile/` (named `api_restaurant_profile_update`), handling `multipart/form-data` for all 8 required profile fields with strict RBAC (Owner / HQ Manager permitted; branch staff rejected with 403) and multi-tenant isolation.

---

## 5. Verification Method

To independently verify the survey and baseline project integrity:

1. **System and Model Static Check**:
   ```bash
   venv/bin/python manage.py check
   ```
   *Expected*: `System check identified no issues (0 silenced).`

2. **Core Workflows Verification**:
   ```bash
   venv/bin/python test_system.py
   ```
   *Expected*: `ALL VERIFICATION TESTS PASSED SUCCESSFULLY! 100% WORKING.`

3. **End-to-End RBAC Verification**:
   ```bash
   venv/bin/python test_e2e_rbac.py
   ```
   *Expected*: `🎉 ALL END-TO-END RBAC & PERMISSION TESTS PASSED PERFECTLY! (100%)`

4. **Standard Harness Entrypoint**:
   ```bash
   ./init.sh
   ```
   *Expected*: Complete run of all above checks with exit code 0.

5. **Files to Inspect**:
   - `templates/base.html` (lines 723-735: sidebar General Admin entry)
   - `templates/_admin_nav_tabs.html` (lines 1-65: secondary navigation tabs)
   - `templates/hq_dashboard.html` (lines 29-45: HQ toolbar)
   - `apps/tenants/models.py` (lines 25-36: Tenant model fields)
   - `apps/tenants/views.py` (lines 685-735: existing branding handler)
   - `apps/accounts/helpers.py` (lines 60-160: permission resolution and redirect rules)
