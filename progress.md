# Session Progress Log

## Current State

**Last Updated:** 2026-10-27 00:03
**Session ID:** AI Call Center Telephony & SIP Trunk Integration + WhatsApp Branding
**Active Features:** 
- `feat-https-canonical-domain-redirect` (Completed)
- `feat-landing-webrtc-voice-demo` (Completed)
- `feat-landing-navbar-auth` (Completed)
- `feat-landing-bilingual` (Completed)
- `feat-user-subscription-profile` (Completed)
- `feat-post-registration-routing` (Completed)
- `feat-subscription-plan-features-grid` (Completed)
- `feat-kds-standby-redesign` (Completed)
- `feat-pos-dynamic-categories` (Completed)
- `feat-callcenter-telephony-sip-trunks` (Completed)

## Status

### What's Done

- [x] **AI Call Center Telephony & SIP Trunk Integration + WhatsApp Branding (`templates/ai_callcenter/omnichannel.html`, `apps/callcenter/`, `core/partner_service.py`)**
  - **WhatsApp Branding & UI Cleanup**: Removed random emojis across header, badges, status indicators, tabs, and action buttons. Replaced with official WhatsApp brand SVG (`#25D366`) and clean Tailwind iconography.
  - **Central Telephony Partner API Integration**: Implemented backend services in `core/partner_service.py` for PBX trunks, direct SIP trunks, DID assignment, and trunk deletion.
  - **Backend API Endpoints**: Created endpoints in `apps/callcenter/views.py` (`api_ai_callcenter_telephony_info`, `api_ai_callcenter_create_pbx_trunk`, `api_ai_callcenter_delete_pbx_trunk`, `api_ai_callcenter_create_sip_trunk`, `api_ai_callcenter_delete_telephony_trunk`, `api_ai_callcenter_assign_did`) with role-based access control (RBAC) and registered in `apps/callcenter/urls.py` & `core/urls.py`.
  - **Modals & Interactive UX**: Added PBX vs Direct SIP Trunk connect modal, Issabel Asterisk config viewer with 1-click copy for PEER and USER details, and DID number assignment modal.
  - **Comprehensive Verification**: Executed `manage.py check`, `test_system.py`, `test_e2e_rbac.py`, and custom `test_telephony_suite.py` (10/10 PASS). Deployed live with `docker restart motaem_web`.

- [x] **POS Screen Dynamic Categories & Multi-Language Filter (`templates/pos.html` & `apps/orders/views.py`)**
  - **Dynamic `MenuCategory` Integration**: Replaced hardcoded category list with tenant-scoped dynamic query (`MenuCategory.objects.filter(tenant=tenant, is_active=True).order_by("ordering", "id")`).
  - **Fixed Category Resurrection Bug**: Protected soft-deleted categories from being re-activated on page load when a tenant deletes/deactivates categories.
  - **Optimized Database Writes**: Replaced per-item database updates during GET requests with single `bulk_update` backfilling `category_rel`.
  - **Category-aligned Item Ordering**: Ordered menu items by `category_rel__ordering, category_rel__id, category, name` to match category pill order.
  - **Swipeable Horizontal Ribbon**: Implemented non-wrapping horizontally scrollable category ribbon (`overflow-x-auto max-w-full flex-nowrap scrollbar-none`) preventing UI height jumps on touchscreens.
  - **Normalized Search & Bilingual Filter**: Added Arabic normalization (unifying alef, taa marbuta, and stripping diacritics) for search queries, matching name, English name, and category name simultaneously.
  - **Full Bilingual RTL/LTR Support**: Added dynamic RTL (`border-r-4 text-right`) and LTR (`border-l-4 text-left`) styling on dish cards, localized modal labels, and bilingual toast notifications.
  - **Verified & Live Container Restart**: Successfully verified with `./init.sh`, `manage.py check`, `test_system.py`, `test_e2e_rbac.py`, and verified on live container `motaem_web` for tenant 77.
  - **Pure Non-Interactive UI**: Kept the standby screen clean and distraction-free without extra buttons, as explicitly requested.
  - **100% Bilingual Support (Arabic & English)**: Translated all kitchen interface elements, top toolbar buttons, search placeholder, category station pills, empty state headlines, ticket card actions, timers (`m`/`د`), order types, and SSE toasts according to `CURRENT_LANG`. Added missing entries to `core/i18n_catalog.py`.
  - **Bugfixes & Robustness**:
    - Protected `#badge-station-all` from being wiped to 0 or hidden in category loop.
    - Added `pendingRemovalOrders` set to eliminate double-removal and duplicate toast flicker during concurrent SSE status events.
    - Added specific empty state copy when search query returns no matches.
    - Added bidirectional fullscreen UI sync and icon state toggle.
  - **Seamless JavaScript Transitions**: Handled instant transition between Standby Hero and Orders Grid upon receiving new SSE orders or completing all orders, updating station-specific idle headings when filtered by station.
  - **Verified & Deployed**: All 5 suites in `scratch/test_kitchen_standby.py` passed 100%, `./init.sh` passed 100%, and verified live deployment on `https://uggu.space/kitchen/`.

- [x] **SubscriptionPlan Admin Features Grid Checkboxes (`/admin/core/subscriptionplan/`)**
  - Converted raw textarea `JSONField` for `features` in Django Admin / Jazzmin into a responsive Grid Cards layout with interactive checkboxes.
  - Aligned catalog in `apps/billing/models.py` (`AVAILABLE_FEATURES`) with the 8 approved features, merging Call Center & AI Voice under `call_center` ("الكول سنتر ومساعد الذكاء الاصطناعي (AI Voice)").
  - Implemented `SubscriptionPlanAdminForm` with `MultipleChoiceField` and custom `FeatureCardsCheckboxSelectMultiple` widget.
  - Hardened widget against unhashable dictionary and scalar inputs (`TypeError: unhashable type: 'dict'`), parsing dictionary truthy keys and JSON strings safely.
  - Hardened `SubscriptionPlanAdminForm.__init__` against non-iterable integers/booleans (`TypeError: 'int' object is not iterable`), gracefully defaulting to empty list and filtering dictionary truthy keys.
  - Implemented automatic legacy key normalization in `__init__` (mapping `pos_billing`, `kds_kitchen`, `inventory_mgmt`, `delivery_zones`, `manage_roles`, `ai_call_center`, `basic_reports` to their canonical keys).
  - Implemented `clean_features` to persist the selected checkboxes as a clean Python JSON list without schema migration.
  - Created custom widget template `templates/admin/billing/widgets/feature_cards_select.html` featuring:
    - Selected features counter badge with Bidi-safe RTL formatting (`الميزات المفعلة: X من 8`).
    - Quick actions: "تحديد الكل" (Select All) and "إلغاء التحديد" (Deselect All) with native `change` event dispatch for form-change detection.
    - Grid layout with distinctive feature icons, key badge, bold title, descriptive subtitle, and active status pill.
    - Full dark-mode support matching Jazzmin's Slate theme.
    - Click-to-toggle card behavior with live counter synchronization.
  - Added Arabic pluralization rules in `SubscriptionPlanAdmin.features_count_display` (0 features: 'لا توجد ميزات', 1: 'ميزة واحدة', 2: 'ميزتان', 3-10: 'X ميزات').
  - Added layout rules in `static/css/jazzmin_custom.css` so feature cards span the full tab width.
  - Verified 100% via unit and integration test `scratch/test_admin_subscriptionplan_features.py` (6 suites) and `./init.sh`.

- [x] **R0: HTTPS & Canonical Domain Enforcement (`uggu.space`)**
  - Configured Traefik gateway middleware `motaem-canonical-redirect` to permanently redirect (308) all HTTP, direct IP (`169.58.32.179`), and `www.uggu.space` traffic to `https://uggu.space/{path}`.
  - Resolved browser "Secure Context" restriction, allowing microphone access and LiveKit WebRTC streaming without security warnings.
  - Rebuilt and stabilized Docker container with `django-jazzmin` installed, connected to `motaem_motaem_network`.
  - Verified 100% via automated HTTP checks across all entry routes.


- [x] **R1: Partner WebRTC Voice Session (`POST /clients/{client_id}/calls/webrtc/`)**
  - Added `initiate_webrtc_call` in `core/partner_service.py` to communicate directly with the Voice AI partner platform.
  - Generates LiveKit encrypted token, room credentials, and binds active restaurant agent profile.
  - Exposed `/api/webrtc/session/` proxy view in `apps/callcenter/views.py` and routed in `core/urls.py` with rate limiting and tenant binding.
- [x] **R2: In-Page Stepper Auth Modal (Zero Page Reload)**
  - Implemented 2-step registration stepper modal: Step 1 (Restaurant Info) -> Step 2 (Account Info & Phone).
  - Quick tab toggle to Instant Login for existing users.
  - Updated `register_view` and `login_view` in `apps/accounts/views.py` to seamlessly handle JSON/AJAX requests with session persistence and error handling.
  - Auto-provisions restaurant on partner platform upon registration via `ensure_tenant_registered(tenant)`.
- [x] **R3: Glassmorphic WebRTC Voice Call Modal (LiveKit WebRTC)**
  - Built `static/js/landing_webrtc_agent.js` with dynamic LiveKit JS loader and fallback.
  - Web Audio API (`AnalyserNode`) real-time audio wave equalizer bars animating on microphone input and AI voice speech.
  - Integrated 5-minute call countdown timer, Mute/Unmute microphone toggle, and End Call action.
- [x] **R4: Post-Call Experience on Landing Page**
  - Keeps visitor on landing page with call summary statistics (call duration, connection quality).
  - Provides dual actions: "إعادة الاتصال / تجربة مكالمة جديدة" and "الانتقال إلى لوحة التحكم وإكمال إعداد مطعمك".
- [x] **R5: Verification & E2E Testing**
  - Django system check: 0 issues.
  - End-to-end AJAX registration -> tenant voice provisioning -> LiveKit WebRTC token generation test: 100% verified.
  - Regression check: `test_system.py` and `test_e2e_rbac.py` pass 100%.


- [x] **R1: Landing Page Navbar Simplification & Auth States**
  - Removed content anchor tabs (`#features`, `#pos-kds`, `#ai-phone`, `#pricing`, `#faq`) from desktop navbar and mobile drawer while preserving all body sections.
  - Implemented Guest Visitor state: Language Switcher (`عربي / EN`), Sign In (`/login/`), Start Free CTA (`/register/`).
  - Implemented Authenticated state: Replaces guest buttons with Dashboard (`/dashboard/`) and Profile (`/profile/`), plus Language Switcher.
  - Excluded landing page from dashboard sidebar layout (`base.html`) when authenticated, so landing page renders its dedicated public navbar.
- [x] **R2: 100% Bilingual Landing Page (Full Arabic & Full English)**
  - Audited and translated all text, badges, stats, feature cards, pricing cards, and FAQ items in `templates/landing.html`.
  - Added new bilingual keys to `core/i18n_catalog.py`.
  - Seamless layout direction switching (`dir="rtl"` for Arabic, `dir="ltr"` for English).
  - Preserved instant language toggle with `set_language_view` redirection back to current page.
- [x] **R3: Comprehensive User & Subscription Profile Page**
  - Integrated dedicated Profile page accessible at `/profile/` and `/user/profile/` (aliasing `owner_subscription_view`).
  - Added `@login_required` to `owner_subscription_view` with 403 enforcement for non-owner staff.
  - Added Account & Restaurant Overview section showing identity, contact, slug, and management credentials.
  - Rendered Active Plan Card (name, billing cycle, status, renewal date).
  - Displayed visual progress bars for branches and employees against plan caps.
  - Maintained plan upgrade modal for requesting plan upgrades.
  - Added prominent Primary CTA "الدخول إلى لوحة العمليات / Enter Dashboard" routing directly to `/dashboard/`.
- [x] **R4: Post-Registration Routing**
  - Updated `/register/` post-signup redirect to `/profile/`.
  - Fixed latent bugs in `register_view` (`NameError: name 'slugify' is not defined` and missing `timedelta` import).
- [x] **Verification & Test Harness**
  - Created comprehensive test suite `test_landing_and_profile.py` verifying all 5 test suites.
  - Integrated `test_landing_and_profile.py` into `./init.sh`.
  - `./init.sh` and `test_restaurant_profile.py` pass 100%.

### Evidence of Completion

- `./init.sh` passes 100% with exit code 0:
  - `venv/bin/python manage.py check`: System check identified no issues (0 silenced).
  - `venv/bin/python test_system.py`: ALL VERIFICATION TESTS PASSED SUCCESSFULLY! 100% WORKING.
  - `venv/bin/python test_e2e_rbac.py`: ALL END-TO-END RBAC & PERMISSION TESTS PASSED PERFECTLY! (100%).
  - `venv/bin/python test_landing_and_profile.py`: ALL TESTS PASSED SUCCESSFULLY! 100% VERIFIED.
- `venv/bin/python test_restaurant_profile.py`: 59/59 test cases passed (100% PASS).

## Adversarial Review (Round 1) Notes
- **Fixed template filter bug**: Resolved invalid `{{ max_branches|add:"-"|add:branches_count }}` that was failing silently and rendering empty string `متاح  فروع` on `/profile/`. Computed `remaining_branches` and `remaining_employees` in backend (`apps/billing/views.py`) and rendered accurately.
- **Fixed English pricing leakage**: In `templates/landing.html`, dynamic pricing cards now translate plan names and descriptions based on `plan.code` when in English mode, preventing Arabic DB names from leaking into the English landing page, and ensuring CTA buttons render `Start Free Trial`.
- **Fixed brand logo subtext**: Made logo subtitle bilingual (`نظام إدارة المطاعم السحابي` in Arabic, `Cloud Restaurant OS` in English).
- **Made User & Subscription Profile fully bilingual**: Active plan card, quotas progress bars, SaaS feature catalog, plan comparison cards, history table, and upgrade request modal now support complete English rendering with LTR layout when switched to English.
- **Fixed trial subscription status badge**: Resolved issue where trial status fell back to a red/rose warning badge by adding dedicated trial and grace period badge styling (`Free Trial` / `تجريبي`).
- **Enhanced test suite**: Added tests covering remaining quotas display, trial badge, English profile view, and upgrade modal API submission.

## Adversarial Review (Round 2) Notes
- **Fixed Query Parameter Language Activation**: Django's standard `LocaleMiddleware` only inspects session and cookie, ignoring direct `?lang=en` or `?lang=ar` query parameters on fresh visits. Updated `core/context_processors.py` to inspect `request.GET.get('lang')`, activate the translation engine, and persist to session.
- **Fixed Language Redirection Loop**: In `core/views.py` (`set_language_view`), incoming `next_url` containing stale `?lang=` query parameters was stripped and replaced with the newly chosen language parameter, preventing redirection bounce-backs.
- **Eliminated 371 Untranslated Arabic Words on English Profile**:
  - `templates/_admin_nav_tabs.html`: Made all 6 sub-navigation tab headers 100% bilingual (`Restaurant Profile`, `Branches & Locations`, `Dishes & Menu Pricing`, `Inventory & Warehouses`, `Staff & Payroll`, `Subscriptions & Billing`).
  - `templates/owner_subscription.html`: Localized FastMCP table headers, status badges, empty states, copy buttons, modals (`create-key-modal` and `mcp-config-modal`), toast notifications, confirm dialogs, and code comments.
  - `templates/base.html`: Localized live call center nav, sidebar resizer tooltips, notifications tooltip, subscription expiration banners, reset toast, and flyout logout label.
- **Added Modal & Drawer Keyboard Accessibility**: Implemented global `Escape` key listener in `templates/owner_subscription.html` (closing upgrade and FastMCP modals) and `templates/landing.html` (closing mobile navigation drawer).
- **Added Robust Defensive Error Handlers**: In `apps/billing/views.py`, added safe null fallbacks for `tenant.subscription_plan` and bilingual JSON error/success messages in `api_request_upgrade`.
- **Extended Test Suite in `test_landing_and_profile.py`**: Added assertions verifying direct `?lang=en` on clean sessions for `/` and `/profile/`, verifying Escape key listeners in templates, and validating English FastMCP modals. All suites verified via `./init.sh`.

## Adversarial Review (Round 3) Notes
- **Fixed Security Vulnerability: Open Redirect in `set_language_view` (`core/views.py`)**:
  - `set_language_view` only checked `if not next_url.startswith("/")`, allowing scheme-relative URLs (`//evil.com`) and backslash paths (`/\\evil.com`) to redirect externally.
  - Hardened with `django.utils.http.url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure())` and explicit checks for `next_url.startswith("//")` and `next_url.startswith("/\\")`.
- **Fixed Plan Badge Arabic Leak in Sub-Navigation Tabs (`templates/_admin_nav_tabs.html` & `core/context_processors.py`)**:
  - `_admin_nav_tabs.html` checked `tenant_subscription.subscription_plan.code`, but `tenant_subscription` dictionary stored it under `"plan"`, causing the template to silently fall back to raw Arabic database name on `/profile/?lang=en`.
  - Added `plan_name_en` computed with `I18N_CATALOG` fallback and dual-key aliasing (`plan` and `subscription_plan`) in `core/context_processors.py`.
- **Fixed Insecure Context and Blocked Clipboard API (`templates/owner_subscription.html`)**:
  - Added cross-browser `fallbackCopy(text, msg)` using temporary textarea and `document.execCommand('copy')` for non-HTTPS environments and browsers blocking `navigator.clipboard`.
- **Fixed Untranslated Arabic Toasts on English Profile View (`templates/owner_subscription.html`)**:
  - `submitCreateApiKey`, `toggleApiKey`, and `deleteApiKey` evaluated `showToast(data.message || ...)`. Because the API returned Arabic strings, English view displayed Arabic toasts. Localized toast feedback when `isEn` is true.
- **Fixed Bilingual API Errors in `api_request_upgrade` (`apps/billing/views.py`)**:
  - Moved `is_en` detection to the entrypoint of `api_request_upgrade`, returning localized English error strings for 403 Forbidden and 400 Bad Request.
- **Fixed Empty Parentheses in Branch Select Options**:
  - Wrapped `({{ b.city }})` in `{% if b.city %}` to prevent rendering `Branch ()` when city is unset.
- **Extended Test Suite (`test_landing_and_profile.py`)**:
  - Added Suite 3.5 testing open redirect attack payloads.
  - Added Suite 4.9 testing tab badge localization, fallbackCopy presence, bilingual API error responses, and clean modal options.
  - Verified 100% pass across `./init.sh`, `test_system.py`, `test_e2e_rbac.py`, `test_restaurant_profile.py`, and `test_landing_and_profile.py`.
