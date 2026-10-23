#!/usr/bin/env python3
"""
Comprehensive 4-Tier Opaque-Box E2E Test Suite for Restaurant Profile Management.
Tests Central HQ Restaurant Profile View, Updates, Media Uploads, Boundary Validation,
Strict Role-Based Access Control (RBAC), Multi-Tenant Isolation, and Real-World Workflows.
"""

import os
import sys
import io
import json
import time
from decimal import Decimal
from pathlib import Path

# Setup Django Environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from django.conf import settings
from django.contrib.auth.models import User, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from apps.tenants.models import Tenant, Branch
from apps.accounts.models import JobRole, UserProfile, Employee
from apps.accounts.helpers import user_has_perm

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# 1x1 Transparent PNG bytes
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01Haf\xa0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Minimal 1x1 JPEG bytes
TINY_JPG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12"
    b"\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<."
    b"342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01"
    b"\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06"
    b"\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)

# Minimal WebP bytes
TINY_WEBP = (
    b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00/0\x00\x00\x00\x00\x00\x00"
    b"\x01\x00\x00\x00\x00\x00"
)


class TestTracker:
    def __init__(self):
        self.tiers = {1: {"passed": 0, "failed": 0, "tests": []},
                      2: {"passed": 0, "failed": 0, "tests": []},
                      3: {"passed": 0, "failed": 0, "tests": []},
                      4: {"passed": 0, "failed": 0, "tests": []}}
        self.failures = []

    def record_pass(self, tier, test_id, description):
        self.tiers[tier]["passed"] += 1
        self.tiers[tier]["tests"].append((test_id, True, description))
        print(f"  {GREEN}✔ PASS [{test_id}]:{RESET} {description}")

    def record_fail(self, tier, test_id, description, error_detail):
        self.tiers[tier]["failed"] += 1
        self.tiers[tier]["tests"].append((test_id, False, f"{description} -> {error_detail}"))
        self.failures.append(f"[{test_id}] {description}: {error_detail}")
        print(f"  {RED}✘ FAIL [{test_id}]:{RESET} {description}")
        print(f"       {RED}Error: {error_detail}{RESET}")

    def summary(self):
        print(f"\n{CYAN}{BOLD}{'='*75}{RESET}")
        print(f"{CYAN}{BOLD}                    RESTAURANT PROFILE TEST SUITE SUMMARY{RESET}")
        print(f"{CYAN}{BOLD}{'='*75}{RESET}")
        total_p = sum(t["passed"] for t in self.tiers.values())
        total_f = sum(t["failed"] for t in self.tiers.values())
        total_all = total_p + total_f

        for t in range(1, 5):
            t_data = self.tiers[t]
            t_tot = t_data["passed"] + t_data["failed"]
            pct = (t_data["passed"] / t_tot * 100) if t_tot > 0 else 0
            tier_names = {
                1: "Tier 1 (Feature Coverage)",
                2: "Tier 2 (Boundary & Corner Cases)",
                3: "Tier 3 (Cross-Feature & Security)",
                4: "Tier 4 (Real-World Scenarios)"
            }
            color = GREEN if t_data["failed"] == 0 and t_tot > 0 else (YELLOW if t_data["passed"] > 0 else RED)
            print(f"  {color}{tier_names[t]}: {t_data['passed']}/{t_tot} passed ({pct:.1f}%){RESET}")

        print(f"{CYAN}{'-'*75}{RESET}")
        if total_f == 0 and total_all > 0:
            print(f"  {GREEN}{BOLD}OVERALL RESULT: 100% PASS ({total_p}/{total_all} test cases passed){RESET}")
        else:
            print(f"  {RED}{BOLD}OVERALL RESULT: FAIL ({total_p}/{total_all} passed, {total_f} failed){RESET}")
        print(f"{CYAN}{BOLD}{'='*75}{RESET}\n")
        return total_f == 0 and total_all > 0


tracker = TestTracker()


def print_tier_header(tier_num, title):
    print(f"\n{CYAN}{BOLD}{'='*75}{RESET}")
    print(f"{CYAN}{BOLD}>>> TIER {tier_num}: {title}{RESET}")
    print(f"{CYAN}{BOLD}{'='*75}{RESET}")


def run_case(tier, test_id, description, fn):
    try:
        ok, err = fn()
        if ok:
            tracker.record_pass(tier, test_id, description)
        else:
            tracker.record_fail(tier, test_id, description, err)
    except Exception as exc:
        tracker.record_fail(tier, test_id, description, f"Exception: {type(exc).__name__}: {str(exc)}")


def post_profile_data(client, data, endpoint=None):
    """
    Submits profile update data, trying /restaurant/profile/ or /api/restaurant/profile/.
    Supports both multipart form data and fallback endpoints.
    """
    if endpoint:
        return client.post(endpoint, data)
    try:
        res = client.post("/restaurant/profile/", data)
        if res.status_code == 404:
            res = client.post("/api/restaurant/profile/", data)
        return res
    except Exception:
        # Fallback to API if view render throws template exception
        return client.post("/api/restaurant/profile/", data)


def safe_cleanup_media(paths):
    """Removes created test media files from filesystem."""
    for p in paths:
        if p and hasattr(p, "name") and p.name:
            full_path = Path(settings.MEDIA_ROOT) / p.name
            try:
                if full_path.exists() and full_path.is_file():
                    full_path.unlink()
            except Exception:
                pass


def run_restaurant_profile_tests():
    print(f"{BOLD}Initializing Restaurant Profile Opaque-Box Test Suite...{RESET}")

    # -------------------------------------------------------------
    # Fixture Setup
    # -------------------------------------------------------------
    unique_tag = str(int(time.time()))
    uploaded_media_cleanup = []

    # Tenant A (Primary Test Subject)
    tenant_a, _ = Tenant.objects.get_or_create(
        slug="test_res_profile_a",
        defaults={
            "name": "مطعم الأصالة للتجربة",
            "bio": "مطعم تقليدي يقدم أشهى الأطباق الشعبية",
            "phone": "0501112233",
            "email": "asala@test-restaurant.sa",
            "address": "الرياض، طريق الملك فهد، مبنى 10",
            "brand_color": "#0E382A",
            "is_active": True,
        }
    )
    branch_a, _ = Branch.objects.get_or_create(
        tenant=tenant_a,
        name="فرع العليا",
        defaults={"status": "active"}
    )

    # Tenant B (Multi-Tenant Isolation Subject)
    tenant_b, _ = Tenant.objects.get_or_create(
        slug="test_res_profile_b",
        defaults={
            "name": "مطعم الأفق البعيد",
            "bio": "مأكولات عصرية ومشروبات فاخرة",
            "phone": "0598887766",
            "email": "horizon@test-restaurant.sa",
            "address": "جدة، طريق الكورنيش، برج 5",
            "brand_color": "#1E40AF",
            "is_active": True,
        }
    )
    branch_b, _ = Branch.objects.get_or_create(
        tenant=tenant_b,
        name="فرع الكورنيش",
        defaults={"status": "active"}
    )

    # Setup Roles for Tenant A
    # 1. HQ Manager Role
    hq_mgr_role, _ = JobRole.objects.get_or_create(
        tenant=tenant_a,
        name=f"مدير عام HQ تجريبي {unique_tag}",
        defaults={"scope": "hq"}
    )
    hq_mgr_role.sync_with_django_group()
    hq_mgr_role.set_permissions(["view_hq_dashboard", "system_manage_settings", "manage_branches"])

    # 2. Branch Cashier Role
    cashier_role, _ = JobRole.objects.get_or_create(
        tenant=tenant_a,
        name=f"كاشير فرع تجريبي {unique_tag}",
        defaults={"scope": "branch"}
    )
    cashier_role.sync_with_django_group()
    cashier_role.set_permissions(["pos_access", "branch_view_orders"])

    # 3. Kitchen Chef Role
    chef_role, _ = JobRole.objects.get_or_create(
        tenant=tenant_a,
        name=f"طاهٍ فرع تجريبي {unique_tag}",
        defaults={"scope": "branch"}
    )
    chef_role.sync_with_django_group()
    chef_role.set_permissions(["kds_access"])

    # 4. Delivery Driver Role
    driver_role, _ = JobRole.objects.get_or_create(
        tenant=tenant_a,
        name=f"سائق فرع تجريبي {unique_tag}",
        defaults={"scope": "branch"}
    )
    driver_role.sync_with_django_group()
    driver_role.set_permissions(["delivery_access"])

    # 5. Branch Manager Role (Branch-scoped without HQ perms)
    bm_role, _ = JobRole.objects.get_or_create(
        tenant=tenant_a,
        name=f"مدير فرع محلي تجريبي {unique_tag}",
        defaults={"scope": "branch"}
    )
    bm_role.sync_with_django_group()
    bm_role.set_permissions(["pos_access", "branch_view_orders", "menu_manage_items"])

    # Setup Users for Tenant A
    # Owner
    owner_user, _ = User.objects.get_or_create(
        username=f"owner_{unique_tag}",
        defaults={"is_superuser": True, "email": "owner@asala.test"}
    )
    owner_user.set_password("pass1234")
    owner_user.save()
    UserProfile.objects.update_or_create(
        user=owner_user,
        defaults={"tenant": tenant_a, "role": "owner"}
    )

    # HQ Manager
    hq_user, _ = User.objects.get_or_create(username=f"hq_mgr_{unique_tag}")
    hq_user.groups.set([hq_mgr_role.group])
    hq_user.save()
    UserProfile.objects.update_or_create(
        user=hq_user,
        defaults={"tenant": tenant_a, "job_role": hq_mgr_role, "role": "branch_manager"}
    )

    # Cashier
    cashier_user, _ = User.objects.get_or_create(username=f"cashier_{unique_tag}")
    cashier_user.groups.set([cashier_role.group])
    cashier_user.save()
    UserProfile.objects.update_or_create(
        user=cashier_user,
        defaults={"tenant": tenant_a, "branch": branch_a, "job_role": cashier_role, "role": "cashier"}
    )

    # Chef
    chef_user, _ = User.objects.get_or_create(username=f"chef_{unique_tag}")
    chef_user.groups.set([chef_role.group])
    chef_user.save()
    UserProfile.objects.update_or_create(
        user=chef_user,
        defaults={"tenant": tenant_a, "branch": branch_a, "job_role": chef_role, "role": "chef"}
    )

    # Driver
    driver_user, _ = User.objects.get_or_create(username=f"driver_{unique_tag}")
    driver_user.groups.set([driver_role.group])
    driver_user.save()
    UserProfile.objects.update_or_create(
        user=driver_user,
        defaults={"tenant": tenant_a, "branch": branch_a, "job_role": driver_role, "role": "driver"}
    )

    # Branch Manager
    bm_user, _ = User.objects.get_or_create(username=f"bm_{unique_tag}")
    bm_user.groups.set([bm_role.group])
    bm_user.save()
    UserProfile.objects.update_or_create(
        user=bm_user,
        defaults={"tenant": tenant_a, "branch": branch_a, "job_role": bm_role, "role": "branch_manager"}
    )

    # Setup User for Tenant B (Owner B)
    owner_b_user, _ = User.objects.get_or_create(username=f"owner_b_{unique_tag}")
    owner_b_user.save()
    UserProfile.objects.update_or_create(
        user=owner_b_user,
        defaults={"tenant": tenant_b, "role": "owner"}
    )

    client = Client()

    try:
        # =============================================================
        # TIER 1: Feature Coverage (>=5 test cases per feature)
        # =============================================================
        print_tier_header(1, "Feature Coverage (Primary Functional Contracts)")

        # -------------------------------------------------------------
        # Feature 1: GET /restaurant/profile/
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Feature 1: GET /restaurant/profile/ View & Rendering:{RESET}")

        def t1_get_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            return res.status_code == 200, f"Status code: {res.status_code}"

        run_case(1, "T1-GET-01", "Owner GET /restaurant/profile/ returns HTTP 200 OK", t1_get_01)

        def t1_get_02():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            html = res.content.decode("utf-8") if res.status_code == 200 else ""
            return tenant_a.name in html, f"Name '{tenant_a.name}' not found in rendered HTML"

        run_case(1, "T1-GET-02", "Restaurant name rendered in profile view HTML", t1_get_02)

        def t1_get_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            html = res.content.decode("utf-8") if res.status_code == 200 else ""
            return tenant_a.bio in html, f"Bio '{tenant_a.bio}' not found in rendered HTML"

        run_case(1, "T1-GET-03", "Restaurant bio rendered in profile view HTML", t1_get_03)

        def t1_get_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            html = res.content.decode("utf-8") if res.status_code == 200 else ""
            ok = (tenant_a.phone in html) and (tenant_a.email in html)
            return ok, "Contact details (phone or email) missing in response HTML"

        run_case(1, "T1-GET-04", "Contact details (phone and email) rendered in profile view HTML", t1_get_04)

        def t1_get_05():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            html = res.content.decode("utf-8") if res.status_code == 200 else ""
            ok = (tenant_a.brand_color.lower() in html.lower()) or ("brand_color" in html)
            return ok, "Brand color or branding elements not found in HTML"

        run_case(1, "T1-GET-05", "Brand color / branding elements rendered in profile view HTML", t1_get_05)

        # -------------------------------------------------------------
        # Feature 2: POST Name & Bio Updates
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Feature 2: POST Name & Bio Updates:{RESET}")

        def t1_name_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            new_name = f"مطعم النخيل الذهبي {unique_tag}"
            new_bio = "أشهى المأكولات التراثية والعالمية بإشراف أمهر الطهاة"
            res = post_profile_data(client, {
                "name": new_name,
                "bio": new_bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.name == new_name and tenant_a.bio == new_bio
            return ok, f"Status: {res.status_code}, Name: '{tenant_a.name}', Bio: '{tenant_a.bio}'"

        run_case(1, "T1-NAME-01", "POST valid name and bio successfully updates database", t1_name_01)

        def t1_name_02():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            new_name = f"مطعم السحاب {unique_tag}"
            res = post_profile_data(client, {
                "name": new_name,
                "bio": "",
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.name == new_name and tenant_a.bio == ""
            return ok, f"Status: {res.status_code}, DB bio: '{tenant_a.bio}'"

        run_case(1, "T1-NAME-02", "POST name with empty bio updates name and clears bio", t1_name_02)

        def t1_name_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            arabic_name = "مطعم كبسة وحاشي فاخر (فرع التحلية)"
            arabic_bio = "نقدم اللحم الطازج يومياً مع أرز عنبر فاخر ومقبلات شامية"
            res = post_profile_data(client, {
                "name": arabic_name,
                "bio": arabic_bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.name == arabic_name and tenant_a.bio == arabic_bio
            return ok, f"Status: {res.status_code}, DB name: '{tenant_a.name}'"

        run_case(1, "T1-NAME-03", "POST Arabic unicode text preserves full character fidelity", t1_name_03)

        def t1_name_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            padded_name = "   مطعم الضيافة المميزة   "
            res = post_profile_data(client, {
                "name": padded_name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.name == padded_name.strip()
            return ok, f"Status: {res.status_code}, DB name: '{tenant_a.name}'"

        run_case(1, "T1-NAME-04", "POST name with leading/trailing whitespace trims before persisting", t1_name_04)

        def t1_name_05():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res_get = client.get("/restaurant/profile/")
            html = res_get.content.decode("utf-8") if res_get.status_code == 200 else ""
            ok = res_get.status_code == 200 and tenant_a.name in html
            return ok, f"Status: {res_get.status_code}, Name '{tenant_a.name}' in HTML: {tenant_a.name in html}"

        run_case(1, "T1-NAME-05", "Updated name immediately reflects in subsequent profile GET view", t1_name_05)

        # -------------------------------------------------------------
        # Feature 3: POST Phone, Email, and Address Updates
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Feature 3: POST Phone, Email, Address Contact Details:{RESET}")

        def t1_cont_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            new_phone = "0114455667"
            new_email = "hq@mot-restaurant.com"
            new_address = "الرياض، حي السليمانية، شارع الثلاثين"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": new_phone,
                "email": new_email,
                "address": new_address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = (res.status_code in [200, 302] and tenant_a.phone == new_phone and
                  tenant_a.email == new_email and tenant_a.address == new_address)
            return ok, f"Status: {res.status_code}, Phone: {tenant_a.phone}, Email: {tenant_a.email}"

        run_case(1, "T1-CONT-01", "POST phone, email, and address successfully updates database", t1_cont_01)

        def t1_cont_02():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            intl_phone = "+966551234567"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": intl_phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.phone == intl_phone
            return ok, f"Status: {res.status_code}, Phone: {tenant_a.phone}"

        run_case(1, "T1-CONT-02", "POST international phone format (+966...) persists accurately", t1_cont_02)

        def t1_cont_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            rfc_email = "contact.support@cloud-kitchen.sa"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": rfc_email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.email == rfc_email
            return ok, f"Status: {res.status_code}, Email: {tenant_a.email}"

        run_case(1, "T1-CONT-03", "POST valid RFC email address persists accurately", t1_cont_03)

        def t1_cont_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            complex_address = "الدمام، حي الشاطئ الشرقي - مجمع الواجهة البحرية، بوابة 3، مكتب 12"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": complex_address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.address == complex_address
            return ok, f"Status: {res.status_code}, Address: {tenant_a.address}"

        run_case(1, "T1-CONT-04", "POST complex Arabic address with numbers and dashes persists", t1_cont_04)

        def t1_cont_05():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            prior_phone = tenant_a.phone
            prior_address = tenant_a.address
            updated_email = "new_contact@restaurant.com"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": prior_phone,
                "email": updated_email,
                "address": prior_address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = (res.status_code in [200, 302] and tenant_a.email == updated_email and
                  tenant_a.phone == prior_phone and tenant_a.address == prior_address)
            return ok, f"Status: {res.status_code}, Phone: {tenant_a.phone}, Email: {tenant_a.email}"

        run_case(1, "T1-CONT-05", "POST email update preserves existing phone and address intact", t1_cont_05)

        # -------------------------------------------------------------
        # Feature 4: POST Primary Brand Color Updates
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Feature 4: POST Primary Brand Color Updates:{RESET}")

        def t1_color_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            color = "#6366F1"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.brand_color.upper() == color.upper()
            return ok, f"Status: {res.status_code}, Color: {tenant_a.brand_color}"

        run_case(1, "T1-COLOR-01", "POST standard hex color (#6366F1) updates brand_color in database", t1_color_01)

        def t1_color_02():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            color = "#0E382A"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.brand_color.upper() == color.upper()
            return ok, f"Status: {res.status_code}, Color: {tenant_a.brand_color}"

        run_case(1, "T1-COLOR-02", "POST uppercase hex color (#0E382A) updates brand_color in database", t1_color_02)

        def t1_color_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            color = "#10b981"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.brand_color.lower() == color.lower()
            return ok, f"Status: {res.status_code}, Color: {tenant_a.brand_color}"

        run_case(1, "T1-COLOR-03", "POST lowercase hex color (#10b981) updates brand_color in database", t1_color_03)

        def t1_color_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            name_before = tenant_a.name
            email_before = tenant_a.email
            color = "#D97706"
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": color,
            })
            tenant_a.refresh_from_db()
            ok = (res.status_code in [200, 302] and tenant_a.brand_color.upper() == color.upper() and
                  tenant_a.name == name_before and tenant_a.email == email_before)
            return ok, f"Status: {res.status_code}, Color: {tenant_a.brand_color}"

        run_case(1, "T1-COLOR-04", "POST brand_color update preserves all other profile attributes", t1_color_04)

        def t1_color_05():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            color = "#D97706"
            res_get = client.get("/restaurant/profile/")
            html = res_get.content.decode("utf-8") if res_get.status_code == 200 else ""
            ok = res_get.status_code == 200 and (color.lower() in html.lower())
            return ok, f"Status: {res_get.status_code}, Color in HTML: {color.lower() in html.lower()}"

        run_case(1, "T1-COLOR-05", "Updated brand color reflects in subsequent profile GET view", t1_color_05)

        # -------------------------------------------------------------
        # Feature 5: POST Logo Image & Cover Image Uploads
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Feature 5: POST Logo Image and Cover Image Uploads:{RESET}")

        def t1_media_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            logo_file = SimpleUploadedFile("brand_logo.png", TINY_PNG, content_type="image/png")
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "logo_image": logo_file,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.logo_image and "brand_logo" in tenant_a.logo_image.name
            if ok:
                uploaded_media_cleanup.append(tenant_a.logo_image)
            return ok, f"Status: {res.status_code}, Logo: {tenant_a.logo_image}"

        run_case(1, "T1-MEDIA-01", "POST multipart upload with valid PNG logo updates logo_image", t1_media_01)

        def t1_media_02():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            cover_file = SimpleUploadedFile("brand_cover.jpg", TINY_JPG, content_type="image/jpeg")
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "cover_image": cover_file,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.cover_image and "brand_cover" in tenant_a.cover_image.name
            if ok:
                uploaded_media_cleanup.append(tenant_a.cover_image)
            return ok, f"Status: {res.status_code}, Cover: {tenant_a.cover_image}"

        run_case(1, "T1-MEDIA-02", "POST multipart upload with valid JPEG cover updates cover_image", t1_media_02)

        def t1_media_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            both_logo = SimpleUploadedFile("both_logo.png", TINY_PNG, content_type="image/png")
            both_cover = SimpleUploadedFile("both_cover.jpg", TINY_JPG, content_type="image/jpeg")
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "logo_image": both_logo,
                "cover_image": both_cover,
            })
            tenant_a.refresh_from_db()
            ok = (res.status_code in [200, 302] and tenant_a.logo_image and "both_logo" in tenant_a.logo_image.name and
                  tenant_a.cover_image and "both_cover" in tenant_a.cover_image.name)
            if ok:
                uploaded_media_cleanup.extend([tenant_a.logo_image, tenant_a.cover_image])
            return ok, f"Status: {res.status_code}, Logo: {tenant_a.logo_image}, Cover: {tenant_a.cover_image}"

        run_case(1, "T1-MEDIA-03", "POST simultaneous upload of both logo and cover updates both fields", t1_media_03)

        def t1_media_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            old_logo = tenant_a.logo_image.name if tenant_a.logo_image else ""
            old_cover = tenant_a.cover_image.name if tenant_a.cover_image else ""
            res = post_profile_data(client, {
                "name": "مطعم النخيل للتحديث النصي",
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            new_logo = tenant_a.logo_image.name if tenant_a.logo_image else ""
            new_cover = tenant_a.cover_image.name if tenant_a.cover_image else ""
            ok = res.status_code in [200, 302] and new_logo == old_logo and new_cover == old_cover
            return ok, f"Status: {res.status_code}, Old: {old_logo}, New: {new_logo}"

        run_case(1, "T1-MEDIA-04", "Text-only profile update preserves existing logo and cover images", t1_media_04)

        def t1_media_05():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            webp_logo = SimpleUploadedFile("modern_logo.webp", TINY_WEBP, content_type="image/webp")
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "logo_image": webp_logo,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and tenant_a.logo_image and "modern_logo" in tenant_a.logo_image.name
            if ok:
                uploaded_media_cleanup.append(tenant_a.logo_image)
            return ok, f"Status: {res.status_code}, Logo: {tenant_a.logo_image}"

        run_case(1, "T1-MEDIA-05", "POST upload with valid WebP format image accepted and saved", t1_media_05)

        # =============================================================
        # TIER 2: Boundary & Corner Cases
        # =============================================================
        print_tier_header(2, "Boundary & Corner Cases (Validation, Limits, and Types)")

        def t2_bound_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            name_before = tenant_a.name
            res = post_profile_data(client, {
                "name": "",
                "bio": "وصف بدون اسم",
                "phone": "0501112233",
                "email": "test@test.com",
                "brand_color": "#0E382A",
            })
            tenant_a.refresh_from_db()
            ok = res.status_code == 400 or tenant_a.name == name_before or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower())
            return ok, f"Status: {res.status_code}, Name: {tenant_a.name}"

        run_case(2, "T2-BOUND-01", "Submitting empty name is rejected without corrupting DB", t2_bound_01)

        def t2_bound_02():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            name_before = tenant_a.name
            res = post_profile_data(client, {
                "name": "     ",
                "bio": "وصف لمطعم باسم فراغات",
                "phone": "0501112233",
                "email": "test@test.com",
                "brand_color": "#0E382A",
            })
            tenant_a.refresh_from_db()
            ok = res.status_code == 400 or tenant_a.name == name_before or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower())
            return ok, f"Status: {res.status_code}, Name: {tenant_a.name}"

        run_case(2, "T2-BOUND-02", "Submitting whitespace-only name is rejected without corrupting DB", t2_bound_02)

        def t2_bound_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            bio_255 = "س" * 255
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": bio_255,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302] and len(tenant_a.bio) <= 255 and len(tenant_a.bio) > 200
            return ok, f"Status: {res.status_code}, Bio len: {len(tenant_a.bio)}"

        run_case(2, "T2-BOUND-03", "Bio at max length boundary (255 characters) accepted cleanly", t2_bound_03)

        def t2_bound_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            email_before = tenant_a.email
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": "invalid_email_format_no_at",
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or (tenant_a.email == email_before)
            return ok, f"Status: {res.status_code}, Email: {tenant_a.email}"

        run_case(2, "T2-BOUND-04", "Malformed email without @ is rejected without updating DB", t2_bound_04)

        def t2_bound_05():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            email_before = tenant_a.email
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": "user@",
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or (tenant_a.email == email_before)
            return ok, f"Status: {res.status_code}, Email: {tenant_a.email}"

        run_case(2, "T2-BOUND-05", "Malformed email 'user@' is rejected without updating DB", t2_bound_05)

        def t2_bound_06():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            color_before = tenant_a.brand_color
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": "not-a-color-name",
            })
            tenant_a.refresh_from_db()
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or (tenant_a.brand_color == color_before)
            return ok, f"Status: {res.status_code}, Color: {tenant_a.brand_color}"

        run_case(2, "T2-BOUND-06", "Non-hex color string 'not-a-color-name' rejected without updating DB", t2_bound_06)

        def t2_bound_07():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            color_before = tenant_a.brand_color
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": "#12345",
            })
            tenant_a.refresh_from_db()
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or (tenant_a.brand_color == color_before)
            return ok, f"Status: {res.status_code}, Color: {tenant_a.brand_color}"

        run_case(2, "T2-BOUND-07", "Invalid 5-character hex code '#12345' rejected without updating DB", t2_bound_07)

        def t2_bound_08():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            color_before = tenant_a.brand_color
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": "#GGGGGG",
            })
            tenant_a.refresh_from_db()
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or (tenant_a.brand_color == color_before)
            return ok, f"Status: {res.status_code}, Color: {tenant_a.brand_color}"

        run_case(2, "T2-BOUND-08", "Hex color with non-hex chars '#GGGGGG' rejected without updating DB", t2_bound_08)

        def t2_bound_09():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            oversized = SimpleUploadedFile("big_logo.png", b"0" * (2 * 1024 * 1024 + 1024), content_type="image/png")
            logo_before = tenant_a.logo_image.name if tenant_a.logo_image else ""
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "logo_image": oversized,
            })
            tenant_a.refresh_from_db()
            curr_logo = tenant_a.logo_image.name if tenant_a.logo_image else ""
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or (curr_logo == logo_before)
            return ok, f"Status: {res.status_code}, Logo: {curr_logo}"

        run_case(2, "T2-BOUND-09", "Oversized logo (>2MB) upload is rejected without saving to DB", t2_bound_09)

        def t2_bound_10():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            oversized = SimpleUploadedFile("big_cover.jpg", b"0" * (5 * 1024 * 1024 + 1024), content_type="image/jpeg")
            cover_before = tenant_a.cover_image.name if tenant_a.cover_image else ""
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "cover_image": oversized,
            })
            tenant_a.refresh_from_db()
            curr_cover = tenant_a.cover_image.name if tenant_a.cover_image else ""
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or (curr_cover == cover_before)
            return ok, f"Status: {res.status_code}, Cover: {curr_cover}"

        run_case(2, "T2-BOUND-10", "Oversized cover (>5MB) upload is rejected without saving to DB", t2_bound_10)

        def t2_bound_11():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            exe_file = SimpleUploadedFile("danger.exe", b"MZ\x90\x00exe", content_type="application/octet-stream")
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "logo_image": exe_file,
            })
            tenant_a.refresh_from_db()
            curr_logo = tenant_a.logo_image.name if tenant_a.logo_image else ""
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or ("danger.exe" not in curr_logo)
            return ok, f"Status: {res.status_code}, Logo: {curr_logo}"

        run_case(2, "T2-BOUND-11", "Disallowed file extension .exe is rejected without saving to DB", t2_bound_11)

        def t2_bound_12():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            py_file = SimpleUploadedFile("exploit.py", b"import os", content_type="text/x-python")
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "cover_image": py_file,
            })
            tenant_a.refresh_from_db()
            curr_cover = tenant_a.cover_image.name if tenant_a.cover_image else ""
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or ("exploit.py" not in curr_cover)
            return ok, f"Status: {res.status_code}, Cover: {curr_cover}"

        run_case(2, "T2-BOUND-12", "Disallowed file extension .py is rejected without saving to DB", t2_bound_12)

        def t2_bound_13():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            pdf_file = SimpleUploadedFile("menu.pdf", b"%PDF-1.4...", content_type="application/pdf")
            res = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
                "logo_image": pdf_file,
            })
            tenant_a.refresh_from_db()
            curr_logo = tenant_a.logo_image.name if tenant_a.logo_image else ""
            ok = res.status_code == 400 or (res.status_code == 200 and "error" in res.content.decode("utf-8").lower()) or ("menu.pdf" not in curr_logo)
            return ok, f"Status: {res.status_code}, Logo: {curr_logo}"

        run_case(2, "T2-BOUND-13", "Disallowed file extension .pdf is rejected without saving to DB", t2_bound_13)

        # =============================================================
        # TIER 3: Cross-Feature & Security Combinations (RBAC & Isolation)
        # =============================================================
        print_tier_header(3, "Cross-Feature & Security Combinations (RBAC & Multi-Tenant)")

        # -------------------------------------------------------------
        # RBAC Tests
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Part A: Strict Role-Based Access Control (RBAC):{RESET}")

        def t3_sec_01():
            anon = Client()
            res = anon.get("/restaurant/profile/")
            ok = res.status_code == 302 and "/login" in res.headers.get("Location", "")
            return ok, f"Status: {res.status_code}, Location: {res.headers.get('Location')}"

        run_case(3, "T3-SEC-01", "Unauthenticated GET /restaurant/profile/ redirects to login (302)", t3_sec_01)

        def t3_sec_02():
            anon = Client()
            res = anon.post("/restaurant/profile/", {"name": "مطعم متسلل"})
            ok = res.status_code in [302, 403]
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-02", "Unauthenticated POST profile update redirects or rejected (302/403)", t3_sec_02)

        def t3_sec_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            ok = res.status_code == 200
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-03", "Owner user GET /restaurant/profile/ granted access (200 OK)", t3_sec_03)

        def t3_sec_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = post_profile_data(client, {
                "name": f"مطعم الأصالة المالك {unique_tag}",
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302]
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-04", "Owner user POST profile update allowed (200/302)", t3_sec_04)

        def t3_sec_05():
            client.force_login(hq_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            ok = res.status_code == 200
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-05", "HQ Manager user GET /restaurant/profile/ granted access (200 OK)", t3_sec_05)

        def t3_sec_06():
            client.force_login(hq_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            res = post_profile_data(client, {
                "name": f"مطعم الأصالة HQ {unique_tag}",
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": tenant_a.email,
                "address": tenant_a.address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            ok = res.status_code in [200, 302]
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-06", "HQ Manager user POST profile update allowed (200/302)", t3_sec_06)

        def t3_sec_07():
            client.force_login(cashier_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-07", "Floor Cashier GET /restaurant/profile/ strictly blocked (403 Forbidden)", t3_sec_07)

        def t3_sec_08():
            client.force_login(cashier_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = post_profile_data(client, {"name": "مطعم تم اختراقه بالكاشير"})
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-08", "Floor Cashier POST profile update strictly blocked (403 Forbidden)", t3_sec_08)

        def t3_sec_09():
            client.force_login(chef_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-09", "Kitchen Chef GET /restaurant/profile/ strictly blocked (403 Forbidden)", t3_sec_09)

        def t3_sec_10():
            client.force_login(chef_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = post_profile_data(client, {"name": "مطعم تم اختراقه بالشيف"})
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-10", "Kitchen Chef POST profile update strictly blocked (403 Forbidden)", t3_sec_10)

        def t3_sec_11():
            client.force_login(driver_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-11", "Delivery Driver GET /restaurant/profile/ strictly blocked (403 Forbidden)", t3_sec_11)

        def t3_sec_12():
            client.force_login(driver_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = post_profile_data(client, {"name": "مطعم تم اختراقه بالسائق"})
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-12", "Delivery Driver POST profile update strictly blocked (403 Forbidden)", t3_sec_12)

        def t3_sec_13():
            client.force_login(bm_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = client.get("/restaurant/profile/")
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-13", "Branch Manager (branch scope) GET /restaurant/profile/ blocked (403 Forbidden)", t3_sec_13)

        def t3_sec_14():
            client.force_login(bm_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session["active_branch_id"] = branch_a.id
            session.save()
            res = post_profile_data(client, {"name": "مطعم تم اختراقه بمدير الفرع"})
            ok = res.status_code == 403
            return ok, f"Status: {res.status_code}"

        run_case(3, "T3-SEC-14", "Branch Manager (branch scope) POST profile update blocked (403 Forbidden)", t3_sec_14)

        # -------------------------------------------------------------
        # Multi-Tenant Isolation Tests
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Part B: Multi-Tenant Data Isolation:{RESET}")

        def t3_iso_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            tenant_a.refresh_from_db()
            tenant_b.refresh_from_db()
            res = client.get("/restaurant/profile/")
            html = res.content.decode("utf-8") if res.status_code == 200 else ""
            ok = res.status_code == 200 and (tenant_b.name not in html) and (tenant_a.name in html)
            return ok, f"Tenant B name ('{tenant_b.name}') found in HTML: {tenant_b.name in html}, Tenant A name ('{tenant_a.name}') in HTML: {tenant_a.name in html}"

        run_case(3, "T3-ISO-01", "Tenant A profile view renders Tenant A data without Tenant B leakage", t3_iso_01)

        def t3_iso_02():
            client.force_login(owner_b_user)
            session = client.session
            session["active_tenant_id"] = tenant_b.id
            session.save()
            res = client.get("/restaurant/profile/")
            html = res.content.decode("utf-8") if res.status_code == 200 else ""
            ok = res.status_code == 200 and (tenant_a.name not in html) and (tenant_b.name in html)
            return ok, "Tenant A name found or Tenant B name missing"

        run_case(3, "T3-ISO-02", "Tenant B profile view renders Tenant B data without Tenant A leakage", t3_iso_02)

        def t3_iso_03():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            name_b_before = tenant_b.name
            res = post_profile_data(client, {
                "tenant_id": tenant_b.id,
                "name": "مطعم تم اختراقه بالحقن عبر المستأجرين",
                "bio": "محاولة تعديل بيانات المستأجر ب",
            })
            tenant_b.refresh_from_db()
            ok = tenant_b.name == name_b_before
            return ok, f"Tenant B name changed to: '{tenant_b.name}'"

        run_case(3, "T3-ISO-03", "Cross-tenant mutation via injected tenant_id strictly prevented", t3_iso_03)

        def t3_iso_04():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()
            snapshot_b = {
                "name": tenant_b.name,
                "bio": tenant_b.bio,
                "phone": tenant_b.phone,
                "email": tenant_b.email,
                "address": tenant_b.address,
                "brand_color": tenant_b.brand_color,
            }
            res = post_profile_data(client, {
                "name": f"مطعم الأصالة المتجدد {unique_tag}",
                "bio": "تحديث شامل لهوية المستأجر أ بالكامل",
                "phone": "0511223344",
                "email": "fresh@asala.sa",
                "address": "الرياض، بوليفارد رياض سيتي",
                "brand_color": "#059669",
            })
            tenant_b.refresh_from_db()
            current_b = {
                "name": tenant_b.name,
                "bio": tenant_b.bio,
                "phone": tenant_b.phone,
                "email": tenant_b.email,
                "address": tenant_b.address,
                "brand_color": tenant_b.brand_color,
            }
            ok = snapshot_b == current_b
            return ok, f"Snapshot: {snapshot_b}, Current: {current_b}"

        run_case(3, "T3-ISO-04", "Tenant B attributes remain 100% intact after Tenant A modifications", t3_iso_04)

        # =============================================================
        # TIER 4: Real-World Scenarios (Full Lifecycle End-to-End)
        # =============================================================
        print_tier_header(4, "Real-World Scenarios (End-to-End User Journeys)")

        # -------------------------------------------------------------
        # Scenario 1: Complete Onboarding / Profile Setup Flow
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Scenario 1: Complete Restaurant Profile Onboarding Lifecycle:{RESET}")

        def t4_scen_01():
            client.force_login(owner_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()

            s1_get1 = client.get("/restaurant/profile/")
            s1_logo = SimpleUploadedFile("onboard_logo.png", TINY_PNG, content_type="image/png")
            s1_cover = SimpleUploadedFile("onboard_cover.jpg", TINY_JPG, content_type="image/jpeg")
            s1_payload = {
                "name": f"مطعم الضيافة المتكامل {unique_tag}",
                "bio": "أفخر أنواع الضيافة والمأكولات الخليجية في قلب العاصمة",
                "phone": "0119988776",
                "email": "welcome@aldiafa.sa",
                "address": "الرياض، حي الملقا، طريق أنس بن مالك",
                "brand_color": "#4338CA",
                "logo_image": s1_logo,
                "cover_image": s1_cover,
            }
            s1_post = post_profile_data(client, s1_payload)
            tenant_a.refresh_from_db()

            s1_get2 = client.get("/restaurant/profile/")
            s1_html2 = s1_get2.content.decode("utf-8") if s1_get2.status_code == 200 else ""

            ok = (
                s1_get1.status_code == 200 and
                s1_post.status_code in [200, 302] and
                tenant_a.name == s1_payload["name"] and
                tenant_a.bio == s1_payload["bio"] and
                tenant_a.phone == s1_payload["phone"] and
                tenant_a.email == s1_payload["email"] and
                tenant_a.address == s1_payload["address"] and
                tenant_a.brand_color.upper() == s1_payload["brand_color"].upper() and
                tenant_a.logo_image and "onboard_logo" in tenant_a.logo_image.name and
                tenant_a.cover_image and "onboard_cover" in tenant_a.cover_image.name and
                s1_payload["name"] in s1_html2
            )
            if ok:
                uploaded_media_cleanup.extend([tenant_a.logo_image, tenant_a.cover_image])
            return ok, f"Post status: {s1_post.status_code}, DB name: {tenant_a.name}, Logo: {tenant_a.logo_image}"

        run_case(4, "T4-SCEN-01", "Complete onboarding lifecycle: initial GET, full 8-field submission, DB verification, subsequent GET rendering", t4_scen_01)

        # -------------------------------------------------------------
        # Scenario 2: Incremental Re-branding Lifecycle
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Scenario 2: Incremental Re-branding Lifecycle:{RESET}")

        def t4_scen_02():
            client.force_login(hq_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()

            prior_phone = tenant_a.phone
            prior_email = tenant_a.email
            prior_address = tenant_a.address
            prior_cover = tenant_a.cover_image.name if tenant_a.cover_image else ""

            s2_new_color = "#7C3AED"
            s2_new_logo = SimpleUploadedFile("rebrand_logo.png", TINY_PNG, content_type="image/png")
            s2_post = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": prior_phone,
                "email": prior_email,
                "address": prior_address,
                "brand_color": s2_new_color,
                "logo_image": s2_new_logo,
            })
            tenant_a.refresh_from_db()
            s2_get = client.get("/restaurant/profile/")
            s2_html = s2_get.content.decode("utf-8") if s2_get.status_code == 200 else ""

            ok = (
                s2_post.status_code in [200, 302] and
                tenant_a.brand_color.upper() == s2_new_color.upper() and
                tenant_a.logo_image and "rebrand_logo" in tenant_a.logo_image.name and
                tenant_a.phone == prior_phone and
                tenant_a.email == prior_email and
                tenant_a.address == prior_address and
                (tenant_a.cover_image.name if tenant_a.cover_image else "") == prior_cover and
                s2_new_color.lower() in s2_html.lower()
            )
            if ok:
                uploaded_media_cleanup.append(tenant_a.logo_image)
            return ok, f"Post status: {s2_post.status_code}, Color: {tenant_a.brand_color}, Logo: {tenant_a.logo_image}"

        run_case(4, "T4-SCEN-02", "Incremental re-branding lifecycle: updated color & logo, verified contacts & cover untouched, confirmed in subsequent GET", t4_scen_02)

        # -------------------------------------------------------------
        # Scenario 3: Validation Error Recovery & Re-submission Lifecycle
        # -------------------------------------------------------------
        print(f"\n{YELLOW}Scenario 3: Validation Error Recovery Lifecycle:{RESET}")

        def t4_scen_03():
            client.force_login(hq_user)
            session = client.session
            session["active_tenant_id"] = tenant_a.id
            session.save()

            state_before = {
                "name": tenant_a.name,
                "email": tenant_a.email,
                "address": tenant_a.address,
            }
            s3_fail = post_profile_data(client, {
                "name": tenant_a.name,
                "email": "not_an_email_at_all",
                "address": "عنوان جديد لم يحفظ",
            })
            tenant_a.refresh_from_db()
            db_protected = tenant_a.email == state_before["email"]

            corrected_email = "corrected_hq@aldiafa.sa"
            new_address = "الرياض، برج الفيصلية، الطابق 15"
            s3_success = post_profile_data(client, {
                "name": tenant_a.name,
                "bio": tenant_a.bio,
                "phone": tenant_a.phone,
                "email": corrected_email,
                "address": new_address,
                "brand_color": tenant_a.brand_color,
            })
            tenant_a.refresh_from_db()
            s3_get = client.get("/restaurant/profile/")
            s3_html = s3_get.content.decode("utf-8") if s3_get.status_code == 200 else ""

            ok = (
                db_protected and
                s3_success.status_code in [200, 302] and
                tenant_a.email == corrected_email and
                tenant_a.address == new_address and
                corrected_email in s3_html
            )
            return ok, f"Fail status: {s3_fail.status_code}, Success: {s3_success.status_code}, Email: {tenant_a.email}"

        run_case(4, "T4-SCEN-03", "Validation error recovery: invalid attempt rejected with zero corruption, corrected re-submission persisted and verified in GET", t4_scen_03)

    finally:
        # -------------------------------------------------------------
        # Cleanup Fixtures
        # -------------------------------------------------------------
        print(f"\n{CYAN}{BOLD}Cleaning up temporary test records and uploaded media...{RESET}")
        safe_cleanup_media(uploaded_media_cleanup)
        try:
            # Restore Tenant A
            tenant_a.logo_image = None
            tenant_a.cover_image = None
            tenant_a.save()

            # Delete test users and profiles
            UserProfile.objects.filter(user__in=[owner_user, hq_user, cashier_user, chef_user, driver_user, bm_user, owner_b_user]).delete()
            User.objects.filter(id__in=[owner_user.id, hq_user.id, cashier_user.id, chef_user.id, driver_user.id, bm_user.id, owner_b_user.id]).delete()
            hq_mgr_role.delete()
            cashier_role.delete()
            chef_role.delete()
            driver_role.delete()
            bm_role.delete()
            print("  All temporary test records and users safely purged.")
        except Exception as e:
            print(f"  Warning during cleanup: {e}")

    # Print summary and exit
    all_passed = tracker.summary()
    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        exit_code = run_restaurant_profile_tests()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n{RED}{BOLD}FATAL TEST EXECUTION ERROR:{RESET} {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
