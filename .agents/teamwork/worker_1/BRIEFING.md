# BRIEFING — 2026-10-23T20:34:30Z

## Mission
Implement the Restaurant Profile feature across backend (views, URLs, validation, RBAC) and frontend (template, admin nav tabs, base sidebar, dashboards) with strict tenant isolation and full test verification.

## 🔒 My Identity
- Archetype: worker_1 (full-stack engineer)
- Roles: implementer, qa, specialist
- Working directory: /root/motaem/.agents/teamwork/worker_1
- Original parent: edcd0c06-1ae8-42c0-a1b9-d21bcdbc28d7
- Milestone: Restaurant Profile Feature

## 🔒 Key Constraints
- EXCLUSIVE file write ownership:
  - /root/motaem/apps/tenants/views.py
  - /root/motaem/core/views.py
  - /root/motaem/core/urls.py
  - /root/motaem/templates/restaurant_profile.html
  - /root/motaem/templates/_admin_nav_tabs.html
  - /root/motaem/templates/base.html
  - /root/motaem/templates/dashboard.html
  - /root/motaem/templates/hq_dashboard.html
  - /root/motaem/feature_list.json
- DO NOT touch files owned by worker_2 (e.g. models.py, migrations, tests).
- DO NOT cheat: genuine implementation only, no hardcoded responses or bypasses.
- RBAC: Owner (`is_owner`) and HQ Manager (`view_hq_dashboard` or `system_manage_settings`) allowed. Non-HQ branch staff forbidden (HTTP 403). Unauthenticated redirected to login (HTTP 302).
- Tenant isolation: strictly query and update `get_active_tenant(request)`.
- No Pillow installed: programmatic file validation (size, extension, mime if feasible).

## Current Parent
- Conversation ID: edcd0c06-1ae8-42c0-a1b9-d21bcdbc28d7
- Updated: 2026-10-23T20:34:30Z

## Task Summary
- **What to build**: Restaurant Profile view and API update endpoint with validation, RBAC, tenant isolation, modern responsive Tailwind HTML UI with live image/color preview, admin nav tabs entry, active sidebar state, dashboard links, and feature_list.json updates.
- **Success criteria**: 100% pass on `manage.py check`, `test_system.py`, `test_e2e_rbac.py`, `test_restaurant_profile.py`, and `./init.sh`.
- **Interface contracts**: /root/motaem/PROJECT.md
- **Code layout**: Django standard app layout under `/root/motaem`

## Key Decisions Made
- Created shared validation and persistence helper `_update_tenant_profile_data` in `apps/tenants/views.py` used by both `restaurant_profile_view`, `api_restaurant_profile_update`, and `api_update_tenant_branding`.
- Programmatic file validation checks size (logo <= 2MB, cover <= 5MB) and extensions (.png, .jpg, .jpeg, .webp, .svg) without requiring Pillow.
- Created responsive 2-column Tailwind UI in `templates/restaurant_profile.html` with real-time live preview for uploaded logo, cover, brand color, and restaurant info.
- Secured all profile endpoints with `_can_manage_restaurant_profile(user)` granting access strictly to Owner and HQ Manager (`view_hq_dashboard` or `system_manage_settings`), returning HTTP 403 to branch staff (Cashier, Kitchen, Driver, Branch Manager).

## Artifact Index
- /root/motaem/.agents/teamwork/worker_1/DISPATCH.md — Assignment instructions
- /root/motaem/.agents/teamwork/worker_1/progress.md — Liveness & progress log
- /root/motaem/.agents/teamwork/worker_1/handoff.md — 5-component handoff report
- /root/motaem/templates/restaurant_profile.html — Dedicated Restaurant Profile template
- /root/motaem/test_restaurant_profile.py — Opaque-box test suite (59/59 passing)
- /root/motaem/feature_list.json — Feature state tracker

## Change Tracker
- **Files modified**:
  - `apps/tenants/views.py`: added `_can_manage_restaurant_profile`, `_update_tenant_profile_data`, `restaurant_profile_view`, `api_restaurant_profile_update`, updated `api_update_tenant_branding`
  - `core/views.py`: re-exported `restaurant_profile_view` and `api_restaurant_profile_update`
  - `core/urls.py`: registered routes `restaurant/profile/` and `api/restaurant/profile/`
  - `templates/restaurant_profile.html`: created dedicated profile template
  - `templates/_admin_nav_tabs.html`: added Restaurant Profile tab
  - `templates/base.html`: updated sidebar active state and permission check
  - `templates/dashboard.html` & `templates/hq_dashboard.html`: added quick-access profile link
  - `feature_list.json`: updated feature statuses and evidence
- **Build status**: 100% PASS on all suites
- **Pending issues**: None

## Quality Status
- **Build/test result**: PASS (59/59 in `test_restaurant_profile.py`, 8/8 in `test_system.py`, 7/7 in `test_e2e_rbac.py`, 0 issues in `manage.py check`)
- **Lint status**: Clean
- **Tests added/modified**: Full 4-tier coverage verified

## Loaded Skills
None
