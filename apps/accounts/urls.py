from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("employees/", views.employees_view, name="employees"),
    path("api/employees/create/", views.api_create_employee, name="api_create_employee"),
    path("api/employees/<int:emp_id>/", views.api_update_employee, name="api_update_employee_short"),
    path("api/employees/update/<int:emp_id>/", views.api_update_employee, name="api_update_employee"),
    path("api/employees/<int:emp_id>/delete/", views.api_delete_employee, name="api_delete_employee"),
    path("api/employees/<int:emp_id>/toggle-status/", views.api_toggle_employee_status, name="api_toggle_employee_status"),
    path("api/employees/<int:emp_id>/detail/", views.api_employee_detail, name="api_employee_detail"),
    path("api/employees/export-csv/", views.api_export_employees_csv, name="api_export_employees_csv"),
    path("api/job-roles/", views.api_job_roles, name="api_job_roles"),
    path("api/job-roles/<int:role_id>/", views.api_job_role_detail, name="api_job_role_detail"),
]
