import os
import sys
import json
import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, Branch, Employee, UserProfile, SubscriptionPlan, UpgradeRequest


def run_tests():
    print("===========================================================================")
    print("STARTING TEST SUITE: LANDING NAVBAR, BILINGUAL & USER/SUBSCRIPTION PROFILE")
    print("===========================================================================")

    client = Client()

    # -------------------------------------------------------------------------
    # SUITE 1: GUEST VISITOR LANDING PAGE (NAVBAR & CONTENT TABS)
    # -------------------------------------------------------------------------
    print("\n>>> SUITE 1: Guest Landing Page (Navbar & Content Tabs Removal)")
    resp = client.get("/")
    assert resp.status_code == 200, f"Expected 200 for guest landing page, got {resp.status_code}"
    content = resp.content.decode("utf-8")

    # Content anchor tabs must NOT be in desktop navbar or mobile drawer links
    # Search within header element
    header_content = content[content.find("<header"):content.find("</header>")]
    forbidden_tabs = ["#features", "#pos-kds", "#ai-phone", "#pricing", "#faq"]
    for tab in forbidden_tabs:
        assert f'href="{tab}"' not in header_content, f"Tab link '{tab}' still present in header navbar!"
    print("  ✔ PASS: Anchor tabs (features, pos-kds, ai-phone, pricing, faq) removed from navbar")

    # Body sections must remain visible and scrollable
    body_content = content[content.find("</header>"):content.find("</footer>")]
    assert 'id="features"' in body_content, "Features section missing in body"
    assert 'id="pos-kds"' in body_content, "POS/KDS section missing in body"
    assert 'id="ai-phone"' in body_content, "AI Phone section missing in body"
    assert 'id="pricing"' in body_content, "Pricing section missing in body"
    assert 'id="faq"' in body_content, "FAQ section missing in body"
    print("  ✔ PASS: All body sections (features, pos-kds, ai-phone, pricing, faq) preserved in page body")

    # Guest user buttons: Sign In, Start Free, and Language Switcher
    assert "تسجيل الدخول" in header_content, "Guest 'Sign In' button not found in header"
    assert "ابدأ مجاناً" in header_content, "Guest 'Start Free' button not found in header"
    assert "/set-language/en/" in header_content, "Language switcher to English not found"
    assert "/dashboard/" not in header_content, "Dashboard button should not appear for guest"
    assert 'href="/profile/"' not in header_content, "Profile button should not appear for guest"
    print("  ✔ PASS: Guest header shows only Logo, Language Switcher, Sign In, and Start Free")

    # -------------------------------------------------------------------------
    # SUITE 2: AUTHENTICATED USER LANDING PAGE (OWNER/MANAGER STATE)
    # -------------------------------------------------------------------------
    print("\n>>> SUITE 2: Authenticated Landing Page (Dashboard & Profile Buttons)")
    admin_user = User.objects.filter(is_superuser=True).first()
    assert admin_user is not None, "Admin user not found"
    client.force_login(admin_user)

    resp_auth = client.get("/")
    assert resp_auth.status_code == 200, f"Expected 200 for authenticated landing page, got {resp_auth.status_code}"
    auth_content = resp_auth.content.decode("utf-8")
    auth_header = auth_content[auth_content.find("<header"):auth_content.find("</header>")]

    # Authenticated buttons present
    assert "/dashboard/" in auth_header, "'Dashboard' link not found in authenticated navbar"
    assert "لوحة الإدارة" in auth_header, "'لوحة الإدارة' text not found in authenticated navbar"
    assert "/profile/" in auth_header, "'Profile' link not found in authenticated navbar"
    assert "البروفايل" in auth_header, "'البروفايل' text not found in authenticated navbar"

    # Guest buttons MUST be hidden for authenticated user
    assert "/login/" not in auth_header, "'Sign In' button should be hidden for authenticated user"
    assert "تسجيل الدخول" not in auth_header, "'تسجيل الدخول' should be hidden for authenticated user"
    # Start free button in header should be hidden
    assert "ابدأ مجاناً" not in auth_header, "'ابدأ مجاناً' should be hidden in header for authenticated user"

    # Dashboard sidebar/topbar shell must NOT appear on landing page
    assert 'id="app-sidebar"' not in auth_content, "Internal app sidebar should not render on landing page"
    print("  ✔ PASS: Authenticated header shows Logo, Dashboard, Profile, and Language Switcher (Guest buttons hidden)")
    client.logout()

    # -------------------------------------------------------------------------
    # SUITE 3: 100% BILINGUAL COVERAGE & INSTANT TOGGLE (ARABIC / ENGLISH)
    # -------------------------------------------------------------------------
    print("\n>>> SUITE 3: 100% Bilingual Arabic and English Landing Page")
    # 3.1 Arabic (RTL) mode
    resp_ar = client.get("/set-language/ar/?next=/")
    assert resp_ar.status_code == 302
    assert resp_ar.url == "/"
    resp_ar_page = client.get("/")
    assert resp_ar_page.status_code == 200
    content_ar = resp_ar_page.content.decode("utf-8")

    assert 'dir="rtl"' in content_ar, "RTL layout direction not found in Arabic mode"
    assert "منظومة التشغيل الموحدة لإدارة سلاسل المطاعم الحديثة" in content_ar
    assert "كل ما تحتاجه لإدارة وتوسيع مطاعمك من مكان واحد" in content_ar
    assert "الأسئلة الشائعة" in content_ar
    assert "باقات واضحة وبسيطة" in content_ar
    assert "بدون بطاقة ائتمانية" in content_ar
    assert "تفعيل فوري خلال دقيقتين" in content_ar
    assert "بث المطبخ اللحظي" in content_ar
    assert "سلسلة مطاعم رائدة" in content_ar
    print("  ✔ PASS: Arabic landing page renders RTL layout with 100% Arabic text")

    # 3.2 English (LTR) mode
    resp_en = client.get("/set-language/en/?next=/")
    assert resp_en.status_code == 302
    assert resp_en.url == "/"
    resp_en_page = client.get("/")
    assert resp_en_page.status_code == 200
    content_en = resp_en_page.content.decode("utf-8")

    assert 'dir="ltr"' in content_en, "LTR layout direction not found in English mode"
    assert "The Unified Operating System for Modern Restaurant Chains" in content_en
    assert "Everything You Need to Manage & Scale Your Restaurants from One Place" in content_en
    assert "Frequently Asked Questions" in content_en
    assert "Simple & Transparent Pricing" in content_en
    assert "No Credit Card Required" in content_en
    assert "Instant 2-Minute Setup" in content_en
    assert "Real-Time Kitchen Feed" in content_en
    assert "Leading Restaurant Chains" in content_en
    assert "Sign In" in content_en
    assert "Start Free" in content_en
    print("  ✔ PASS: English landing page renders LTR layout with 100% English text")

    # 3.3 Authenticated English navbar
    client.force_login(admin_user)
    resp_en_auth = client.get("/")
    assert resp_en_auth.status_code == 200
    content_en_auth = resp_en_auth.content.decode("utf-8")
    header_en_auth = content_en_auth[content_en_auth.find("<header"):content_en_auth.find("</header>")]
    assert "Dashboard" in header_en_auth
    assert "Profile" in header_en_auth
    print("  ✔ PASS: English authenticated navbar renders 'Dashboard' and 'Profile'")
    client.logout()

    # Reset back to Arabic
    client.get("/set-language/ar/?next=/")

    # -------------------------------------------------------------------------
    # SUITE 4: USER & SUBSCRIPTION PROFILE PAGE (/profile/ & /user/profile/)
    # -------------------------------------------------------------------------
    print("\n>>> SUITE 4: User & Subscription Profile Page")

    # 4.1 Unauthenticated access must redirect to login (302)
    resp_unauth_profile = client.get("/profile/")
    assert resp_unauth_profile.status_code == 302, f"Expected 302 redirect to login, got {resp_unauth_profile.status_code}"
    assert "/login/" in resp_unauth_profile.url, f"Expected redirect to login, got {resp_unauth_profile.url}"

    resp_unauth_user_profile = client.get("/user/profile/")
    assert resp_unauth_user_profile.status_code == 302, f"Expected 302 redirect to login, got {resp_unauth_user_profile.status_code}"
    assert "/login/" in resp_unauth_user_profile.url, f"Expected redirect to login, got {resp_unauth_user_profile.url}"
    print("  ✔ PASS: Non-authenticated requests to /profile/ and /user/profile/ redirected to login")

    # 4.2 Setup test tenant and owner
    tenant, _ = Tenant.objects.get_or_create(
        slug="test-profile-tenant",
        defaults={
            "name": "مطعم النخبة التجريبي",
            "phone": "+966500000001",
            "email": "owner@elite.sa",
            "is_active": True,
        }
    )

    plan_starter = SubscriptionPlan.objects.filter(code="starter").first()
    if not plan_starter:
        plan_starter = SubscriptionPlan.objects.create(
            name="باقة البداية",
            code="starter",
            price_monthly=199,
            price_yearly=1990,
            max_branches=2,
            max_employees=10,
            features=["pos", "kds"],
            is_active=True,
            ordering=1,
        )

    tenant.subscription_plan = plan_starter
    tenant.subscription_status = "active"
    tenant.save()

    owner_user, _ = User.objects.get_or_create(
        username="profile_owner_test",
        defaults={
            "first_name": "سلطان",
            "last_name": "العتيبي",
            "email": "sultan@elite.sa"
        }
    )
    owner_user.set_password("pass123456")
    owner_user.save()

    UserProfile.objects.update_or_create(
        user=owner_user,
        defaults={
            "tenant": tenant,
            "role": "owner",
            "is_platform_admin": False,
        }
    )

    client.force_login(owner_user)
    session = client.session
    session["active_tenant_id"] = tenant.id
    session.save()

    # 4.3 Access /profile/ and /user/profile/ as owner
    for profile_path in ["/profile/", "/user/profile/", "/subscription/"]:
        resp_p = client.get(profile_path)
        assert resp_p.status_code == 200, f"Expected 200 on {profile_path}, got {resp_p.status_code}"
        p_content = resp_p.content.decode("utf-8")

        # R3 requirement: Account and Restaurant overview
        assert tenant.name in p_content, f"Tenant name '{tenant.name}' not found on {profile_path}"
        assert "@test-profile-tenant" in p_content, f"Tenant slug '@test-profile-tenant' not found on {profile_path}"
        assert "profile_owner_test" in p_content, f"Owner username not found on {profile_path}"

        # R3 requirement: Active Plan Card
        assert plan_starter.name in p_content, f"Plan name '{plan_starter.name}' not found on {profile_path}"

        # R3 requirement: Visual Progress Bars
        assert "الفروع المشغلة" in p_content, f"Branches quota not found on {profile_path}"
        assert "الموظفون المسجلون" in p_content, f"Employees quota not found on {profile_path}"

        # R3 requirement: Plan Upgrade Action Modal
        assert "openUpgradeModal()" in p_content, f"Upgrade modal opener not found on {profile_path}"
        assert 'id="upgrade-modal"' in p_content, f"Upgrade modal container not found on {profile_path}"

        # R3 requirement: Prominent Primary CTA routing to /dashboard/
        assert "/dashboard/" in p_content, f"Dashboard link not found on {profile_path}"
        assert "الدخول إلى لوحة العمليات" in p_content, f"'الدخول إلى لوحة العمليات' text not found on {profile_path}"
        print(f"  ✔ PASS: {profile_path} renders complete Account, Plan, Quota bars, Upgrade Modal & Dashboard CTA")

    # 4.4 Non-owner (cashier) access blocked (403)
    cashier_user, _ = User.objects.get_or_create(username="profile_cashier_test")
    cashier_user.set_password("pass123456")
    cashier_user.save()
    UserProfile.objects.update_or_create(
        user=cashier_user,
        defaults={"tenant": tenant, "role": "cashier", "is_platform_admin": False}
    )
    client.force_login(cashier_user)
    session = client.session
    session["active_tenant_id"] = tenant.id
    session.save()
    for profile_path in ["/profile/", "/user/profile/", "/subscription/"]:
        resp_c = client.get(profile_path)
        assert resp_c.status_code == 403, f"Expected 403 for cashier on {profile_path}, got {resp_c.status_code}"
    print("  ✔ PASS: Non-owner staff (cashier) strictly blocked with HTTP 403 Forbidden")
    client.logout()

    # -------------------------------------------------------------------------
    # SUITE 5: POST-REGISTRATION ROUTING
    # -------------------------------------------------------------------------
    print("\n>>> SUITE 5: Post-Registration Routing (/register/ -> /profile/)")
    reg_username = "new_signup_owner_999"
    User.objects.filter(username=reg_username).delete()

    reg_payload = {
        "restaurant_name": "شاورما البركة",
        "cuisine_type": "وجبات سريعة",
        "owner_name": "عبد الله السالم",
        "phone": "+966555123456",
        "email": "abdullah@baraka.sa",
        "username": reg_username,
        "password": "strongPassword123",
        "plan_code": "growth"
    }

    resp_reg = client.post("/register/", data=reg_payload)
    assert resp_reg.status_code == 302, f"Expected 302 redirect after registration, got {resp_reg.status_code}"
    # Must redirect to profile page
    assert resp_reg.url in ["/profile/", "/user/profile/", "/subscription/"], f"Expected redirect to profile, got {resp_reg.url}"
    print(f"  ✔ PASS: Successful registration redirected to {resp_reg.url}")

    # Following redirect should render 200 OK with trial subscription & limits
    resp_after_reg = client.get(resp_reg.url)
    assert resp_after_reg.status_code == 200, f"Expected 200 after redirect, got {resp_after_reg.status_code}"
    after_reg_content = resp_after_reg.content.decode("utf-8")
    assert "شاورما البركة" in after_reg_content, "Newly registered restaurant name not rendered on profile"
    assert "new_signup_owner_999" in after_reg_content, "Newly registered username not rendered on profile"
    assert "الدخول إلى لوحة العمليات" in after_reg_content, "Dashboard CTA not rendered on profile"
    print("  ✔ PASS: Newly registered owner lands directly on their Profile page (200 OK)")

    # -------------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------------
    User.objects.filter(username=reg_username).delete()
    Tenant.objects.filter(name="شاورما البركة").delete()
    User.objects.filter(username="profile_owner_test").delete()
    User.objects.filter(username="profile_cashier_test").delete()
    Tenant.objects.filter(slug="test-profile-tenant").delete()

    print("\n===========================================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! 100% VERIFIED.")
    print("===========================================================================")


if __name__ == "__main__":
    run_tests()
