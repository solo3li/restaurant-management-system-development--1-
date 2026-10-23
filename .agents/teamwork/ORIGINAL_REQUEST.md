# Original User Request

## 2026-10-23T20:07:56Z

Build a dedicated Restaurant Profile page in the Central HQ management portal (الإدارة العامة) allowing authorized managers to manage restaurant identity, visual branding, and contact details.

Working directory: /root/motaem
Integrity mode: development

## Requirements

### R1. HQ Restaurant Profile View and Navigation
Create a dedicated Restaurant Profile view accessible from the central HQ dashboard and navigation bar. The interface must display the restaurant's current identity details, visual assets (Logo, Cover), and contact details in a clean, responsive layout matching the existing design system (Tailwind CSS, RTL/LTR support).

### R2. Profile Data and Media Management Endpoints
Implement robust backend handlers to retrieve and update restaurant profile details for the active tenant:
- Basic information: Restaurant name, bio/description.
- Contact information: Phone number, email address, physical headquarters address.
- Visual branding: Primary brand color (with color picker/input), logo image upload, and cover banner upload.
- Proper input validation and error feedback on form submission.

### R3. Permissions and Multi-Tenant Isolation
Ensure strict permission checks (RBAC) and tenant isolation:
- Only authenticated users with HQ management permissions (Restaurant Owner or HQ Manager) can submit profile updates.
- Branch-only staff (Cashier, Kitchen, Delivery Driver) must be forbidden (HTTP 403) from updating HQ restaurant profile settings.
- Profile changes must only affect the active authenticated tenant.

## Verification Resources
- Verification runner script: `./init.sh`
- Existing test suites: `test_system.py`, `test_e2e_rbac.py`
- Django system check: `venv/bin/python manage.py check`

## Acceptance Criteria

### Interface & Navigation
- [ ] Restaurant Profile link is accessible in HQ navigation / sidebar.
- [ ] Page renders current restaurant name, bio, phone, email, address, logo, and cover.

### Functionality & APIs
- [ ] Updating restaurant name, bio, phone, email, or address persists changes to database.
- [ ] Uploading a new logo or cover image saves file and displays updated preview.
- [ ] Brand color selection saves and reflects on the tenant profile.

### Security & RBAC
- [ ] Unauthenticated requests are redirected to login.
- [ ] Non-HQ users attempting to submit profile updates receive HTTP 403 Forbidden.
- [ ] Cross-tenant modification is strictly impossible.

### Quality & Verification
- [ ] Automated test coverage added for profile view and update endpoints.
- [ ] `./init.sh` runs and passes 100% with zero errors.


## 2026-10-23T21:24:43Z

# Teamwork Project Prompt

> Requested team: Small focused team (مطور رئيسي مع مراجع صارم)

This is a single self-contained set of improvements; keep it small and focused. Refactor the Landing Page navbar (removing content tab links while preserving page sections, adding authenticated state with Dashboard and Profile buttons), implement 100% bilingual Arabic/English coverage across the landing page, and create an integrated User & Subscription Profile page with usage progress bars, plan upgrade modal, and post-registration routing.

Working directory: /root/motaem
Integrity mode: development

## Requirements

### R1. Landing Page Navbar Simplification & Auth States
- Remove content anchor tabs (المميزات, الكاشير والمطبخ, كول سنتر AI, باقات الاشتراك, الأسئلة الشائعة) from both desktop navbar and mobile drawer, while keeping all corresponding body sections visible and scrollable.
- Guest Visitors: Show Language Switcher (عربي / EN), "تسجيل الدخول / Sign In", and "ابدأ مجاناً / Start Free" CTA button.
- Authenticated Users (Restaurant Owners / Managers): Hide Sign In / Start Free buttons and display:
  - Button 1: "لوحة الإدارة / Dashboard" linking to `/dashboard/`.
  - Button 2: "البروفايل / Profile" linking to the user/subscription profile page.
  - Language Switcher (عربي / EN).

### R2. 100% Bilingual Landing Page (Full Arabic & Full English)
- Audit and translate all text, badges, headers, stats, feature cards, and FAQ items in `templates/landing.html`.
- Ensure clean dynamic switching between Arabic (RTL) and English (LTR) without page reload issues.
- Preserve instant language toggle with immediate redirection back to the same page.

### R3. Comprehensive User & Subscription Profile Page
- Create/integrate a dedicated Profile Page accessible at `/user/profile/` or `/profile/` (or enhancing owner subscription view) containing:
  - Account and Restaurant overview.
  - Active Plan Card: Current plan name, billing cycle (monthly/yearly), status (active/trial/grace), and renewal date.
  - Usage Limits with Visual Progress Bars:
    - Active Branches vs Max Allowed Branches.
    - Active Staff/Employees vs Max Allowed Employees.
    - Active SaaS Features checklist.
  - Plan Upgrade Action: "ترقية الباقة / Upgrade Plan" button opening a clean modal to select a higher plan and submit an upgrade request.
  - Prominent Primary CTA: "الدخول إلى لوحة العمليات / Enter Dashboard" routing directly to operational management.

### R4. Post-Registration Routing
- Upon successful registration on `/register/`, redirect the newly created restaurant owner directly to their Profile page so they can review their trial subscription, limits, and plan details before entering operations.

## Verification Resources
- Verification runner script: `./init.sh`
- Existing test suites: `test_system.py`, `test_e2e_rbac.py`, `test_restaurant_profile.py`
- Django system check: `venv/bin/python manage.py check`

## Acceptance Criteria

### Navbar & Authentication
- [ ] Landing page header shows only Logo, Language Switcher, and auth buttons (no content tab links).
- [ ] When logged in as owner/manager, header replaces guest buttons with "لوحة الإدارة" and "البروفايل".
- [ ] Guest users still see "تسجيل الدخول" and "ابدأ مجاناً".

### Language & Internationalization
- [ ] Switching between Arabic and English renders 100% translated text across the entire landing page.
- [ ] Layout switches direction seamlessly (RTL for Arabic, LTR for English).

### Profile & Subscriptions
- [ ] Profile page renders current subscription status, plan name, and renewal date.
- [ ] Visual progress bars display branch and employee usage against plan caps accurately.
- [ ] Upgrade modal allows selecting a plan and submitting an upgrade request.
- [ ] "الدخول إلى لوحة العمليات" button navigates smoothly to `/dashboard/`.

### Registration Flow & Security
- [ ] Newly registered user is redirected to the Profile page upon successful signup.
- [ ] Non-authenticated users are redirected to login when trying to access the profile page.
- [ ] `./init.sh` runs and passes with exit code 0.
