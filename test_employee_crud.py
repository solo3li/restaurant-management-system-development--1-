import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant_system.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, Employee, JobRole, Branch, UserProfile

def run_tests():
    print("=== STARTING FULL EMPLOYEE CRUD E2E TEST ===")
    
    # 1. Setup Tenant and Superuser/Owner Client
    tenant = Tenant.objects.first()
    assert tenant is not None, "Tenant not found"
    print(f"Tenant: {tenant.name} (slug: {tenant.slug})")
    
    owner_user = User.objects.filter(is_superuser=True).first()
    if not owner_user:
        owner_user = User.objects.filter(profile__tenant=tenant, profile__role="owner").first()
    assert owner_user is not None, "Owner / superuser not found"
    print(f"Testing as user: {owner_user.username}")
    
    client = Client(HTTP_HOST="uggu.space")
    client.force_login(owner_user)
    session = client.session
    session["active_tenant_id"] = tenant.id
    session.save()
    
    # 2. Test GET /employees/
    print("\n--- 1. Testing GET /employees/ page render ---")
    res = client.get('/employees/')
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    content = res.content.decode('utf-8')
    assert 'view-emp-modal' in content, "view-emp-modal missing from HTML"
    assert 'delete-emp-modal' in content, "delete-emp-modal missing from HTML"
    assert '/api/employees/export-csv/' in content, "CSV export link missing from HTML"
    assert 'edit-emp-password' in content, "edit-emp-password field missing from HTML"
    print("✓ GET /employees/ successfully rendered with all CRUD modals and export actions.")

    # 3. Test POST /api/employees/create/
    print("\n--- 2. Testing Employee Creation (CREATE) ---")
    job_role = JobRole.objects.filter(tenant=tenant).first()
    test_code = "9988"
    # Ensure clean slate for test_code
    Employee.objects.filter(tenant=tenant, employee_code=test_code).delete()
    User.objects.filter(username=f"emp_{tenant.slug}_{test_code}").delete()
    
    create_payload = {
        "name": "موظف اختبار تجريبي",
        "phone": "0555555555",
        "job_role_id": job_role.id if job_role else None,
        "salary": 6500,
        "employee_code": test_code,
        "pin_code": "4321"
    }
    res = client.post(
        '/api/employees/create/', 
        data=json.dumps(create_payload), 
        content_type='application/json'
    )
    assert res.status_code == 200, f"Create failed: {res.content}"
    data = res.json()
    emp_id = data.get("id")
    assert emp_id, "Employee ID not returned"
    print(f"✓ Employee created with ID: {emp_id}, code: {test_code}")

    # 4. Test GET /api/employees/<id>/detail/ (READ)
    print("\n--- 3. Testing Employee Detail (READ) ---")
    res = client.get(f'/api/employees/{emp_id}/detail/')
    assert res.status_code == 200, f"Detail failed: {res.content}"
    detail_data = res.json()
    assert detail_data.get("ok") is True
    emp_obj = detail_data["employee"]
    assert emp_obj["name"] == "موظف اختبار تجريبي"
    assert emp_obj["employee_code"] == test_code
    assert emp_obj["has_pin"] is True
    print(f"✓ Employee detail retrieved successfully. Permissions count: {len(emp_obj.get('permissions', []))}")

    # 5. Test POST /api/employees/update/<id>/ (UPDATE)
    print("\n--- 4. Testing Employee Update (UPDATE) ---")
    update_payload = {
        "name": "موظف اختبار معدل",
        "phone": "0544444444",
        "job_role_id": job_role.id if job_role else None,
        "salary": 7200,
        "employee_code": test_code,
        "pin_code": "9876",
        "password": "newSecurePassword123"
    }
    res = client.post(
        f'/api/employees/update/{emp_id}/',
        data=json.dumps(update_payload),
        content_type='application/json'
    )
    assert res.status_code == 200, f"Update failed: {res.content}"
    updated_emp = Employee.objects.get(id=emp_id)
    assert updated_emp.name == "موظف اختبار معدل"
    assert updated_emp.salary == 7200
    assert updated_emp.check_pin("9876") is True
    assert updated_emp.user.check_password("newSecurePassword123") is True
    print("✓ Employee updated successfully (name, salary, PIN, and dashboard password).")

    # 5.1 Test Update with OMITTED pin and password (Must preserve existing values)
    print("\n--- 4.1 Testing Update without PIN or Password (Preservation) ---")
    partial_payload = {
        "name": "موظف اختبار بدون تغيير كلمة السر",
        "salary": 7500,
        "job_role_id": job_role.id if job_role else None
    }
    res = client.post(
        f'/api/employees/update/{emp_id}/',
        data=json.dumps(partial_payload),
        content_type='application/json'
    )
    assert res.status_code == 200, f"Partial update failed: {res.content}"
    updated_emp.refresh_from_db()
    assert updated_emp.name == "موظف اختبار بدون تغيير كلمة السر"
    assert updated_emp.salary == 7500
    assert updated_emp.check_pin("9876") is True, "PIN was overwritten when omitted!"
    assert updated_emp.user.check_password("newSecurePassword123") is True, "Password was overwritten when omitted!"
    print("✓ Omitted PIN and Password were preserved 100% without system overwriting.")

    # 5.2 Test Update with empty salary (Must reject with 400)
    print("\n--- 4.2 Testing Update with empty salary (Validation) ---")
    bad_salary_payload = {
        "name": "اختبار راتب فارغ",
        "salary": ""
    }
    res = client.post(
        f'/api/employees/update/{emp_id}/',
        data=json.dumps(bad_salary_payload),
        content_type='application/json'
    )
    assert res.status_code == 400, f"Expected 400 for empty salary, got {res.status_code}"
    print("✓ Empty salary rejected with 400 as expected.")

    # 6. Test POST /api/employees/<id>/toggle-status/ (TOGGLE)
    print("\n--- 5. Testing Employee Status Toggle (DEACTIVATE / ACTIVATE) ---")
    # Toggle to inactive
    res = client.post(f'/api/employees/{emp_id}/toggle-status/')
    assert res.status_code == 200, f"Toggle failed: {res.content}"
    toggle_data = res.json()
    assert toggle_data["new_status"] == "inactive"
    updated_emp.refresh_from_db()
    assert updated_emp.status == "inactive"
    assert updated_emp.user.is_active is False
    print("✓ Successfully deactivated employee and disabled linked auth user.")

    # Toggle back to active
    res = client.post(f'/api/employees/{emp_id}/toggle-status/')
    assert res.status_code == 200, f"Toggle back failed: {res.content}"
    toggle_data = res.json()
    assert toggle_data["new_status"] == "active"
    updated_emp.refresh_from_db()
    assert updated_emp.status == "active"
    assert updated_emp.user.is_active is True
    print("✓ Successfully reactivated employee and re-enabled linked auth user.")

    # 7. Test GET /api/employees/export-csv/ (EXPORT)
    print("\n--- 6. Testing Employees CSV Export (EXPORT) ---")
    res = client.get('/api/employees/export-csv/')
    assert res.status_code == 200, f"Export CSV failed: {res.status_code}"
    assert res.get('Content-Disposition', '').startswith('attachment; filename="employees_')
    csv_bytes = res.content
    assert csv_bytes.startswith(b'\xef\xbb\xbf'), "UTF-8 BOM missing from CSV output"
    csv_text = csv_bytes.decode('utf-8-sig')
    assert "كود الموظف" in csv_text
    assert "موظف اختبار بدون تغيير كلمة السر" in csv_text
    print("✓ CSV Export generated with UTF-8 BOM and correct employee data.")

    # 8. Test POST /api/employees/<id>/delete/ (DELETE - Clean Hard Delete)
    print("\n--- 7. Testing Employee Smart Delete (Hard Delete when no orders) ---")
    res = client.post(f'/api/employees/{emp_id}/delete/')
    assert res.status_code == 200, f"Delete failed: {res.content}"
    del_data = res.json()
    assert del_data["action"] == "deleted"
    assert not Employee.objects.filter(id=emp_id).exists()
    print("✓ Clean smart delete executed: Employee without orders cleanly deleted.")

    # 9. Test POST /api/employees/<id>/delete/ (DELETE - Smart Archive when order history exists)
    print("\n--- 8. Testing Smart Archival (Soft Delete when order history exists) ---")
    from core.models import Order
    Order.objects.filter(order_number="ORD-TEST-9977").delete()
    Employee.objects.filter(tenant=tenant, employee_code="9977").delete()
    User.objects.filter(username="emp_test_with_orders").delete()

    emp_with_orders = Employee.objects.create(
        tenant=tenant,
        name="موظف ذو مبيعات",
        employee_code="9977",
        status="active"
    )
    user_with_orders = User.objects.create_user(username="emp_test_with_orders", password="password123")
    emp_with_orders.user = user_with_orders
    emp_with_orders.save()

    test_order = Order.objects.create(
        tenant=tenant,
        order_number="ORD-TEST-9977",
        cashier=emp_with_orders.name,
        total=150,
        status="delivered"
    )

    res = client.post(f'/api/employees/{emp_with_orders.id}/delete/')
    assert res.status_code == 200, f"Archive failed: {res.content}"
    archive_data = res.json()
    assert archive_data["action"] == "archived", f"Expected archived, got {archive_data}"
    emp_with_orders.refresh_from_db()
    assert emp_with_orders.status == "inactive"
    user_with_orders.refresh_from_db()
    assert user_with_orders.is_active is False
    print("✓ Smart archival successfully protected financial records: Employee archived and user deactivated.")

    # Cleanup test order and test employee
    test_order.delete()
    emp_with_orders.delete()
    user_with_orders.delete()

    print("\n=== ALL CRUD & SMART DELETION TESTS PASSED 100%! ===")

if __name__ == '__main__':
    run_tests()
