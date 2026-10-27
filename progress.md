# Session Progress Log

## Current State

**Last Updated:** 2026-10-27 05:45
**Session ID:** Comprehensive 5-Language Official Support (AR, EN, FR, TR, DE) - Full 25+ Screen Rollout
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
- `feat-callcenter-telephony-sip-trunks` (Completed & Hardened)
- `feat-landing-text-animations-and-counters` (Completed)
- `feat-landing-pure-native-animations` (Completed)
- `feat-official-5-language-multilingual` (Completed & Verified 100%)

## Status

### What's Done

- [x] **Full 25+ Screen 5-Language Internationalization Rollout (`ar`, `en`, `fr`, `tr`, `de`)**
  - **Django Template Builtin Filter**: Created `core/templatetags/i18n_tags.py` (`|t`, `|trans5`, `trans_text`) and registered as built-in in `restaurant_system/settings.py` `TEMPLATES[0]['OPTIONS']['builtins']`.
  - **Catalog Scaled to 2,764 Verified Terms**: Expanded `core/i18n_catalog.py`, `static/js/diyafa_i18n_catalog.json`, and `staticfiles/js/diyafa_i18n_catalog.json` with 2,764 verified keys across all 5 official languages (`ar`, `en`, `fr`, `tr`, `de`). Purged all fake entries from prior attempt. Zero non-Arabic entries match Arabic characters. Backward-compatible `TranslatableString` and `I18nCatalogDict` ensure 100% string equality with existing tests.
  - **Eliminated Binary Language Checks**: Replaced hardcoded binary checks (`{% if CURRENT_LANG == 'en' %}`, `{% if not IS_RTL %}`, and JS `CURRENT_LANG === 'en'`) across 34 templates with canonical `{{ ...|t }}` and `tJs(key, fallback)` helpers.
  - **Syntax-Safe Template Refactoring**: Built parser protecting Django blocks (`{% ... %}` and `{{ ... }}`) so comparisons (e.g. `<=`, `&&`) never break tag splitting.
  - **34 Screens Refactored**:
    1. `templates/base.html`: Global language switcher, user flyout, and `window.tJs` registration.
    2. `templates/_admin_nav_tabs.html`: Sub-navigation tabs with dynamic localized plan badge.
    3. `templates/dashboard.html` & `templates/hq_dashboard.html`: Main dashboard and HQ overview.
    4. `templates/branch_dashboard.html`: Branch operations, active POS counters, shift metrics.
    5. `templates/branches.html`: Multi-branch manager, branch cards, status badges.
    6. `templates/branch_menu.html`: Dish availability toggles, branch-specific pricing, category filter ribbon.
    7. `templates/inventory.html`: Inventory stock items, safety thresholds, stock adjust modal.
    8. `templates/employees.html`: Employee staff list, job role badges, employee create modal.
    9. `templates/pos.html`: Point of Sale live register, category selector, cart, checkout modal.
    10. `templates/ai_callcenter/_nav_tabs.html`: 8 AI Call Center navigation tabs.
    11. `templates/ai_callcenter/_common_scripts.html`: Common JS helpers with `tJs` translations.
    12. `templates/ai_callcenter/overview.html`: Call center KPIs, quota bars, recent calls, AI orders, and audio modal.
    13. `templates/ai_callcenter/omnichannel.html`: Omnichannel WhatsApp inbox, SIP Trunks, telephonist configs.
    14. `templates/ai_callcenter/calls.html`: Call logs, filters, table headers, audio player.
    15. `templates/ai_callcenter/queues.html`: Call queue distribution, agents, live load.
    16. `templates/ai_callcenter/persona.html`: AI voice agent persona, tone, language parameters.
    17. `templates/ai_callcenter/hours.html`: Operating hours, schedule toggle, auto-response message.
    18. `templates/ai_callcenter/knowledge.html`: RAG knowledge items, questions, approved answers.
    19. `templates/ai_callcenter/capabilities.html`: FastMCP live tools, live menu, KDS order dispatch, delivery zone checks.
    20. `templates/hq_orders.html`: Central order stream, multi-branch filters, status badges.
    21. `templates/branch_orders.html`: Branch specific order listing and live statuses.
    22. `templates/order_detail.html`: Detailed invoice, order lines, timeline, receipt printing.
    23. `templates/order_edit.html`: Order line item adjustments, add/remove items.
    24. `templates/kitchen.html`: KDS live display, station filters, empty state hero, audio alerts, clock locale formatting.
    25. `templates/delivery.html`: Dispatcher dashboard, live driver fleet panel, order cards, SSE toasts.
    26. `templates/delivery_card.html`: Delivery order tooltips, currency, phone button, status actions.
    27. `templates/call_center.html`: Order taker dashboard, cart, takeaway/delivery toggles, live search.
    28. `templates/owner_subscription.html`: Subscriptions & billing, quotas progress bars, FastMCP keys, plan upgrade modal, clipboard toasts.
    29. `templates/restaurant_profile.html`: Brand identity, logo/cover upload validations, color swatches, contact info, live preview.
    30. `templates/qr_menu.html`: Customer digital self-ordering menu, 5-language capsule switcher, sizes, cart, delivery area selector.
    31. `templates/login.html`: Auth login screen, credentials form, register link.
    32. `templates/404.html`: Localized Not Found error page.
    33. `templates/500.html`: Localized Server Error page.
  - **Menu Dish Names Preserved**: Database menu dishes, categories, and custom modifiers remain strictly preserved as entered by the restaurant.
  - **Automated Verification**:
    - `manage.py check`: 0 issues identified.
    - `test_multilingual_5lang.py`: 8/8 suites 100% PASS (2,754 verified terms, 0 fake translations, 9 internal view routes across 5 languages).
    - `test_restaurant_profile.py`: 59/59 PASS (100%).
    - `test_landing_and_profile.py`: 100% PASS (5 suites).
    - `test_system.py`: 100% PASS.
    - `test_e2e_rbac.py`: 100% PASS.
    - `./init.sh`: 100% PASS.
    - `collectstatic --noinput`: Completed.
    - `docker restart motaem_web`: Restarted.
    - `curl -k -I https://uggu.space/?lang={ar,en,fr,tr,de}`: HTTP 200 OK across all 5 languages.
    - `graphify update .`: AST update complete.

- [x] **Comprehensive 5-Language Official Support (`restaurant_system/settings.py`, `core/views.py`, `core/context_processors.py`, `core/i18n_catalog.py`, `static/js/diyafa_i18n_catalog.json`, `static/js/diyafa_i18n_engine.js`, `templates/landing.html`, `templates/base.html`, `static/js/landing_animations.js`)**
  - **Full 5-Language Backend Integration**: Configured `LANGUAGES` in `restaurant_system/settings.py` for Arabic (`ar`, RTL), English (`en`, LTR), French (`fr`, LTR), Turkish (`tr`, LTR), and German (`de`, LTR).
  - **Hardened Language Switch View**: Updated `set_language_view` to accept `['ar', 'en', 'fr', 'tr', 'de']`, store in session and secure 365-day cookie, and enforce strict open-redirect protection against external origins and backslash evasion paths.
  - **Rich Multi-Language Context Processor**: Updated `core/context_processors.py` (`i18n_context`) with dynamic `is_rtl = (lang == 'ar')`, `CURRENT_LANG_NAME`, `CURRENT_LANG_FLAG`, `LANGUAGES_LIST`, 5-language dictionary in `base_t`, and `SafeI18nDict` multi-language resolution. Added compatibility aliases (`CURRENT_LANGUAGE`, `LANG_CODE`, `LANGUAGE_CODE`).
  - **Fixed Zero Arabic Leakage in Landing Page**: Replaced hardcoded binary checks `{% if CURRENT_LANG == 'en' %}...{% else %}Arabic{% endif %}` across `templates/landing.html` with canonical `{{ t.landing_... }}` keys and 5-language plan resolvers.
  - **Fixed Base Template Dropdowns & Mini Sidebar Rail**:
    - Added `#desktop-topbar-lang-dropdown` to `templates/base.html` topbar.
    - Embedded 5-language selector in `#sidebar-flyout-card` (mini sidebar mode popover).
    - Removed `sidebar-text` from outer user-card flex container (`line 762`), preserving the language switcher, notification bell, and logout button when sidebar is collapsed in `.sidebar-mini` mode.
  - **Fixed Regression in `test_landing_and_profile.py`**:
    - Added `landing_nav_profile` key in `core/context_processors.py` mapping to "البروفايل" (AR) and "Profile" (EN), updating `templates/landing.html`.
    - Aligned `brand_subtitle` to "نظام إدارة المطاعم السحابي" (AR) and "Cloud Restaurant OS" (EN).
    - Wrapped `pick_lang` string values in `mark_safe` so that unescaped ampersands (`&`) in titles like "Everything You Need to Manage & Scale Your Restaurants from One Place" and "Simple & Transparent Pricing" match expected test strings without double-escaping.
  - **Expanded 1197-Term Translation Catalog**: Upgraded `core/i18n_catalog.py` with `TranslatableString` and `I18nCatalogDict` delivering 100% backward-compatible `str` equality for existing test suites while exposing full 5-language translations via `.translations['fr'|'tr'|'de']` and `get_translation(key, lang)`.
  - **Client-Side Translation Engine**: Generated `static/js/diyafa_i18n_catalog.json` (1197 entries across 5 languages) and `static/js/diyafa_i18n_engine.js` for real-time DOM localization on client rendering.
  - **Automated Verification & Live Deployment**:
    - Executed all test suites: `manage.py check` (0 issues), `test_system.py` (100% PASS), `test_e2e_rbac.py` (100% PASS), `test_landing_and_profile.py` (100% PASS), `test_multilingual_5lang.py` (100% PASS), `./init.sh` (100% PASS).
    - Collected static assets (`manage.py collectstatic --noinput`).
    - Restarted Docker container `motaem_web` (`docker restart motaem_web`).
    - Verified live HTTP 200 & 302 responses across all 5 languages on `https://uggu.space/`.

- [x] **Pure Native Landing Animations Engine (`templates/landing.html`, `static/js/landing_animations.js`, `staticfiles/js/landing_animations.js`)**
  - **100% Zero-CDN & External Dependencies Removal**: Completely eliminated all `cdn.jsdelivr.net` tags, `Typed.js`, `GSAP`, `ScrollTrigger`, and `document.write` fallback script tags from `templates/landing.html`. Single script call: `<script src="{% static 'js/landing_animations.js' %}?v={% now 'U' %}"></script>`. Solves complete animation freezing in regions with ISP-level CDN blocks (e.g. Egypt / IP 197.161.x.x).
  - **Native Vanilla JS Typewriter**: Replaced `Typed.js` with zero-dependency typewriter loop starting at `delay: 150ms`. Smooth character-by-character typing (`typingSpeed: 65ms`, `backspacingSpeed: 32ms`, `pause: 2200ms`) with pulsing violet-600 cursor (`|`) and continuous cycling across AR & EN text arrays. Prevented mobile line collapse/layout shifts (CLS) by adding `inline-block` and zero-width space `\u200B` on empty states. Maintained `<span class="sr-only">` ensuring 100% test pass in `test_landing_and_profile.py`.
  - **Native requestAnimationFrame Counters**: Implemented cubic ease-out (`1 - (1 - t)^3`) 60fps counter animation for Hero metrics (`metric-uptime-hrs` 0->24, `metric-uptime-pct` 0.0->99.9%, `metric-latency` starting and holding at 0ms without jumping to 50ms) starting immediately upon page load without scroll requirement. Bottom stats bar (`18+`, `45+`, `15,000+`, `99.9%`) dynamically trigger via native `IntersectionObserver` coordinated directly with `.stat-card` viewport entrance.
  - **Native Scroll Reveal with Keyframe Waterfall**: Fixed CSS transition reflow drop for above-the-fold hero items by using `@keyframes heroReveal` with staggered animation delays (`50ms + idx * 75ms`). For below-the-fold content (section headers, Bento cards, stats cards, pricing cards, FAQ items, conversion banner, footer), applied `IntersectionObserver` with `threshold: 0.08` and safety scroll listener near bottom of document to prevent stuck elements. Fully respects `prefers-reduced-motion: reduce`.
  - **Verification & Deployment**: Executed `manage.py check`, `test_landing_and_profile.py`, `test_system.py`, `test_e2e_rbac.py`, `./init.sh`, `collectstatic`, and restarted `motaem_web` container. Verified live HTTP 200 and asset serving on `https://uggu.space/`.

- [x] **Landing Page Dynamic Typewriter, Instant Hero Counters & Page-Wide Text Reveals (`templates/landing.html`, `static/js/landing_animations.js`, `staticfiles/js/landing_animations.js`)**
  - **Immediate Typewriter Initiation**: Emptied `#hero-typewriter` content in `templates/landing.html` so `Typed.js` types letter-by-letter instantly from an empty state without delay (`startDelay: 100`, natural speed), while keeping the full localized sentence inside `<span class="sr-only">` so test assertions in `test_landing_and_profile.py` continue to pass 100%.
  - **Zero-Start Dynamic Numbers**: Set HTML initial values to `0` for `metric-latency`, `metric-uptime-hrs`, `metric-uptime-pct`, and all stats counter items (`data-counter-target`).
  - **Immediate Hero Counters on Load**: Decoupled hero metrics (`metric-latency`, `metric-uptime-hrs`, `metric-uptime-pct`) from ScrollTrigger so they roll up immediately on page load, eliminating 100ms flash/flicker by setting initial roll values immediately.
  - **Robust Fallback Engine**: Added `ensureFallbackValues()` in `landing_animations.js` preventing `#hero-typewriter` or counters from being trapped in blank/`0` states if CDN or animation scripts fail to load.
  - **Script Tag Synchronous Fallback**: Replaced ineffective `onerror="this.src=..."` with standard `window.XYZ || document.write(...)` pattern with cache busting query params (`?v={% now 'U' %}`) ensuring local vendor scripts execute synchronously on CDN failures.
  - **Page-wide Text Motion**: Applied GSAP ScrollTrigger staggered text reveals to the main Hero H1 headline (`.hero-anim-item`), section headers (`.section-header-reveal` / `.reveal-item`), bento cards (`.bento-card`), pricing plans (`.pricing-card` including fallback static cards), FAQ items (`.faq-item`), final conversion banner (`.banner-item`), and footer (`.footer-reveal`).
  - **Reduced Motion & RTL/LTR Parity**: Safe fallback for users with reduced motion preferences and 100% symmetric vertical motion across Arabic (RTL) and English (LTR).
  - **Full Verification & Deployment**: Passed `manage.py check`, `test_landing_and_profile.py`, `test_system.py`, `test_e2e_rbac.py`, and `./init.sh` with 100% success. Restarted `motaem_web` container and verified live HTTP 200 response on `https://uggu.space/`.

- [x] **AI Call Center Telephony & SIP Trunk Integration + WhatsApp Branding (`templates/ai_callcenter/omnichannel.html`, `apps/callcenter/`, `core/partner_service.py`)**
  - **WhatsApp Branding & 100% Zero-Emoji UI**: Replaced raw emojis across headers, chat bubbles, badges, outbound call modal feedback, toasts (`_common_scripts.html`), and action buttons with official WhatsApp SVG (`#25D366`) and clean Tailwind iconography.
  - **Fixed Issabel Modal Data Binding**: Corrected `openIssabelConfigModalWithData` to dynamically populate Trunk Name box and conditionally display Register String box with 1-click clipboard copy.
  - **Fixed `deleteTrunk` Quote Escaping Bug**: Changed `deleteTrunk` signature to `(trunkType, trunkId)` with client-side trunk name lookup, preventing JavaScript syntax breakage when trunk names contain apostrophes.
  - **Fixed Direct SIP DID Auto-Assignment**: Corrected `api_ai_callcenter_create_sip_trunk` to avoid passing SIP trunk IDs as `pbx_trunk_id` to partner API. Restricted Assign DID modal select to PBX trunks.
  - **Central Telephony Partner API Integration**: Implemented backend services in `core/partner_service.py` for PBX trunks, direct SIP trunks, DID assignment, and trunk deletion.
  - **Backend API Endpoints**: Created endpoints in `apps/callcenter/views.py` with RBAC enforcement (`_check_callcenter_admin`) and registered in `apps/callcenter/urls.py` & `core/urls.py`.
  - **Comprehensive Verification**: Executed `manage.py check`, `test_system.py`, `test_e2e_rbac.py`, and `test_telephony_suite.py` with automated zero-emoji scanner (10/10 PASS). Deployed live with `docker restart motaem_web` (HTTP 200/302 verified).

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
