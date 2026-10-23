# Project: Restaurant Profile Management (Central HQ)

## Architecture
- **Framework**: Django 5.x with multi-tenant architecture.
- **Tenant Isolation**: Resolves active tenant via `TenantMiddleware` (`core/middleware.py`) and `get_active_tenant(request)` (`apps/tenants/helpers.py`).
- **Data Model**: `Tenant` model in `apps/tenants/models.py` (re-exported by `core/models.py`) stores restaurant identity, branding, and contact details. No migrations required.
- **Access Control (RBAC)**: Enforced via `user_has_perm`, user roles (`owner`, `platform_admin`), and `JobRole` scope (`hq`, `both`). Branch staff (`cashier`, `chef`, `driver`, `branch_manager`) restricted with HTTP 403 Forbidden.
- **UI Design System**: Tailwind CSS with custom palette, RTL/LTR support, responsive card layout, live image/color preview, and toast feedback (`showToast`).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Navigation & Tab Integration | Add Restaurant Profile tab to `_admin_nav_tabs.html`, sidebar in `base.html`, and HQ dashboard | M2 | R1 |
| 2 | Dedicated Restaurant Profile View & Template | Render current identity, logo, cover, brand color, and contact details in responsive layout | M2 | R1 |
| 3 | Profile Data Update Handler | Backend handler to update basic (name, bio) and contact (phone, email, address) details | M1 | R2 |
| 4 | Visual Branding & Media Handler | File upload for logo/cover with programmatic validation and hex color update | M1 | R2 |
| 5 | Input Validation & Error Handling | Validates required name, email format, hex color (#RRGGBB), and image size/type limits | M1 | R2 |
| 6 | RBAC Authorization (HQ vs Branch) | Owner and HQ Manager allowed; branch staff (Cashier, Chef, Driver) receive HTTP 403 | M1 | R3 |
| 7 | Authentication Redirect | Unauthenticated requests redirected to login | M1 | R3 |
| 8 | Multi-Tenant Isolation | Changes strictly scoped to `get_active_tenant(request)`; cross-tenant mutation prevented | M1 | R3 |
| 9 | Opaque-Box E2E Test Suite | Comprehensive test suite (Tiers 1-4) covering all features, edge cases, RBAC, and isolation | E2E_TEST | Quality |
| 10 | Final Verification & Harness Integration | 100% test pass on `./init.sh`, `feature_list.json` updated, and adversarial hardening | M3 | Quality |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | E2E_TEST | E2E Test Suite creation (TEST_INFRA.md, test cases Tiers 1-4, TEST_READY.md) | Survey | DONE |
| 2 | M1_BACKEND_RBAC | Backend views, URL routes, input validation, media handlers, RBAC & multi-tenant isolation | Survey | DONE |
| 3 | M2_FRONTEND_UI | Profile template, tab navigation, sidebar links, preview scripts, and form feedback | M1_BACKEND_RBAC (interface) | DONE |
| 4 | M3_FINAL_E2E_VERIFICATION | 100% E2E test pass, feature_list.json update, ./init.sh verification, Tier 5 hardening | E2E_TEST, M1, M2 | DONE |

## Interface Contracts
### View & API Contract: Restaurant Profile
- **Page URL**: `/restaurant/profile/` (name: `restaurant_profile`)
  - **Method**: GET
  - **Auth**: `@login_required`
  - **Permissions**: Owner or HQ Manager (`is_owner or user_has_perm(request.user, "view_hq_dashboard") or user_has_perm(request.user, "system_manage_settings")`)
  - **Response**: HTML rendering `restaurant_profile.html` with context `tenant`, `active_tab='restaurant_profile'`
- **Update Handling**: POST to `/restaurant/profile/` or `/api/restaurant/profile/` (name: `api_restaurant_profile_update`)
  - **Method**: POST (multipart/form-data)
  - **Parameters**:
    - `name` (string, required)
    - `bio` (string, optional)
    - `phone` (string, optional)
    - `email` (string/email, optional)
    - `address` (string, optional)
    - `brand_color` (string, hex `#RRGGBB`, optional)
    - `logo_image` (file, optional, max 2MB, image extensions)
    - `cover_image` (file, optional, max 5MB, image extensions)
  - **Success Response**: Redirect or JSON `{"success": true, "message": "...", "tenant": {...}}`
  - **Error Response**:
    - Non-HQ / Branch staff: HTTP 403 Forbidden
    - Unauthenticated: HTTP 302 Redirect to `/login/`
    - Validation error: HTTP 400 with error details or form error re-render

## Code Layout
- `apps/tenants/views.py`: `restaurant_profile_view`, `api_restaurant_profile_update`
- `core/views.py`: Facade exports for `restaurant_profile_view`
- `core/urls.py`: URL patterns for `restaurant/profile/` and `api/restaurant/profile/`
- `templates/restaurant_profile.html`: Dedicated HQ Restaurant Profile page
- `templates/_admin_nav_tabs.html`: Secondary navigation tab for Restaurant Profile
- `templates/base.html`: Sidebar active state matching for `restaurant_profile`
- `templates/dashboard.html` / `templates/hq_dashboard.html`: Quick-link buttons to profile
- `test_restaurant_profile.py`: Dedicated comprehensive test suite
