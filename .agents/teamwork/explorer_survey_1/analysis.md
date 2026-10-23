# Central HQ Management Portal Frontend Architecture Survey

**Date**: 2026-10-23  
**Target System**: Motaem Cloud Restaurant OS (الإدارة العامة - Central HQ Portal)  
**Survey Scope**: Layout, Navigation, Styling Conventions (Tailwind CSS, RTL/LTR), Component Architecture, Form & Media Previews, Color Pickers, and Restaurant Profile Integration Plan.

---

## 1. Executive Summary

The Central HQ Management Portal (الإدارة العامة) in Motaem operates within a multi-tenant Django web application styled with Tailwind CSS, supporting complete Arabic (RTL) and English (LTR) bilingual operations.

Currently, General Administration features are grouped under the `/branches/` entrypoint and navigated through a shared secondary tab bar (`templates/_admin_nav_tabs.html`). The underlying data model (`Tenant` in `apps/tenants/models.py`) already contains all necessary fields (`name`, `slug`, `bio`, `phone`, `email`, `address`, `brand_color`, `logo_emoji`, `logo_image`, `cover_image`), but lacks a dedicated, unified Restaurant Profile page in the HQ portal.

This survey establishes the complete blueprint for integrating the dedicated **Restaurant Profile (هوية وبيانات المطعم)** view and update endpoint with zero architectural friction.

---

## 2. Central HQ Portal Layout & Navigation Hierarchy

### 2.1 Base Layout (`templates/base.html`)
- **Shell Structure**:
  - Global `<html>` tag dynamically bound to `lang="{{ CURRENT_LANG|default:'ar' }}"` and `dir="{{ DIR|default:'rtl' }}"`.
  - Body has `#F8FAFC` background (`bg-paper`), dark slate typography (`text-ink`, `#0F172A`), and font family `IBM Plex Sans Arabic`, `Cairo`, `Inter`.
  - Global `#toast-container` fixed at `top-5 left-5` powered by global `showToast(message, type)` function (lines 905-924).
  - Main content container `#main-content` styled with responsive margin to clear sidebar (`mr-0 md:mr-72` in RTL; `ml-0 md:ml-72` in LTR).

### 2.2 Enterprise Dark Sidebar (`#app-sidebar` in `templates/base.html`)
- **Sidebar Width**: 288px (`w-72`), collapsible to mini mode (80px, `sidebar-mini`) on desktop and hidden behind backdrop on mobile.
- **Brand Cartouche (Lines 556-599)**:
  - Links to `{% url 'dashboard' %}` when `is_hq_mode` is active; otherwise `{% url 'branch_dashboard' %}`.
  - Displays restaurant symbol icon, brand name, and violet `HQ` badge (`bg-violet-500/20 text-violet-300`).
- **Sidebar Link for General Administration (Lines 723-735)**:
  - Route: `{% url 'branches' %}`.
  - Active check: `{% if request.resolver_match.url_name in 'branches,branch_menu,inventory,employees,owner_subscription' %}`.
  - Label: `t.nav_general_admin` ("الإدارة العامة" / "General Admin").
  - SVG Icon: Briefcase/Office icon (`M20 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2z M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16`).

### 2.3 Secondary Navigation Bar (`templates/_admin_nav_tabs.html`)
Included at the top of all HQ administrative pages (`branches.html`, `branch_menu.html`, `inventory.html`, `employees.html`, `owner_subscription.html`):
- Container: `<div class="border-b border-slate-200/60 pb-3 mb-5 font-sans"><div class="flex items-center gap-1.5 overflow-x-auto text-xs whitespace-nowrap ...">`
- Tab Items:
  1. `branches` — إدارة الفروع والمواقع (Branches & Locations)
  2. `branch_menu` — قائمة الأطباق والأسعار (Menu & Pricing)
  3. `inventory` — جرد المخزون والمستودعات (Stock & Inventory)
  4. `employees` — فريق العمل والرواتب (Staff & Payroll)
  5. `owner_subscription` — الاشتراكات والتقارير المالية (Subscriptions & Billing)
- Active Tab Styling:
  `bg-violet-50 text-violet-700 font-semibold border border-violet-200/60 shadow-xs`
- Inactive Tab Styling:
  `text-slate-600 hover:text-slate-900 hover:bg-slate-100/70 font-medium border border-transparent`

### 2.4 HQ Dashboard Toolbar (`templates/hq_dashboard.html`)
- Top Command Toolbar (lines 29-45) houses quick navigation buttons for Currency modal, Orders archive (`{% url 'hq_orders' %}`), and Branches (`{% url 'branches' %}`).
- Prime candidate for a direct shortcut button to the Restaurant Profile.

---

## 3. Existing Frontend Styling Conventions

### 3.1 Tailwind CSS Configuration
Tailwind is loaded via CDN (`cdn.tailwindcss.com`) with custom palette extensions in `templates/base.html`:
- **Brand / Violet**:
  - `brand-50` / `blue-50`: `#F5F3FF` (Luminous surface)
  - `brand-100` / `blue-100`: `#EDE9FE` (Active item bg)
  - `brand-200` / `blue-200`: `#DDD6FE` (Subtle boundary)
  - `brand-500`: `#818CF8`
  - `brand-600` / `blue-600`: `#6366F1` (Primary CTA & buttons)
  - `brand-700` / `blue-700`: `#4F46E5` (Hover states)
- **Surfaces & Neutral Text**:
  - `paper`: `#F8FAFC`
  - `card`: `#FFFFFF`
  - `ink`: `#0F172A`
  - `ink-soft`: `#475569`
  - `soft`: `#64748B`
  - `line`: `#E2E8F0`
- **State Colors**:
  - Good/Success: `good-50` (`#F0FDF4`), `good-600` (`#16A34A`), `good-700` (`#15803D`)
  - Warning/Pending: `warn-50` (`#FFFBEB`), `warn-600` (`#D97706`), `warn-700` (`#B45309`)
  - Danger/Error: `bad-50` (`#FEF2F2`), `bad-600` (`#DC2626`), `bad-700` (`#B91C1C`)

### 3.2 Standard Component Patterns
| Component | Existing Class Pattern | Reference File |
|---|---|---|
| Card Container | `bg-white rounded-xl border border-slate-200/70 p-4 sm:p-5 shadow-xs` | `branches.html:59`, `owner_subscription.html:68` |
| Form Input | `.input` (`w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-violet-500 focus:ring-3 focus:ring-violet-500/15`) | `base.html:192-206` |
| Primary CTA Button | `bg-violet-600 hover:bg-violet-700 text-white font-semibold rounded-lg px-3.5 py-1.5 text-xs transition shadow-xs cursor-pointer` | `branches.html:49`, `hq_dashboard.html:38` |
| Secondary Toolbar Button | `rounded-lg border border-slate-200/70 bg-white hover:bg-slate-100 text-slate-900 px-3 py-1.5 text-xs font-bold transition flex items-center gap-1.5 cursor-pointer shadow-xs` | `branches.html:40` |
| Section Badges | `inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-medium bg-violet-50 text-violet-700 border border-violet-200/60` | `hq_dashboard.html:14` |
| Toast Notification | `showToast(message, 'success' \| 'error')` | `base.html:905` |

### 3.3 RTL / LTR Architecture
- `core/context_processors.py` provides:
  - `CURRENT_LANG`: `'ar'` or `'en'`
  - `IS_RTL`: `True` when Arabic, `False` when English
  - `DIR`: `'rtl'` or `'ltr'`
  - `ALIGN_START`: `'right'` (RTL) / `'left'` (LTR)
  - `ALIGN_END`: `'left'` (RTL) / `'right'` (LTR)
  - `t`: Safe translation dictionary backed by `core/i18n_catalog.py`
- LTR Enforcement: Technical fields (`phone`, `email`, `brand_color`, `slug`, `custom_domain`) must explicitly use `dir="ltr"` to ensure left-to-right number/text ordering in an RTL interface.

---

## 4. Media Upload & Visual Branding Conventions

### 4.1 Image Preview Patterns
Examined in `branch_menu.html` (lines 588-618 & 732-745):
- **Logo Upload & Preview**:
  - Container: `w-16 h-16 rounded-2xl bg-slate-50 border border-slate-200 flex items-center justify-center overflow-hidden flex-shrink-0 shadow-xs relative`
  - Fallback: Current emoji (`{{ tenant.logo_emoji|default:"🍽️" }}`) or initials badge.
  - Image element: `<img id="logoPreviewImg" src="{% if tenant.logo_image %}{{ tenant.logo_image.url }}{% endif %}" class="w-full h-full object-cover {% if not tenant.logo_image %}hidden{% endif %}">`
- **Cover Banner Upload & Preview**:
  - Container: `w-full h-32 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center overflow-hidden relative shadow-xs`
  - Image element: `<img id="coverPreviewImg" src="{% if tenant.cover_image %}{{ tenant.cover_image.url }}{% endif %}" class="w-full h-full object-cover {% if not tenant.cover_image %}hidden{% endif %}">`
- **Client-Side Live Preview Script**:
  - When a user chooses a file, read through `URL.createObjectURL(file)` to immediately update the `<img>` tag without waiting for server response:
    ```javascript
    function handleFilePreview(input, imgId, placeholderId) {
        if (input.files && input.files[0]) {
            const url = URL.createObjectURL(input.files[0]);
            const img = document.getElementById(imgId);
            const placeholder = document.getElementById(placeholderId);
            if (img) { img.src = url; img.classList.remove('hidden'); }
            if (placeholder) { placeholder.classList.add('hidden'); }
        }
    }
    ```

### 4.2 Color Picker Pattern
Examined in `branch_menu.html` (lines 627-633):
- Dual input pairing:
  1. `<input type="color" id="brandColorPicker" name="brand_color" value="{{ tenant.brand_color|default:'#6366F1' }}" class="w-10 h-9 p-0.5 rounded-lg border border-slate-200 cursor-pointer bg-transparent">`
  2. `<input type="text" id="brandColorHex" value="{{ tenant.brand_color|default:'#6366F1' }}" class="input text-xs font-mono font-bold w-full uppercase" dir="ltr" maxlength="7">`
- Bidirectional event binding:
  - Color picker `input` updates the hex text field and live preview swatch.
  - Hex text input `input` validates regex (`/^#[0-9A-Fa-f]{6}$/`) and synchronizes the color picker and swatch.
- Preset Quick Palette:
  - Clickable pill swatches for fast selection (e.g., `#6366F1` Indigo, `#0E382A` Classic Emerald, `#0284C7` Sky Blue, `#DC2626` Crimson, `#D97706` Amber Gold, `#1E293B` Slate).

---

## 5. Security & RBAC Enforcement

### 5.1 Permission Scopes
From `apps/accounts/helpers.py`, `core/context_processors.py`, and `test_e2e_rbac.py`:
- **Allowed Roles for Profile Updates**:
  1. Platform Superuser / Admin (`request.user.is_superuser` or `profile.is_platform_admin`)
  2. Restaurant Owner (`profile.role == "owner"`)
  3. HQ General Manager / Operations Supervisor (`user_has_perm(request.user, "view_hq_dashboard")` or `user_has_perm(request.user, "system_manage_settings")`)
- **Forbidden Roles (Must receive HTTP 403 Forbidden)**:
  - Branch-locked staff: Floor Cashier (`pos_access`), Senior Cashier (`pos_cancel_order`), Kitchen Chef (`kds_access`), Delivery Driver (`delivery_access`).
  - Branch Manager without HQ permissions (`branch_dashboard` only).

### 5.2 Multi-Tenant Isolation
- Tenant resolution strictly through `get_active_tenant(request)`:
  - Mutating operations (`POST`) must exclusively write to `tenant = get_active_tenant(request)`.
  - Modification across tenants is strictly prevented (HTTP 403/404).

---

## 6. Recommended Architecture for Implementation

### 6.1 URL Routing
- **Page View**:
  - `path("restaurant/profile/", views.restaurant_profile_view, name="restaurant_profile")` in `core/urls.py` and `apps/tenants/urls.py`
  - Alias: `path("profile/", views.restaurant_profile_view, name="restaurant_profile_alias")`
- **Data & Media Management Endpoint**:
  - `path("api/restaurant/profile/", views.api_restaurant_profile_update, name="api_restaurant_profile_update")`
  - Supporting both `multipart/form-data` (file uploads) and JSON payloads.
  - Form fields handled: `name`, `bio`, `phone`, `email`, `address`, `brand_color`, `logo_emoji`, `logo_image`, `cover_image`.

### 6.2 Template Implementation (`templates/restaurant_profile.html`)
- Extends `base.html`.
- Includes `_admin_nav_tabs.html` at the top.
- Structure:
  - **Header Bar**: Breadcrumb (`الإدارة العامة (HQ) / هوية وبيانات المطعم`), Title, Subtitle, "حفظ التغييرات" primary CTA, and "معاينة المنيو الرقمي" secondary link.
  - **Two-Column Responsive Grid**:
    - **Column 1: Identity & Contact Form**:
      - Card 1: *المعلومات الأساسية* (Name [required], Bio / Tagline, Identifier slug [read-only badge])
      - Card 2: *بيانات التواصل والمقر الرئيسي* (Phone, Email, Physical HQ Address)
    - **Column 2: Visual Assets & Live Preview**:
      - Card 3: *الهوية البصرية والألوان* (Brand color picker + quick swatches, Logo upload + square preview, Cover banner upload + wide preview)
      - Card 4: *المعاينة الحية للمنشأة (Live Card Preview)* (Interactive mock card rendering logo, cover banner, brand color highlights, name, bio, and contact chips in real time).

### 6.3 Navigation Bar Integration
1. In `templates/_admin_nav_tabs.html`:
   Insert the "هوية وبيانات المطعم" tab:
   ```django
   {% if is_owner or 'system_manage_settings' in user_perms or 'view_hq_dashboard' in user_perms %}
   <a href="{% url 'restaurant_profile' %}" 
      class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all {% if request.resolver_match.url_name == 'restaurant_profile' %}bg-violet-50 text-violet-700 font-semibold border border-violet-200/60 shadow-xs{% else %}text-slate-600 hover:text-slate-900 hover:bg-slate-100/70 font-medium border border-transparent{% endif %}">
       <svg class="w-4 h-4 shrink-0 text-violet-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
           <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
       </svg>
       <span>هوية وبيانات المطعم</span>
   </a>
   {% endif %}
   ```
2. In `templates/base.html` (line 726):
   Update active URL resolver check:
   ```django
   {% if request.resolver_match.url_name in 'restaurant_profile,branches,branch_menu,inventory,employees,owner_subscription' %}
   ```
3. In `templates/hq_dashboard.html`:
   Add a quick-access button to the command toolbar pointing to `{% url 'restaurant_profile' %}`.

---

## 7. Verification Baseline
- Verification runner: `./init.sh`
- Component tests verified working:
  - `venv/bin/python manage.py check`: 0 issues
  - `venv/bin/python test_system.py`: 100% PASS
  - `venv/bin/python test_e2e_rbac.py`: 100% PASS (172 permissions, all 7 roles tested)
