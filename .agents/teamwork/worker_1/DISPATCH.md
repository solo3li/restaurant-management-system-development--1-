## 2026-10-23T20:20:26Z
You are worker_1, a full-stack engineer.
Your working directory is: /root/motaem/.agents/teamwork/worker_1
Parent orchestrator directory is: /root/motaem/.agents/teamwork/orchestrator_1

Read:
- /root/motaem/.agents/teamwork/ORIGINAL_REQUEST.md
- /root/motaem/PROJECT.md
- /root/motaem/AGENTS.md
- /root/motaem/.agents/teamwork/explorer_survey_1/handoff.md
- /root/motaem/.agents/teamwork/explorer_survey_2/handoff.md
- /root/motaem/.agents/teamwork/explorer_survey_3/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write ownership:
You EXCLUSIVELY own:
- /root/motaem/apps/tenants/views.py
- /root/motaem/core/views.py
- /root/motaem/core/urls.py
- /root/motaem/templates/restaurant_profile.html
- /root/motaem/templates/_admin_nav_tabs.html
- /root/motaem/templates/base.html
- /root/motaem/templates/dashboard.html
- /root/motaem/templates/hq_dashboard.html
- /root/motaem/feature_list.json

Mission:
Implement the Restaurant Profile feature across backend and frontend per requirements:
1. Backend (`apps/tenants/views.py`, exported in `core/views.py`, mapped in `core/urls.py`):
   - `restaurant_profile_view` at `restaurant/profile/` (name: `restaurant_profile`) and API endpoint `api/restaurant/profile/` (name: `api_restaurant_profile_update`).
   - Authentication: Unauthenticated redirected to `/login/?next=...` (HTTP 302).
   - RBAC: Owner (`is_owner`) and HQ Manager (`view_hq_dashboard` or `system_manage_settings`) permitted (HTTP 200). Branch staff (Cashier, Kitchen, Driver, Branch Manager without HQ perms) strictly forbidden (HTTP 403).
   - Tenant isolation: Fetch and update only `get_active_tenant(request)`.
   - Update handling: Support both standard form POST and JSON/AJAX for `name` (required), `bio`, `phone`, `email` (validate syntax), `address`, `brand_color` (validate hex `#RRGGBB`), `logo_image` (validate <= 2MB, allowed extensions .png,.jpg,.jpeg,.webp,.svg), and `cover_image` (validate <= 5MB, allowed extensions). Note: Pillow is not installed; do programmatic file validation.
   - Also update `api_update_tenant_branding` in `apps/tenants/views.py` to support `phone`, `email`, `address` and enforce proper HQ RBAC.
2. Frontend (`templates/restaurant_profile.html`, `templates/_admin_nav_tabs.html`, `templates/base.html`):
   - Create `templates/restaurant_profile.html` matching design system (Tailwind CSS, RTL/LTR support, responsive 2-column or clean card layout).
   - Display current profile data, logo preview, cover preview, brand color picker + hex input, bio, phone, email, address, and read-only slug badge.
   - Add live preview JS for uploaded logo and cover images, live preview of brand color changes, and form submit handler with toast feedback (`showToast`).
   - Add tab to `templates/_admin_nav_tabs.html` ("هوية وبيانات المطعم").
   - Update `templates/base.html:726` so sidebar active state includes `restaurant_profile`.
   - Add quick access link in `templates/dashboard.html` / `templates/hq_dashboard.html`.
3. Update `feature_list.json` with the Restaurant Profile feature status.
4. Verification:
   Run:
   `venv/bin/python manage.py check`
   `venv/bin/python test_system.py`
   `venv/bin/python test_e2e_rbac.py`
   `./init.sh`
   Confirm 100% pass with zero errors.
5. Document all implementation details and test execution output in `/root/motaem/.agents/teamwork/worker_1/handoff.md` and send completion message to parent.
