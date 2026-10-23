#!/usr/bin/env python3
"""
Adversarial Stress Harness for Restaurant Profile Management.
Probes RBAC bypass, cross-tenant isolation, malicious injection, and media upload edge cases.
"""

import os
import sys
import io
import json
import re
import shutil
from pathlib import Path

# Setup Django Environment
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
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

# 1x1 Valid PNG bytes
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01Haf\xa0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# 1x1 Valid JPEG bytes
VALID_JPG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12"
    b"\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<."
    b"342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01"
    b"\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06"
    b"\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)


class AdversarialTestTracker:
    def __init__(self):
        self.sections = {
            "RBAC_BYPASS": {"passed": 0, "failed": 0, "tests": []},
            "CROSS_TENANT": {"passed": 0, "failed": 0, "tests": []},
            "INJECTION": {"passed": 0, "failed": 0, "tests": []},
            "MEDIA_UPLOADS": {"passed": 0, "failed": 0, "tests": []},
        }
        self.findings = []

    def record_pass(self, section, test_id, desc):
        self.sections[section]["passed"] += 1
        self.sections[section]["tests"].append((test_id, True, desc))
        print(f"  {GREEN}✔ PASS [{test_id}]:{RESET} {desc}")

    def record_fail(self, section, test_id, desc, detail):
        self.sections[section]["failed"] += 1
        self.sections[section]["tests"].append((test_id, False, f"{desc} -> {detail}"))
        self.findings.append({"section": section, "test_id": test_id, "desc": desc, "detail": detail})
        print(f"  {RED}✘ VULN/FAIL [{test_id}]:{RESET} {desc}")
        print(f"       {RED}Detail: {detail}{RESET}")

    def summary(self):
        print(f"\n{CYAN}{BOLD}{'='*75}{RESET}")
        print(f"{CYAN}{BOLD}               ADVERSARIAL STRESS TEST SUITE SUMMARY{RESET}")
        print(f"{CYAN}{BOLD}{'='*75}{RESET}")
        tot_p = sum(s["passed"] for s in self.sections.values())
        tot_f = sum(s["failed"] for s in self.sections.values())
        tot = tot_p + tot_f

        for s_name, s_data in self.sections.items():
            s_tot = s_data["passed"] + s_data["failed"]
            pct = (s_data["passed"] / s_tot * 100) if s_tot > 0 else 0
            color = GREEN if s_data["failed"] == 0 else RED
            print(f"  {color}{s_name}: {s_data['passed']}/{s_tot} passed ({pct:.1f}%){RESET}")

        print(f"{CYAN}{'-'*75}{RESET}")
        print(f"Total probes: {tot} | Passed: {tot_p} | Vulnerabilities/Failures: {tot_f}")
        return tot_f == 0


def create_adversarial_fixtures():
    """Create isolated test fixtures for adversarial testing."""
    fixtures = {}

    # 1. Tenant Alpha (Primary Target)
    t_alpha, _ = Tenant.objects.get_or_create(
        slug="adv-tenant-alpha",
        defaults={
            "name": "Alpha Adversarial Grill",
            "bio": "Original Alpha Bio",
            "phone": "+966501111111",
            "email": "alpha@adversarial.local",
            "address": "Riyadh Alpha HQ",
            "brand_color": "#6366F1",
            "is_active": True,
        }
    )
    b_alpha, _ = Branch.objects.get_or_create(
        tenant=t_alpha,
        name="Alpha Main Branch",
        defaults={"status": "active"}
    )
    fixtures["t_alpha"] = t_alpha
    fixtures["b_alpha"] = b_alpha

    # 2. Tenant Beta (Victim Tenant for Cross-Tenant Tampering)
    t_beta, _ = Tenant.objects.get_or_create(
        slug="adv-tenant-beta",
        defaults={
            "name": "Beta Victim Bistro",
            "bio": "Original Beta Bio",
            "phone": "+966502222222",
            "email": "beta@victim.local",
            "address": "Jeddah Beta HQ",
            "brand_color": "#0E382A",
            "is_active": True,
        }
    )
    b_beta, _ = Branch.objects.get_or_create(
        tenant=t_beta,
        name="Beta Main Branch",
        defaults={"status": "active"}
    )
    fixtures["t_beta"] = t_beta
    fixtures["b_beta"] = b_beta

    # 3. Users for Tenant Alpha
    u_alpha_owner, _ = User.objects.get_or_create(
        username="adv_alpha_owner",
        defaults={"email": "alpha_owner@adversarial.local", "is_staff": False, "is_superuser": False}
    )
    u_alpha_owner.set_password("pass123")
    u_alpha_owner.save()
    p_alpha_owner, _ = UserProfile.objects.get_or_create(
        user=u_alpha_owner,
        defaults={"tenant": t_alpha, "branch": b_alpha, "role": "owner"}
    )
    p_alpha_owner.tenant = t_alpha
    p_alpha_owner.role = "owner"
    p_alpha_owner.save()
    fixtures["u_alpha_owner"] = u_alpha_owner

    # Floor Cashier (Branch Staff)
    u_alpha_cashier, _ = User.objects.get_or_create(
        username="adv_alpha_cashier",
        defaults={"email": "alpha_cashier@adversarial.local", "is_staff": False, "is_superuser": False}
    )
    u_alpha_cashier.set_password("pass123")
    u_alpha_cashier.save()
    p_alpha_cashier, _ = UserProfile.objects.get_or_create(
        user=u_alpha_cashier,
        defaults={"tenant": t_alpha, "branch": b_alpha, "role": "cashier"}
    )
    p_alpha_cashier.tenant = t_alpha
    p_alpha_cashier.role = "cashier"
    p_alpha_cashier.save()
    fixtures["u_alpha_cashier"] = u_alpha_cashier

    # Kitchen Chef
    u_alpha_chef, _ = User.objects.get_or_create(
        username="adv_alpha_chef",
        defaults={"email": "alpha_chef@adversarial.local", "is_staff": False, "is_superuser": False}
    )
    u_alpha_chef.set_password("pass123")
    u_alpha_chef.save()
    p_alpha_chef, _ = UserProfile.objects.get_or_create(
        user=u_alpha_chef,
        defaults={"tenant": t_alpha, "branch": b_alpha, "role": "chef"}
    )
    p_alpha_chef.tenant = t_alpha
    p_alpha_chef.role = "chef"
    p_alpha_chef.save()
    fixtures["u_alpha_chef"] = u_alpha_chef

    # Delivery Driver
    u_alpha_driver, _ = User.objects.get_or_create(
        username="adv_alpha_driver",
        defaults={"email": "alpha_driver@adversarial.local", "is_staff": False, "is_superuser": False}
    )
    u_alpha_driver.set_password("pass123")
    u_alpha_driver.save()
    p_alpha_driver, _ = UserProfile.objects.get_or_create(
        user=u_alpha_driver,
        defaults={"tenant": t_alpha, "branch": b_alpha, "role": "driver"}
    )
    p_alpha_driver.tenant = t_alpha
    p_alpha_driver.role = "driver"
    p_alpha_driver.save()
    fixtures["u_alpha_driver"] = u_alpha_driver

    # Branch Manager without HQ perms
    u_alpha_bm, _ = User.objects.get_or_create(
        username="adv_alpha_bm",
        defaults={"email": "alpha_bm@adversarial.local", "is_staff": False, "is_superuser": False}
    )
    u_alpha_bm.set_password("pass123")
    u_alpha_bm.save()
    jr_branch, _ = JobRole.objects.get_or_create(
        tenant=t_alpha,
        name="Adv Branch Manager Role",
        defaults={"scope": "branch"}
    )
    jr_branch.sync_with_django_group()
    jr_branch.set_permissions(["pos_access", "branch_view_orders"])
    if jr_branch.group:
        u_alpha_bm.groups.add(jr_branch.group)

    p_alpha_bm, _ = UserProfile.objects.get_or_create(
        user=u_alpha_bm,
        defaults={"tenant": t_alpha, "branch": b_alpha, "role": "manager", "job_role": jr_branch}
    )
    p_alpha_bm.tenant = t_alpha
    p_alpha_bm.role = "manager"
    p_alpha_bm.job_role = jr_branch
    p_alpha_bm.save()
    fixtures["u_alpha_bm"] = u_alpha_bm

    # 4. User for Tenant Beta (Owner)
    u_beta_owner, _ = User.objects.get_or_create(
        username="adv_beta_owner",
        defaults={"email": "beta_owner@victim.local", "is_staff": False, "is_superuser": False}
    )
    u_beta_owner.set_password("pass123")
    u_beta_owner.save()
    p_beta_owner, _ = UserProfile.objects.get_or_create(
        user=u_beta_owner,
        defaults={"tenant": t_beta, "branch": b_beta, "role": "owner"}
    )
    p_beta_owner.tenant = t_beta
    p_beta_owner.role = "owner"
    p_beta_owner.save()
    fixtures["u_beta_owner"] = u_beta_owner

    return fixtures


def cleanup_adversarial_fixtures():
    """Purge temporary test data and uploaded files safely."""
    for slug in ["adv-tenant-alpha", "adv-tenant-beta"]:
        Tenant.objects.filter(slug=slug).delete()

    User.objects.filter(username__startswith="adv_").delete()
    JobRole.objects.filter(name__startswith="Adv ").delete()

    # Clean media test uploads
    media_root = Path(settings.MEDIA_ROOT)
    for folder in ["tenant_logos", "tenant_covers"]:
        target_dir = media_root / folder
        if target_dir.exists():
            for f in target_dir.glob("adv_*"):
                try:
                    f.unlink()
                except Exception:
                    pass
            for f in target_dir.glob("corrupt_*"):
                try:
                    f.unlink()
                except Exception:
                    pass
            for f in target_dir.glob("empty_*"):
                try:
                    f.unlink()
                except Exception:
                    pass


# =========================================================================
# PROBE SUITE 1: RBAC BYPASS PROBES
# =========================================================================
def run_rbac_bypass_probes(tracker, f):
    print(f"\n{YELLOW}--- PROBING 1: RBAC Enforcement & Authorization Bypass ---{RESET}")

    client_anon = Client()
    endpoints = [
        ("/restaurant/profile/", "GET"),
        ("/restaurant/profile/", "POST"),
        ("/api/restaurant/profile/", "POST"),
        ("/api/settings/branding/", "POST"),
    ]

    # Test 1.1: Unauthenticated attacks
    for ep, method in endpoints:
        test_id = f"ADV-RBAC-ANON-{ep.strip('/').replace('/', '_')}-{method}"
        if method == "GET":
            res = client_anon.get(ep)
        else:
            res = client_anon.post(ep, {"name": "Hacked Name"})
        # Should redirect to login (302) or return 401/403
        if res.status_code in [302, 401, 403]:
            tracker.record_pass("RBAC_BYPASS", test_id, f"Unauthenticated {method} {ep} rejected with {res.status_code}")
        else:
            tracker.record_fail("RBAC_BYPASS", test_id, f"Unauthenticated {method} {ep} allowed", f"Status: {res.status_code}")

    # Test 1.2: Branch Cashier POST attacks
    client_cashier = Client()
    client_cashier.force_login(f["u_alpha_cashier"])
    attack_payloads = [
        ("/restaurant/profile/", {"name": "Cashier Tamper Name"}, "Form POST"),
        ("/restaurant/profile/", json.dumps({"name": "Cashier Tamper Name"}), "JSON POST"),
        ("/api/restaurant/profile/", {"name": "Cashier Tamper Name"}, "API Form POST"),
        ("/api/restaurant/profile/", json.dumps({"name": "Cashier Tamper Name"}), "API JSON POST"),
        ("/api/settings/branding/", {"name": "Cashier Tamper Name"}, "Branding Form POST"),
        ("/api/settings/branding/", json.dumps({"name": "Cashier Tamper Name"}), "Branding JSON POST"),
    ]

    initial_name = Tenant.objects.get(id=f["t_alpha"].id).name

    for idx, (ep, payload, desc) in enumerate(attack_payloads, 1):
        test_id = f"ADV-RBAC-CASHIER-{idx:02d}"
        if isinstance(payload, str):
            res = client_cashier.post(ep, data=payload, content_type="application/json")
        else:
            res = client_cashier.post(ep, data=payload)
        
        # Verify 403
        curr_name = Tenant.objects.get(id=f["t_alpha"].id).name
        if res.status_code == 403 and curr_name == initial_name:
            tracker.record_pass("RBAC_BYPASS", test_id, f"Cashier {desc} to {ep} strictly blocked (403), DB untouched")
        else:
            tracker.record_fail("RBAC_BYPASS", test_id, f"Cashier {desc} to {ep} bypassed RBAC", f"Status: {res.status_code}, Name in DB: '{curr_name}'")

    # Test 1.3: Kitchen Chef & Delivery Driver & Branch Manager
    other_roles = [
        ("CHEF", f["u_alpha_chef"]),
        ("DRIVER", f["u_alpha_driver"]),
        ("BRANCH_MGR", f["u_alpha_bm"]),
    ]

    for role_label, user_obj in other_roles:
        c = Client()
        c.force_login(user_obj)
        res_post = c.post("/api/restaurant/profile/", {"name": f"{role_label} Injected Name"})
        curr_name = Tenant.objects.get(id=f["t_alpha"].id).name
        test_id = f"ADV-RBAC-{role_label}-API"
        if res_post.status_code == 403 and curr_name == initial_name:
            tracker.record_pass("RBAC_BYPASS", test_id, f"{role_label} POST to /api/restaurant/profile/ blocked (403)")
        else:
            tracker.record_fail("RBAC_BYPASS", test_id, f"{role_label} POST to /api/restaurant/profile/ succeeded", f"Status: {res_post.status_code}")

    # Test 1.4: Method Tampering (PUT / DELETE / PATCH on profile endpoints)
    c_owner = Client()
    c_owner.force_login(f["u_alpha_owner"])
    for verb in ["PUT", "DELETE", "PATCH"]:
        test_id = f"ADV-RBAC-METHOD-{verb}"
        res_verb = getattr(c_owner, verb.lower())("/api/restaurant/profile/", data={"name": "Tamper"})
        # Should be 400 (Bad Request: "POST required") or 405 (Method Not Allowed)
        if res_verb.status_code in [400, 405]:
            tracker.record_pass("RBAC_BYPASS", test_id, f"{verb} on /api/restaurant/profile/ handled safely ({res_verb.status_code})")
        else:
            tracker.record_fail("RBAC_BYPASS", test_id, f"{verb} on /api/restaurant/profile/ returned unexpected status", f"Status: {res_verb.status_code}")


# =========================================================================
# PROBE SUITE 2: CROSS-TENANT ISOLATION PROBES
# =========================================================================
def run_cross_tenant_probes(tracker, f):
    print(f"\n{YELLOW}--- PROBING 2: Multi-Tenant Boundary & Cross-Tenant Tampering ---{RESET}")

    c_alpha = Client()
    c_alpha.force_login(f["u_alpha_owner"])

    initial_beta = Tenant.objects.get(id=f["t_beta"].id)
    beta_id = initial_beta.id
    beta_slug = initial_beta.slug
    beta_original_name = initial_beta.name
    beta_original_color = initial_beta.brand_color

    # Test 2.1: Injected tenant_id parameter in Form POST
    test_id = "ADV-TENANT-FORM-INJECT"
    res1 = c_alpha.post("/restaurant/profile/", {
        "name": "Alpha Name Change",
        "tenant_id": beta_id,
        "tenant": beta_id,
        "tenant_slug": beta_slug,
    })
    beta_after_1 = Tenant.objects.get(id=beta_id)
    if beta_after_1.name == beta_original_name:
        tracker.record_pass("CROSS_TENANT", test_id, "Form POST with injected tenant_id/tenant_slug ignored; Tenant B untouched")
    else:
        tracker.record_fail("CROSS_TENANT", test_id, "Tenant B mutated by foreign Form POST!", f"Name changed to '{beta_after_1.name}'")

    # Test 2.2: Injected tenant_id in JSON API payload
    test_id = "ADV-TENANT-JSON-INJECT"
    res2 = c_alpha.post("/api/restaurant/profile/", data=json.dumps({
        "name": "Beta Overwritten By Alpha",
        "tenant_id": beta_id,
        "tenant": beta_id,
        "brand_color": "#FF0000",
    }), content_type="application/json")
    beta_after_2 = Tenant.objects.get(id=beta_id)
    if beta_after_2.name == beta_original_name and beta_after_2.brand_color == beta_original_color:
        tracker.record_pass("CROSS_TENANT", test_id, "JSON API POST with injected tenant_id ignored; Tenant B untouched")
    else:
        tracker.record_fail("CROSS_TENANT", test_id, "Tenant B mutated by foreign JSON payload!", f"Name: {beta_after_2.name}, Color: {beta_after_2.brand_color}")

    # Test 2.3: Query String Injection (?tenant_id=Beta.id)
    test_id = "ADV-TENANT-QUERY-INJECT"
    res3 = c_alpha.post(f"/api/restaurant/profile/?tenant_id={beta_id}", data={"name": "Alpha Valid Name"})
    beta_after_3 = Tenant.objects.get(id=beta_id)
    if beta_after_3.name == beta_original_name:
        tracker.record_pass("CROSS_TENANT", test_id, "POST with query param ?tenant_id= ignored; Tenant B untouched")
    else:
        tracker.record_fail("CROSS_TENANT", test_id, "Tenant B mutated via query param injection!", f"Name: {beta_after_3.name}")

    # Test 2.4: Injected X-Tenant-ID / Tenant-ID Custom Headers
    test_id = "ADV-TENANT-HEADER-INJECT"
    res4 = c_alpha.post(
        "/api/restaurant/profile/",
        data={"name": "Header Tamper"},
        HTTP_X_TENANT_ID=str(beta_id),
        HTTP_TENANT_ID=str(beta_id)
    )
    beta_after_4 = Tenant.objects.get(id=beta_id)
    if beta_after_4.name == beta_original_name:
        tracker.record_pass("CROSS_TENANT", test_id, "Injected HTTP_X_TENANT_ID header ignored; Tenant B untouched")
    else:
        tracker.record_fail("CROSS_TENANT", test_id, "Tenant B mutated via X-Tenant-ID header!", f"Name: {beta_after_4.name}")

    # Test 2.5: Host Header Spoofing (Passing Tenant Beta Host while authenticated as Alpha)
    test_id = "ADV-TENANT-HOST-SPOOF"
    res5 = c_alpha.post(
        "/api/restaurant/profile/",
        data={"name": "Host Header Injected"},
        HTTP_HOST=f"{beta_slug}.restaurant.local"
    )
    beta_after_5 = Tenant.objects.get(id=beta_id)
    if beta_after_5.name == beta_original_name:
        tracker.record_pass("CROSS_TENANT", test_id, "Spoofed HTTP_HOST ignored for authenticated user; Tenant B untouched")
    else:
        tracker.record_fail("CROSS_TENANT", test_id, "Tenant B mutated via HTTP_HOST spoofing!", f"Name: {beta_after_5.name}")

    # Test 2.6: Session Tampering (Attempting to set active_tenant_id as non-admin user)
    test_id = "ADV-TENANT-SESSION-TAMPER"
    session = c_alpha.session
    session["active_tenant_id"] = beta_id
    session.save()
    res6 = c_alpha.post("/api/restaurant/profile/", data={"name": "Session Injected Name"})
    beta_after_6 = Tenant.objects.get(id=beta_id)
    if beta_after_6.name == beta_original_name:
        tracker.record_pass("CROSS_TENANT", test_id, "Session active_tenant_id ignored for regular tenant owner; Tenant B untouched")
    else:
        tracker.record_fail("CROSS_TENANT", test_id, "Tenant B mutated via session tampering!", f"Name: {beta_after_6.name}")


# =========================================================================
# PROBE SUITE 3: MALICIOUS INJECTION PROBES
# =========================================================================
def run_injection_probes(tracker, f):
    print(f"\n{YELLOW}--- PROBING 3: Malicious Injection (SQLi, XSS, Length Overflow, Null Bytes) ---{RESET}")

    c = Client()
    c.force_login(f["u_alpha_owner"])

    # 3.1: SQL Injection in Name, Bio, Address, Phone
    sqli_payloads = [
        ("SQLI-NAME-OR", "name", "' OR '1'='1"),
        ("SQLI-NAME-DROP", "name", "'; DROP TABLE core_tenant; --"),
        ("SQLI-NAME-UNION", "name", "1' UNION SELECT username, password, email FROM auth_user--"),
        ("SQLI-BIO-STACKED", "bio", "Bio'; UPDATE tenants_tenant SET name='pwned' WHERE id=1; --"),
        ("SQLI-ADDR-COMMENT", "address", "Road 123' /* comment */ --"),
        ("SQLI-PHONE-ESCAPE", "phone", "+966' OR '1'='1"),
    ]

    for test_id, field, payload in sqli_payloads:
        # Save payload
        data = {"name": "Alpha Grill Safe Name"}
        data[field] = payload
        res = c.post("/api/restaurant/profile/", data=data)
        
        # Verify DB is healthy and intact
        try:
            count = Tenant.objects.count()
            t_refetched = Tenant.objects.get(id=f["t_alpha"].id)
            val_in_db = getattr(t_refetched, field)
            # Should not crash with 500, table should still exist
            if res.status_code in [200, 400] and count >= 2:
                tracker.record_pass("INJECTION", test_id, f"SQLi payload in {field} safely stored as literal text or rejected without SQL syntax error")
            else:
                tracker.record_fail("INJECTION", test_id, f"SQLi probe triggered unexpected status", f"Status: {res.status_code}")
        except Exception as e:
            tracker.record_fail("INJECTION", test_id, f"SQLi probe crashed database query", f"Exception: {e}")

    # 3.2: SQLi in brand_color & email (Should be strictly rejected by validation)
    sqli_strict_fields = [
        ("SQLI-COLOR-UNION", "brand_color", "#123456' UNION SELECT 1--"),
        ("SQLI-EMAIL-OR", "email", "' OR 1=1--@domain.com"),
    ]
    for test_id, field, payload in sqli_strict_fields:
        data = {"name": "Alpha Grill Safe Name", field: payload}
        res = c.post("/api/restaurant/profile/", data=data)
        if res.status_code == 400:
            tracker.record_pass("INJECTION", test_id, f"SQLi in {field} rejected by format validator (HTTP 400)")
        else:
            tracker.record_fail("INJECTION", test_id, f"SQLi in {field} was NOT rejected by validator", f"Status: {res.status_code}")

    # 3.3: Stored XSS Payloads in Name, Bio, Address
    xss_payloads = [
        ("XSS-NAME-SCRIPT", "name", "<script>alert('XSS_NAME')</script>"),
        ("XSS-BIO-IMG", "bio", "<img src=x onerror=alert('XSS_BIO')>"),
        ("XSS-ADDR-SVG", "address", "<svg/onload=alert('XSS_ADDR')>"),
        ("XSS-NAME-TAGCLOSE", "name", '"><script>alert(1)</script>'),
    ]

    for test_id, field, payload in xss_payloads:
        data = {"name": "Alpha Grill Safe Name"}
        data[field] = payload
        res_post = c.post("/api/restaurant/profile/", data=data)
        
        # Now fetch profile page HTML and check escaping
        res_get = c.get("/restaurant/profile/")
        html_content = res_get.content.decode("utf-8")

        # In raw unescaped form, <script>alert('XSS_NAME')</script> or <img src=x onerror=...> must NOT appear unescaped in HTML
        # In Django template auto-escaping:
        # < becomes &lt;
        # > becomes &gt;
        # " becomes &quot;
        # ' becomes &#x27;
        raw_unescaped = payload in html_content
        escaped_present = any(esc in html_content for esc in ["&lt;script&gt;", "&lt;img", "&lt;svg", "&quot;&gt;&lt;script"])
        
        # Also check javascript block escaping (escapejs)
        # In JS block: \u003Cscript\u003E or similar
        js_safe = True
        if "<script>alert(" in html_content or "<img src=x onerror=" in html_content or "<svg/onload=" in html_content:
            js_safe = False

        if not raw_unescaped and js_safe:
            tracker.record_pass("INJECTION", test_id, f"Stored XSS in {field} properly HTML/JS-escaped in rendered profile view")
        else:
            tracker.record_fail("INJECTION", test_id, f"Stored XSS in {field} rendered unescaped in HTML!", f"Raw payload found in HTML: {raw_unescaped}, JS safe: {js_safe}")

    # 3.4: XSS / CSS Injection in brand_color
    color_injections = [
        ("XSS-COLOR-TAG", "#6366F1<script>alert(1)</script>"),
        ("XSS-COLOR-STYLE", "red; } </style><script>alert(1)</script>"),
        ("XSS-COLOR-JS", "' onfocus='alert(1)"),
        ("XSS-COLOR-HEX-SUFFIX", "#FFFFFF; background:url('javascript:alert(1)')"),
    ]
    for test_id, payload in color_injections:
        res = c.post("/api/restaurant/profile/", data={"name": "Alpha Grill", "brand_color": payload})
        if res.status_code == 400:
            tracker.record_pass("INJECTION", test_id, f"Color injection '{payload[:25]}...' strictly rejected (400)")
        else:
            tracker.record_fail("INJECTION", test_id, f"Color injection was accepted!", f"Status: {res.status_code}")

    # 3.5: Extremely Long Strings (Buffer / Length Boundary Enforcement)
    length_probes = [
        ("LEN-NAME-255", "name", "A" * 255, 200, "255 chars in name accepted"),
        ("LEN-NAME-256", "name", "A" * 256, 400, "256 chars in name rejected (400)"),
        ("LEN-NAME-5000", "name", "A" * 5000, 400, "5000 chars in name rejected (400)"),
        ("LEN-BIO-255", "bio", "B" * 255, 200, "255 chars in bio accepted"),
        ("LEN-BIO-256", "bio", "B" * 256, 400, "256 chars in bio rejected (400)"),
        ("LEN-BIO-5000", "bio", "B" * 5000, 400, "5000 chars in bio rejected (400)"),
        ("LEN-PHONE-50", "phone", "1" * 50, 200, "50 chars in phone accepted"),
        ("LEN-PHONE-51", "phone", "1" * 51, 400, "51 chars in phone rejected (400)"),
        ("LEN-ADDR-255", "address", "C" * 255, 200, "255 chars in address accepted"),
        ("LEN-ADDR-256", "address", "C" * 256, 400, "256 chars in address rejected (400)"),
        ("LEN-EMAIL-255", "email", ("e" * 245) + "@domain.local", 400, "255+ chars in email rejected (400)"),
    ]

    for test_id, field, value, exp_status, desc in length_probes:
        data = {"name": "Alpha Length Test"}
        data[field] = value
        res = c.post("/api/restaurant/profile/", data=data)
        if res.status_code == exp_status:
            tracker.record_pass("INJECTION", test_id, desc)
        else:
            tracker.record_fail("INJECTION", test_id, f"Length check for {field} failed", f"Expected {exp_status}, got {res.status_code}")

    # 3.6: Null Bytes in Strings
    null_byte_probes = [
        ("NULL-NAME", "name", "Alpha\x00HackedName"),
        ("NULL-BIO", "bio", "Bio\x00HackedBio"),
        ("NULL-PHONE", "phone", "+966500\x000000"),
        ("NULL-EMAIL", "email", "adv\x00test@domain.local"),
        ("NULL-ADDR", "address", "Street 1\x00Suite 2"),
    ]

    for test_id, field, payload in null_byte_probes:
        data = {"name": "Alpha Null Byte Test"}
        data[field] = payload
        try:
            res = c.post("/api/restaurant/profile/", data=data)
            # In Django / SQLite, null bytes in text should either be stripped, rejected (400), or stored safely without uncaught 500
            if res.status_code in [200, 400]:
                tracker.record_pass("INJECTION", test_id, f"Null byte in {field} handled safely ({res.status_code})")
            else:
                tracker.record_fail("INJECTION", test_id, f"Null byte in {field} produced unexpected status", f"Status: {res.status_code}")
        except Exception as e:
            tracker.record_fail("INJECTION", test_id, f"Null byte in {field} caused unhandled exception", str(e))


# =========================================================================
# PROBE SUITE 4: MEDIA UPLOAD EDGE CASE PROBES
# =========================================================================
def run_media_upload_probes(tracker, f):
    print(f"\n{YELLOW}--- PROBING 4: Media Upload Edge Cases (0-byte, corrupt, fake MIME, dotfiles) ---{RESET}")

    c = Client()
    c.force_login(f["u_alpha_owner"])

    # 4.1: 0-Byte Files
    # Test uploading 0-byte file for logo
    test_id = "ADV-MEDIA-0BYTE-LOGO"
    empty_logo = SimpleUploadedFile("empty_logo.png", b"", content_type="image/png")
    res_0b_logo = c.post("/api/restaurant/profile/", data={
        "name": "Alpha 0Byte Test",
        "logo_image": empty_logo
    })
    # Inspect what happened: Did it crash? Or did it reject? Or did it save?
    t_after_0b = Tenant.objects.get(id=f["t_alpha"].id)
    # Check if system handled it without crashing (status != 500)
    if res_0b_logo.status_code in [200, 400]:
        tracker.record_pass("MEDIA_UPLOADS", test_id, f"0-byte logo upload handled without crash ({res_0b_logo.status_code})")
    else:
        tracker.record_fail("MEDIA_UPLOADS", test_id, "0-byte logo upload crashed server", f"Status: {res_0b_logo.status_code}")

    # Test uploading 0-byte file for cover
    test_id = "ADV-MEDIA-0BYTE-COVER"
    empty_cover = SimpleUploadedFile("empty_cover.jpg", b"", content_type="image/jpeg")
    res_0b_cover = c.post("/api/restaurant/profile/", data={
        "name": "Alpha 0Byte Cover Test",
        "cover_image": empty_cover
    })
    if res_0b_cover.status_code in [200, 400]:
        tracker.record_pass("MEDIA_UPLOADS", test_id, f"0-byte cover upload handled without crash ({res_0b_cover.status_code})")
    else:
        tracker.record_fail("MEDIA_UPLOADS", test_id, "0-byte cover upload crashed server", f"Status: {res_0b_cover.status_code}")

    # 4.2: Corrupt Image Headers (Fake image header / random binary noise)
    test_id = "ADV-MEDIA-CORRUPT-HEADER"
    corrupt_file = SimpleUploadedFile("corrupt_logo.png", b"NOT_A_REAL_PNG_HEADER_JUST_TEXT_NOISE", content_type="image/png")
    res_corrupt = c.post("/api/restaurant/profile/", data={
        "name": "Alpha Corrupt Header Test",
        "logo_image": corrupt_file
    })
    # Since Pillow is omitted by design, system validates extension and size.
    # Verify no unhandled exception or server crash
    if res_corrupt.status_code in [200, 400]:
        tracker.record_pass("MEDIA_UPLOADS", test_id, f"Corrupt image header handled safely without crash ({res_corrupt.status_code})")
    else:
        tracker.record_fail("MEDIA_UPLOADS", test_id, "Corrupt image header caused server error", f"Status: {res_corrupt.status_code}")

    # 4.3: Fake MIME Types (Executable MIME with .png extension, and PHP with .png)
    test_id = "ADV-MEDIA-FAKE-MIME-EXE"
    fake_exe = SimpleUploadedFile("payload.png", b"\x7fELF\x02\x01\x01\x00", content_type="application/x-executable")
    res_fake_exe = c.post("/api/restaurant/profile/", data={"name": "Alpha Fake Mime", "logo_image": fake_exe})
    if res_fake_exe.status_code in [200, 400]:
        tracker.record_pass("MEDIA_UPLOADS", test_id, f"Fake MIME executable with .png extension processed without server compromise ({res_fake_exe.status_code})")
    else:
        tracker.record_fail("MEDIA_UPLOADS", test_id, "Fake MIME caused server crash", f"Status: {res_fake_exe.status_code}")

    # Fake MIME type in reverse: PHP file with image/png content type
    test_id = "ADV-MEDIA-REVERSE-MIME-PHP"
    php_file = SimpleUploadedFile("backdoor.php", b"<?php phpinfo(); ?>", content_type="image/png")
    res_php = c.post("/api/restaurant/profile/", data={"name": "Alpha Reverse Mime", "logo_image": php_file})
    # Extension .php MUST be rejected (400)
    if res_php.status_code == 400:
        tracker.record_pass("MEDIA_UPLOADS", test_id, "Disallowed extension .php with fake image MIME strictly rejected (400)")
    else:
        tracker.record_fail("MEDIA_UPLOADS", test_id, "Disallowed extension .php with image MIME was accepted!", f"Status: {res_php.status_code}")

    # 4.4: Dotfile Extensions & Abnormal Filenames
    filename_probes = [
        ("ADV-MEDIA-DOT-ONLY", ".", b"test", 400, "Single dot '.' rejected"),
        ("ADV-MEDIA-DOTS-TWO", "..", b"test", 400, "Double dot '..' rejected"),
        ("ADV-MEDIA-DOT-TRAILING", "image.", b"test", 400, "Trailing dot 'image.' rejected"),
        ("ADV-MEDIA-DOUBLE-EXT", "image.png.exe", b"test", 400, "Double extension '.png.exe' rejected"),
        ("ADV-MEDIA-EXE-PNG", "image.exe.png", VALID_PNG, 200, "'.exe.png' accepted as png file"),
        ("ADV-MEDIA-UPPERCASE", "image.PNG", VALID_PNG, 200, "Uppercase extension '.PNG' accepted"),
        ("ADV-MEDIA-MIXEDCASE", "image.JpEg", VALID_JPG, 200, "Mixed-case extension '.JpEg' accepted"),
        ("ADV-MEDIA-NO-EXT", "noextensionfile", b"test", 400, "File without extension rejected"),
    ]

    from django.core.exceptions import SuspiciousFileOperation

    for test_id, fname, content, exp_status, desc in filename_probes:
        try:
            up_file = SimpleUploadedFile(fname, content, content_type="image/png")
            res = c.post("/api/restaurant/profile/", data={"name": "Alpha Dotfile Test", "logo_image": up_file})
            status = res.status_code
        except SuspiciousFileOperation:
            # Django core explicitly blocks suspicious filename as bad request
            status = 400

        if status == exp_status:
            tracker.record_pass("MEDIA_UPLOADS", test_id, desc)
        else:
            tracker.record_fail("MEDIA_UPLOADS", test_id, f"Abnormal filename probe '{fname}' failed", f"Expected {exp_status}, got {status}")

    # 4.5: Path Traversal in Filename
    test_id = "ADV-MEDIA-PATH-TRAVERSAL"
    traversal_file = SimpleUploadedFile("../../../../media/evil.png", VALID_PNG, content_type="image/png")
    res_trav = c.post("/api/restaurant/profile/", data={"name": "Alpha Traversal Test", "logo_image": traversal_file})
    # Ensure Django storage sanitized path (saved inside tenant_logos/ without escaping root)
    t_trav = Tenant.objects.get(id=f["t_alpha"].id)
    if t_trav.logo_image:
        saved_name = t_trav.logo_image.name
        if ".." not in saved_name and saved_name.startswith("tenant_logos/"):
            tracker.record_pass("MEDIA_UPLOADS", test_id, f"Path traversal in filename sanitized to '{saved_name}'")
        else:
            tracker.record_fail("MEDIA_UPLOADS", test_id, f"Path traversal escaped tenant_logos directory!", f"Saved name: {saved_name}")
    else:
        tracker.record_pass("MEDIA_UPLOADS", test_id, "Path traversal rejected or neutralized")

    # 4.6: Oversized File Upload Boundary
    test_id = "ADV-MEDIA-OVERSIZE-LOGO-EXACT"
    logo_oversized = SimpleUploadedFile("big_logo.png", b"x" * (2 * 1024 * 1024 + 1), content_type="image/png")
    res_big_logo = c.post("/api/restaurant/profile/", data={"name": "Alpha Oversize", "logo_image": logo_oversized})
    if res_big_logo.status_code == 400:
        tracker.record_pass("MEDIA_UPLOADS", test_id, "Logo exactly 2MB + 1 byte rejected (400)")
    else:
        tracker.record_fail("MEDIA_UPLOADS", test_id, "Logo 2MB + 1 byte was not rejected", f"Status: {res_big_logo.status_code}")

    test_id = "ADV-MEDIA-OVERSIZE-COVER-EXACT"
    cover_oversized = SimpleUploadedFile("big_cover.jpg", b"x" * (5 * 1024 * 1024 + 1), content_type="image/jpeg")
    res_big_cover = c.post("/api/restaurant/profile/", data={"name": "Alpha Oversize", "cover_image": cover_oversized})
    if res_big_cover.status_code == 400:
        tracker.record_pass("MEDIA_UPLOADS", test_id, "Cover exactly 5MB + 1 byte rejected (400)")
    else:
        tracker.record_fail("MEDIA_UPLOADS", test_id, "Cover 5MB + 1 byte was not rejected", f"Status: {res_big_cover.status_code}")


def main():
    print(f"\n{CYAN}{BOLD}Starting Adversarial Stress & Vulnerability Probes...{RESET}")
    tracker = AdversarialTestTracker()

    try:
        cleanup_adversarial_fixtures()
        fixtures = create_adversarial_fixtures()

        run_rbac_bypass_probes(tracker, fixtures)
        run_cross_tenant_probes(tracker, fixtures)
        run_injection_probes(tracker, fixtures)
        run_media_upload_probes(tracker, fixtures)

    finally:
        print(f"\n{YELLOW}Cleaning up adversarial test fixtures...{RESET}")
        cleanup_adversarial_fixtures()

    success = tracker.summary()
    if not success:
        print(f"\n{RED}{BOLD}Adversarial probes revealed {len(tracker.findings)} failure(s) / vulnerability(ies)!{RESET}")
        sys.exit(1)
    else:
        print(f"\n{GREEN}{BOLD}All adversarial probes PASSED with 100% robustness! System withstands all tested attack vectors.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
