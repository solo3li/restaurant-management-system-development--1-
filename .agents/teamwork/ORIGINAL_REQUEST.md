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
