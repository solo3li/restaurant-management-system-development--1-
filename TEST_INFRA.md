# TEST_INFRA.md — Restaurant Profile Management Test Infrastructure

## 1. Overview & Architecture

This document establishes the test infrastructure, testing strategy, and 4-tier test verification framework for the **Central HQ Restaurant Profile Management** module in the Motaem Cloud Restaurant OS.

### Objectives
- Guarantee end-to-end reliability for Central HQ managers updating restaurant branding, identity, and contact details.
- Enforce strict Role-Based Access Control (RBAC) ensuring branch staff (Cashiers, Kitchen, Drivers, Branch Managers) cannot access or modify HQ profile settings.
- Enforce uncompromising multi-tenant isolation so tenant modifications never leak or tamper with other tenants.
- Provide automated regression protection executable via a single standard command.

### Environment & Test Harness
- **Runtime**: Python 3.10+ / Django 5.x test environment.
- **Execution Command**: `venv/bin/python test_restaurant_profile.py`
- **Driver**: Django `Client` and `RequestFactory` with session and authentication middleware simulation.
- **Database**: SQLite transactional backend with clean test fixture creation and automated post-test teardown.
- **Media Storage**: Mocked/in-memory file uploads via `SimpleUploadedFile` with automated cleanup in `MEDIA_ROOT`.

---

## 2. The 4-Tier Test Methodology

The test suite is structured according to a strict 4-tier hierarchy:

```
+---------------------------------------------------------------+
| Tier 4: Real-World Scenarios (Full Lifecycle End-to-End)     |
+---------------------------------------------------------------+
| Tier 3: Cross-Feature & Security (RBAC + Tenant Isolation)    |
+---------------------------------------------------------------+
| Tier 2: Boundary & Corner Cases (Adversarial, Limits, Types) |
+---------------------------------------------------------------+
| Tier 1: Feature Coverage (Core Functions >=5 cases/feature)   |
+---------------------------------------------------------------+
```

---

### Tier 1: Feature Coverage (>=5 test cases per feature)

Tier 1 exercises the primary functional contracts of each core feature.

#### Feature 1: GET `/restaurant/profile/` (HQ Profile View)
- `T1-GET-01`: Owner gets HTTP 200 and renders `restaurant_profile.html`.
- `T1-GET-02`: Rendered view exposes the active tenant's current name and bio.
- `T1-GET-03`: Rendered view exposes current contact details (phone, email, headquarters address).
- `T1-GET-04`: Rendered view includes visual branding indicators (brand color, logo image/cover if present).
- `T1-GET-05`: Rendered view includes navigation context (`active_tab='restaurant_profile'` and admin navigation tabs).

#### Feature 2: POST Name & Bio Updates
- `T1-NAME-01`: POST with valid name and bio successfully updates tenant record in database.
- `T1-NAME-02`: POST with new name and empty bio updates name and clears/leaves bio empty.
- `T1-NAME-03`: POST with Arabic unicode text (اسم المطعم، نبذة باللغة العربية) persists without encoding degradation.
- `T1-NAME-04`: POST with leading and trailing whitespace on name trims cleanly before persisting.
- `T1-NAME-05`: POST name update reflects immediately on subsequent GET request and database refresh.

#### Feature 3: POST Phone, Email, and Address Updates
- `T1-CONT-01`: POST with valid phone, email, and address updates all three contact fields in database.
- `T1-CONT-02`: POST phone number in international and local formats (e.g. `+966501234567`, `0501234567`) persists accurately.
- `T1-CONT-03`: POST valid RFC-compliant email address (e.g. `contact@restaurant.com`) persists accurately.
- `T1-CONT-04`: POST multi-word headquarters address with punctuation and numbers persists accurately.
- `T1-CONT-05`: POST partial contact update (updating email only) preserves existing phone and address intact.

#### Feature 4: POST Primary Brand Color Updates
- `T1-COLOR-01`: POST standard 7-character hex color code (e.g. `#6366F1`) updates `brand_color` in database.
- `T1-COLOR-02`: POST uppercase hex color code (e.g. `#0E382A`) updates `brand_color` in database.
- `T1-COLOR-03`: POST lowercase hex color code (e.g. `#4f46e5`) updates or normalizes in database.
- `T1-COLOR-04`: POST alternative brand color updates without mutating other tenant profile attributes.
- `T1-COLOR-05`: Updated brand color reflects in rendered profile view context on subsequent GET.

#### Feature 5: POST Logo Image & Cover Image Uploads
- `T1-MEDIA-01`: POST multipart upload with valid PNG logo saves file to `tenant_logos/` and links to tenant.
- `T1-MEDIA-02`: POST multipart upload with valid JPEG cover saves file to `tenant_covers/` and links to tenant.
- `T1-MEDIA-03`: POST multipart upload with both logo and cover simultaneously updates both file fields.
- `T1-MEDIA-04`: POST update without new file uploads preserves existing logo and cover paths unchanged.
- `T1-MEDIA-05`: POST upload with valid WebP or SVG format image accepted and saved successfully.

---

### Tier 2: Boundary & Corner Cases

Tier 2 exercises input validation, data limits, resource constraints, and error rejection paths.

- `T2-BOUND-01`: **Empty Name Rejection** — Submitting empty string or whitespace-only name is rejected with HTTP 400 (or validation error message).
- `T2-BOUND-02`: **Bio Maximum Length Boundary** — Submitting bio at boundary (<= 255 characters) succeeds; exceeding 255 characters is rejected or properly truncated/validated.
- `T2-BOUND-03`: **Invalid Email Syntax Rejection** — Submitting malformed email (e.g. `invalid-email`, `user@`, `@domain.com`, `user@domain`) is rejected with HTTP 400 or form error.
- `T2-BOUND-04`: **Invalid Hex Color Rejection** — Submitting non-hex strings (e.g. `blue`, `#12345`, `#GGGGGG`, `#1234567`, `123456`) is rejected with HTTP 400 or validation error.
- `T2-BOUND-05`: **Oversized Logo Rejection (>2MB)** — Uploading logo file exceeding 2MB (e.g. 2.5MB payload) is rejected with HTTP 400 / error message without storing file.
- `T2-BOUND-06`: **Oversized Cover Rejection (>5MB)** — Uploading cover file exceeding 5MB (e.g. 5.5MB payload) is rejected with HTTP 400 / error message without storing file.
- `T2-BOUND-07`: **Disallowed File Extensions Rejection** — Uploading executable or script files (e.g. `.exe`, `.py`, `.sh`, `.php`, `.pdf`, `.html`) is rejected with HTTP 400 / error message.
- `T2-BOUND-08`: **Corrupted / Empty File Upload Handling** — Uploading 0-byte file or empty file input handled gracefully without crashing.
- `T2-BOUND-09`: **XSS / Special Characters in Bio & Address** — HTML tags (`<script>`, `<style>`, `<b>`) in bio or address are properly handled and escaped.

---

### Tier 3: Cross-Feature & Security Combinations

Tier 3 exercises RBAC security, role authorization gates, and multi-tenant data isolation.

#### Strict Role-Based Access Control (RBAC) Matrix
| Actor / Role | Permitted Permissions | Expected GET `/restaurant/profile/` | Expected POST Update | Expected Response Code |
| :--- | :--- | :---: | :---: | :---: |
| **Unauthenticated** | None | Redirect `/login/` | Redirect `/login/` | **HTTP 302** |
| **Owner** | All (`is_owner` / superuser) | Access Granted | Allowed | **HTTP 200** / 302 |
| **HQ Manager** | `view_hq_dashboard` / `system_manage_settings` | Access Granted | Allowed | **HTTP 200** / 302 |
| **Floor Cashier** | `pos_access`, `branch_view_orders` | Forbidden | Forbidden | **HTTP 403** |
| **Kitchen Chef** | `kds_access`, `inventory_view` | Forbidden | Forbidden | **HTTP 403** |
| **Delivery Driver** | `delivery_access`, `delivery_track` | Forbidden | Forbidden | **HTTP 403** |
| **Branch Manager** | `branch_dashboard`, `manage_menu` | Forbidden (HQ settings) | Forbidden | **HTTP 403** |

- `T3-SEC-01`: Unauthenticated GET `/restaurant/profile/` redirects to login (`HTTP 302`).
- `T3-SEC-02`: Unauthenticated POST to profile endpoint redirects to login (`HTTP 302`).
- `T3-SEC-03`: Restaurant Owner accesses GET and executes POST with `HTTP 200`.
- `T3-SEC-04`: HQ Manager accesses GET and executes POST with `HTTP 200`.
- `T3-SEC-05`: Branch Cashier is strictly blocked from GET and POST with `HTTP 403 Forbidden`.
- `T3-SEC-06`: Kitchen Chef is strictly blocked from GET and POST with `HTTP 403 Forbidden`.
- `T3-SEC-07`: Delivery Driver is strictly blocked from GET and POST with `HTTP 403 Forbidden`.
- `T3-SEC-08`: Branch Manager without HQ permissions is strictly blocked from GET and POST with `HTTP 403 Forbidden`.

#### Multi-Tenant Data Isolation
- `T3-ISO-01`: **Tenant Profile Scoping** — Tenant A manager authenticated in session sees only Tenant A's name, logo, and contact info.
- `T3-ISO-02`: **Cross-Tenant Mutation Immunity** — Tenant A manager submitting profile updates cannot modify Tenant B's profile.
- `T3-ISO-03`: **Tamper Resistance via Request Parameters** — Explicit injection of `tenant_id=<Tenant B ID>` in POST payload is ignored; updates apply exclusively to `get_active_tenant(request)`.
- `T3-ISO-04`: **Tenant B Integrity Verification** — Full profile modification on Tenant A leaves all attributes of Tenant B completely intact.

---

### Tier 4: Real-World Scenarios

Tier 4 exercises full end-to-end lifecycle workflows reflecting genuine user behavior.

- `T4-SCEN-01`: **Complete Restaurant Onboarding / Initial Setup Workflow**
  1. Tenant created with minimal placeholder data.
  2. Owner logs in and navigates to Central HQ dashboard.
  3. Owner opens Restaurant Profile page (`/restaurant/profile/`).
  4. Owner submits complete brand profile: name, bio, phone, email, address, brand color, logo, and cover.
  5. Verify HTTP success and persistent database reflection for all fields.
  6. Owner refreshes profile page; view displays all updated assets and contact details.

- `T4-SCEN-02`: **Incremental Re-branding Lifecycle**
  1. HQ Manager updates primary brand color and replaces logo image.
  2. Verify logo file replaced in storage and database updated.
  3. Verify existing contact details (phone, email, address) and cover banner remain unchanged.
  4. Subsequent GET confirms new branding is active.

- `T4-SCEN-03`: **Contact Relocation & Error Recovery Lifecycle**
  1. HQ Manager attempts update with invalid email address format -> rejected with HTTP 400.
  2. Verify database was NOT partially updated.
  3. HQ Manager corrects email and updates headquarters address -> succeeds with HTTP 200/302.
  4. Verify updated email and address persist while branding remains intact.

---

## 3. Test Fixtures & Teardown Protocol

### Test Data Generation
1. **Tenants**:
   - `Tenant A`: Primary test tenant (`slug="test_restaurant_a"`).
   - `Tenant B`: Isolation boundary tenant (`slug="test_restaurant_b"`).
2. **Users & Profiles**:
   - `Owner User`: Superuser / Owner profile.
   - `HQ Manager User`: Synced to `JobRole` with `view_hq_dashboard` and `system_manage_settings`.
   - `Cashier User`: Synced to `JobRole` with `pos_access`.
   - `Chef User`: Synced to `JobRole` with `kds_access`.
   - `Driver User`: Synced to `JobRole` with `delivery_access`.
   - `Branch Manager User`: Synced to `JobRole` with `manage_branches` (branch scope).
3. **Media Files**:
   - `SimpleUploadedFile` used to generate valid PNG (`image/png`), JPEG (`image/jpeg`), and oversized buffers in memory.

### Teardown & Cleanup
1. Delete generated `SimpleUploadedFile` artifacts from disk (`settings.MEDIA_ROOT / tenant_logos` and `tenant_covers`).
2. Purge test orders, test employees, test users, and test tenants.
3. Reset tenant profile to clean baseline state.

---

## 4. Execution Commands

```bash
# Execute Restaurant Profile Test Suite standalone
venv/bin/python test_restaurant_profile.py

# Execute full verification harness including system and RBAC checks
./init.sh
```

---

## 5. Requirements Traceability Matrix

| Requirement | Description | Test Tier | Test Case IDs |
| :--- | :--- | :--- | :--- |
| **R1** | Dedicated HQ view & navigation | Tier 1, Tier 3 | `T1-GET-01` to `T1-GET-05`, `T3-SEC-01` to `T3-SEC-04` |
| **R2** | Profile data & media update endpoints | Tier 1, Tier 2, Tier 4 | `T1-NAME-01` to `T1-NAME-05`, `T1-CONT-01` to `T1-CONT-05`, `T1-COLOR-01` to `T1-COLOR-05`, `T1-MEDIA-01` to `T1-MEDIA-05`, `T2-BOUND-01` to `T2-BOUND-09`, `T4-SCEN-01` to `T4-SCEN-03` |
| **R3** | Permissions (RBAC) & Multi-Tenant Isolation | Tier 3 | `T3-SEC-01` to `T3-SEC-08`, `T3-ISO-01` to `T3-ISO-04` |
| **Acceptance** | DB persistence, preview, 100% pass | Tier 1, Tier 4 | All Tiers, `T4-SCEN-01`, `T4-SCEN-02` |
