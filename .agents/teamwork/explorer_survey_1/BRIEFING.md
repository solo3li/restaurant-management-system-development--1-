# BRIEFING — 2026-10-23T20:17:00Z

## Mission
Survey frontend architecture and UI structure for Central HQ management portal (الإدارة العامة) for Restaurant Profile integration.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: /root/motaem/.agents/teamwork/explorer_survey_1
- Original parent: edcd0c06-1ae8-42c0-a1b9-d21bcdbc28d7
- Milestone: survey Central HQ management portal frontend architecture

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Deliver findings in analysis.md and handoff.md in working directory
- Caveman style for messages; technical payload verbatim

## Current Parent
- Conversation ID: edcd0c06-1ae8-42c0-a1b9-d21bcdbc28d7
- Updated: 2026-10-23T20:17:00Z

## Investigation State
- **Explored paths**:
  - `templates/base.html` (layout, sidebar, Tailwind setup, global toast, RTL/LTR)
  - `templates/_admin_nav_tabs.html` (General Admin secondary navigation tabs)
  - `templates/hq_dashboard.html` (Central HQ command center toolbar)
  - `templates/branch_menu.html` (existing branding modal, color picker, image previews)
  - `templates/branches.html`, `templates/owner_subscription.html` (card patterns, layouts)
  - `apps/tenants/models.py` (Tenant model fields: name, bio, phone, email, address, brand_color, logo_image, cover_image)
  - `apps/tenants/views.py` (api_update_tenant_branding)
  - `apps/accounts/helpers.py`, `core/context_processors.py` (RBAC, user_has_perm, RTL/LTR context)
  - `core/urls.py`, `restaurant_system/urls.py` (URL routing patterns)
  - `./init.sh`, `test_system.py`, `test_e2e_rbac.py` (100% PASS verification baseline)
- **Key findings**:
  - `Tenant` model already has all required fields.
  - General Admin tabs in `_admin_nav_tabs.html` provide natural, seamless integration for Restaurant Profile tab.
  - Sidebar check in `base.html` line 726 needs `'restaurant_profile'` to keep "الإدارة العامة" drawer item active.
  - Form & preview conventions: `.card`, `.input` with `dir="ltr"` for technical fields, paired `<input type="color">` and hex input, instant client-side preview via `URL.createObjectURL`.
  - RBAC: Owner / HQ Manager (`view_hq_dashboard` or `system_manage_settings`) permitted; branch-locked staff (Cashier, Kitchen, Driver) receive HTTP 403; `get_active_tenant(request)` preserves tenant isolation.
- **Unexplored areas**: None for survey scope. Ready for handoff.

## Key Decisions Made
- Fully documented architecture survey in `analysis.md` and `handoff.md`.
- Recommended URL: `restaurant/profile/` (`name="restaurant_profile"`) and API endpoint `api/restaurant/profile/` (`name="api_restaurant_profile_update"`).
- Recommended template: `templates/restaurant_profile.html` extending `base.html` and including `_admin_nav_tabs.html`.

## Artifact Index
- `/root/motaem/.agents/teamwork/explorer_survey_1/DISPATCH.md` — Incoming task dispatch log
- `/root/motaem/.agents/teamwork/explorer_survey_1/BRIEFING.md` — Situational awareness and working memory
- `/root/motaem/.agents/teamwork/explorer_survey_1/progress.md` — Liveness heartbeat
- `/root/motaem/.agents/teamwork/explorer_survey_1/analysis.md` — Detailed frontend architecture survey
- `/root/motaem/.agents/teamwork/explorer_survey_1/handoff.md` — 5-Component self-contained handoff report
