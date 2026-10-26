import os
import sys
import django

# Setup Django Environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from apps.billing.models import SubscriptionPlan, AVAILABLE_FEATURES
from apps.billing.admin import (
    SubscriptionPlanAdminForm,
    SubscriptionPlanAdmin,
    FeatureCardsCheckboxSelectMultiple,
    LEGACY_FEATURE_MAP,
)

GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def assert_true(cond, msg):
    if cond:
        print(f"  {GREEN}✔ PASS:{RESET} {msg}")
    else:
        print(f"  {RED}✘ FAIL:{RESET} {msg}")
        raise AssertionError(f"Failed: {msg}")


def test_feature_catalog():
    print(f"\n{BOLD}>>> 1. Testing Feature Catalog Integrity{RESET}")
    expected_keys = [
        "pos",
        "kds",
        "menu_management",
        "delivery_management",
        "call_center",
        "inventory",
        "custom_roles",
        "financial_analytics",
    ]
    catalog_keys = [f["key"] for f in AVAILABLE_FEATURES]
    assert_true(catalog_keys == expected_keys, f"Catalog keys match approved list ({catalog_keys})")

    # Check labels and descs
    feat_map = {f["key"]: f for f in AVAILABLE_FEATURES}
    assert_true("نقاط البيع والكاشير (POS)" in feat_map["pos"]["label"], "POS label matches")
    assert_true("الكول سنتر ومساعد الذكاء الاصطناعي (AI Voice)" in feat_map["call_center"]["label"], "Call Center + AI Voice merged label matches")
    assert_true(len(AVAILABLE_FEATURES) == 8, "Exactly 8 approved features")


def test_form_initial_and_normalization():
    print(f"\n{BOLD}>>> 2. Testing Form Normalization of Canonical, Legacy, and Dict Keys{RESET}")

    # Case A: New plan (no instance)
    form_new = SubscriptionPlanAdminForm()
    assert_true(form_new.initial.get("features", []) == [], "New plan starts with empty features initial")

    # Case B: Plan with canonical keys
    dummy_plan = SubscriptionPlan(name="Dummy", code="dummy", features=["pos", "kds", "call_center"])
    dummy_plan.pk = 99999
    form_canonical = SubscriptionPlanAdminForm(instance=dummy_plan)
    assert_true(set(form_canonical.initial["features"]) == {"pos", "kds", "call_center"}, "Canonical keys preserved in initial")

    # Case C: Plan with legacy keys
    legacy_plan = SubscriptionPlan(
        name="Legacy",
        code="legacy",
        features=["pos_billing", "kds_kitchen", "inventory_mgmt", "delivery_zones", "manage_roles", "basic_reports", "ai_call_center"]
    )
    legacy_plan.pk = 99998
    form_legacy = SubscriptionPlanAdminForm(instance=legacy_plan)
    expected_normalized = {"pos", "kds", "inventory", "delivery_management", "custom_roles", "financial_analytics", "call_center"}
    assert_true(set(form_legacy.initial["features"]) == expected_normalized, f"Legacy keys properly normalized to canonical keys: {form_legacy.initial['features']}")

    # Case D: Plan with dictionary features (truthy and falsy values)
    dict_plan = SubscriptionPlan(
        name="DictPlan",
        code="dict_plan",
        features={"pos": True, "kds": False, "call_center": 1, "inventory": 0}
    )
    dict_plan.pk = 99997
    form_dict = SubscriptionPlanAdminForm(instance=dict_plan)
    assert_true(set(form_dict.initial["features"]) == {"pos", "call_center"}, f"Dict features filtered by truthy values: {form_dict.initial['features']}")

    # Case E: Plan with JSON string dictionary
    json_dict_plan = SubscriptionPlan(
        name="JsonDictPlan",
        code="json_dict_plan",
        features='{"pos": true, "inventory": false}'
    )
    json_dict_plan.pk = 99996
    form_json_dict = SubscriptionPlanAdminForm(instance=json_dict_plan)
    assert_true(form_json_dict.initial["features"] == ["pos"], f"JSON string dict features loaded: {form_json_dict.initial['features']}")

    # Case F: Defensive against non-iterable features (e.g. integer or boolean or None)
    int_plan = SubscriptionPlan(name="IntPlan", code="int_plan", features=42)
    int_plan.pk = 99995
    form_int = SubscriptionPlanAdminForm(instance=int_plan)
    assert_true(form_int.initial["features"] == [], "Non-iterable integer features handled safely without crash")

    none_plan = SubscriptionPlan(name="NonePlan", code="none_plan", features=None)
    none_plan.pk = 99994
    form_none = SubscriptionPlanAdminForm(instance=none_plan)
    assert_true(form_none.initial["features"] == [], "None features handled safely")


def test_form_validation_and_cleaning():
    print(f"\n{BOLD}>>> 3. Testing Form Validation & clean_features{RESET}")

    plan = SubscriptionPlan.objects.first()
    data = {
        "name": plan.name,
        "code": plan.code,
        "price_monthly": plan.price_monthly,
        "price_yearly": plan.price_yearly,
        "max_branches": plan.max_branches,
        "max_employees": plan.max_employees,
        "trial_days": plan.trial_days,
        "ordering": plan.ordering,
        "features": ["pos", "kds", "delivery_management", "inventory"],
    }
    form = SubscriptionPlanAdminForm(data=data, instance=plan)
    assert_true(form.is_valid(), f"Form is valid with selected features. Errors: {form.errors}")
    assert_true(form.cleaned_data["features"] == ["pos", "kds", "delivery_management", "inventory"], "Cleaned data is python list")

    # Test empty features
    data_empty = dict(data)
    data_empty["features"] = []
    form_empty = SubscriptionPlanAdminForm(data=data_empty, instance=plan)
    assert_true(form_empty.is_valid(), f"Form is valid with empty features. Errors: {form_empty.errors}")
    assert_true(form_empty.cleaned_data["features"] == [], "Cleaned empty features is empty list")


def test_widget_resilience():
    print(f"\n{BOLD}>>> 4. Testing Widget Resilience against Edge Cases{RESET}")
    widget = FeatureCardsCheckboxSelectMultiple()

    # Case A: Dictionary value (should not raise TypeError: unhashable type: 'dict')
    ctx_dict = widget.get_context("features", {"pos": True, "kds": False}, {})
    checked_keys = [c["key"] for c in ctx_dict["feature_cards"] if c["checked"]]
    assert_true(checked_keys == ["pos"], f"Widget handles dict value safely: {checked_keys}")

    # Case B: JSON string dictionary
    ctx_str = widget.get_context("features", '{"pos": true, "inventory": false}', {})
    checked_str_keys = [c["key"] for c in ctx_str["feature_cards"] if c["checked"]]
    assert_true(checked_str_keys == ["pos"], f"Widget handles JSON string dict safely: {checked_str_keys}")

    # Case C: Non-iterable value (int, None)
    ctx_int = widget.get_context("features", 42, {})
    assert_true(isinstance(ctx_int["feature_cards"], list), "Widget handles integer without crash")

    ctx_none = widget.get_context("features", None, {})
    assert_true(ctx_none["selected_count"] == 0, "Widget handles None value with 0 selected")


def test_features_count_display():
    print(f"\n{BOLD}>>> 5. Testing features_count_display Formatting & Pluralization{RESET}")
    model_admin = SubscriptionPlanAdmin(SubscriptionPlan, None)

    # 0 features
    p0 = SubscriptionPlan(features=[])
    d0 = model_admin.features_count_display(p0)
    assert_true("لا توجد ميزات" in d0 and "badge-secondary" in d0, "0 features displays 'لا توجد ميزات' with badge-secondary")

    # 1 feature
    p1 = SubscriptionPlan(features=["pos"])
    d1 = model_admin.features_count_display(p1)
    assert_true("ميزة واحدة" in d1, "1 feature displays 'ميزة واحدة'")

    # 2 features
    p2 = SubscriptionPlan(features=["pos", "kds"])
    d2 = model_admin.features_count_display(p2)
    assert_true("ميزتان" in d2, "2 features displays 'ميزتان'")

    # 3-10 features
    p5 = SubscriptionPlan(features=["pos", "kds", "call_center", "inventory", "custom_roles"])
    d5 = model_admin.features_count_display(p5)
    assert_true("5 ميزات" in d5, "5 features displays '5 ميزات'")

    # Non-list value (defensive check)
    p_int = SubscriptionPlan(features=42)
    d_int = model_admin.features_count_display(p_int)
    assert_true("لا توجد ميزات" in d_int, "Integer features displays 0 safely")


def test_admin_views_and_crud():
    print(f"\n{BOLD}>>> 6. Testing Live Django Admin GET & POST Requests{RESET}")

    client = Client()
    admin_user = User.objects.filter(is_superuser=True).first()
    assert_true(admin_user is not None, "Superuser exists")
    client.force_login(admin_user)

    # 1. Admin changelist
    res = client.get("/admin/core/subscriptionplan/")
    assert_true(res.status_code == 200, "Changelist /admin/core/subscriptionplan/ loads (200 OK)")
    content = res.content.decode("utf-8")
    assert_true("الميزات المضمنة" in content, "features_count_display column appears in changelist")

    # 2. Admin add view
    res_add = client.get("/admin/core/subscriptionplan/add/")
    assert_true(res_add.status_code == 200, "Add view /admin/core/subscriptionplan/add/ loads (200 OK)")
    add_content = res_add.content.decode("utf-8")
    assert_true("fcw-card" in add_content, "Feature card grid rendered on add page")
    assert_true("تحديد الكل" in add_content, "Select All button rendered on add page")
    assert_true("إلغاء التحديد" in add_content, "Deselect All button rendered on add page")

    # 3. Admin change view
    res_change = client.get("/admin/core/subscriptionplan/1/change/")
    assert_true(res_change.status_code == 200, "Change view loads (200 OK)")
    change_content = res_change.content.decode("utf-8")
    assert_true("fcw-card" in change_content, "Feature cards rendered on change page")
    assert_true("الميزات المفعلة:" in change_content, "Selected counter header rendered")

    # 4. Create new plan via admin POST
    test_code = "e2e-card-plan"
    SubscriptionPlan.objects.filter(code=test_code).delete()

    create_payload = {
        "name": "باقة الكروت التجريبية",
        "code": test_code,
        "description": "تجربة حفظ المربعات الاختيارية",
        "price_monthly": "120.00",
        "price_yearly": "1200.00",
        "max_branches": 3,
        "max_employees": 15,
        "trial_days": 14,
        "ordering": 50,
        "is_active": "on",
        "features": ["pos", "call_center", "inventory"],
    }
    post_res = client.post("/admin/core/subscriptionplan/add/", create_payload, follow=True)
    assert_true(post_res.status_code == 200, "Plan created via Admin POST and redirected (200 OK)")

    created_plan = SubscriptionPlan.objects.filter(code=test_code).first()
    assert_true(created_plan is not None, "Plan successfully written to database")
    assert_true(created_plan.features == ["pos", "call_center", "inventory"], f"Features saved properly as JSON list: {created_plan.features}")

    # 5. Update plan features via admin POST
    update_payload = {
        "name": created_plan.name,
        "code": created_plan.code,
        "price_monthly": created_plan.price_monthly,
        "price_yearly": created_plan.price_yearly,
        "max_branches": created_plan.max_branches,
        "max_employees": created_plan.max_employees,
        "trial_days": created_plan.trial_days,
        "ordering": created_plan.ordering,
        "is_active": "on",
        "features": ["pos", "kds", "menu_management", "delivery_management", "call_center", "financial_analytics"],
    }
    edit_res = client.post(f"/admin/core/subscriptionplan/{created_plan.id}/change/", update_payload, follow=True)
    assert_true(edit_res.status_code == 200, "Plan updated via Admin POST and redirected (200 OK)")

    created_plan.refresh_from_db()
    expected_updated = ["pos", "kds", "menu_management", "delivery_management", "call_center", "financial_analytics"]
    assert_true(created_plan.features == expected_updated, f"Features updated properly in database: {created_plan.features}")

    # 6. Uncheck all features
    empty_payload = {
        "name": created_plan.name,
        "code": created_plan.code,
        "price_monthly": created_plan.price_monthly,
        "price_yearly": created_plan.price_yearly,
        "max_branches": created_plan.max_branches,
        "max_employees": created_plan.max_employees,
        "trial_days": created_plan.trial_days,
        "ordering": created_plan.ordering,
        "is_active": "on",
    }
    empty_res = client.post(f"/admin/core/subscriptionplan/{created_plan.id}/change/", empty_payload, follow=True)
    assert_true(empty_res.status_code == 200, "Plan with no features selected saved and redirected (200 OK)")

    created_plan.refresh_from_db()
    assert_true(created_plan.features == [], f"Features emptied properly: {created_plan.features}")

    # Clean up
    created_plan.delete()
    assert_true(not SubscriptionPlan.objects.filter(code=test_code).exists(), "Cleaned up test plan from database")


if __name__ == "__main__":
    print(f"\n{BOLD}========================================================================{RESET}")
    print(f"{BOLD}STARTING E2E VERIFICATION: SUBSCRIPTION PLAN FEATURES GRID CHECKBOXES{RESET}")
    print(f"{BOLD}========================================================================{RESET}")
    test_feature_catalog()
    test_form_initial_and_normalization()
    test_form_validation_and_cleaning()
    test_widget_resilience()
    test_features_count_display()
    test_admin_views_and_crud()
    print(f"\n{GREEN}{BOLD}========================================================================{RESET}")
    print(f"{GREEN}{BOLD}ALL TESTS PASSED SUCCESSFULLY! 100% VERIFIED.{RESET}")
    print(f"{GREEN}{BOLD}========================================================================{RESET}\n")
