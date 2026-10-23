# _get_client_ip()

> God node · 37 connections · `apps/accounts/helpers.py`

**Community:** [Community 2](Community_2.md)

## Connections by Relation

### calls
- api_create_order() `EXTRACTED`
- order_edit_view() `EXTRACTED`
- api_update_menu_item() `EXTRACTED`
- api_create_menu_item() `EXTRACTED`
- api_create_employee() `EXTRACTED`
- api_update_branch_item_price() `EXTRACTED`
- api_update_item_branch_prices() `EXTRACTED`
- api_update_order() `EXTRACTED`
- api_update_employee() `EXTRACTED`
- api_create_inventory() `EXTRACTED`
- api_cancel_order() `EXTRACTED`
- api_delete_order() `EXTRACTED`
- api_branch_delivery_areas() `EXTRACTED`
- api_update_branch_currency() `EXTRACTED`
- api_delete_employee() `EXTRACTED`
- api_job_role_detail() `EXTRACTED`
- api_job_roles() `EXTRACTED`
- login_view() `EXTRACTED`
- api_create_api_key() `EXTRACTED`
- api_adjust_inventory() `EXTRACTED`
- *…and 8 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- accounts/helpers.py `EXTRACTED`

### imports
- core/views.py `EXTRACTED`
- callcenter/views.py `EXTRACTED`
- orders/views.py `EXTRACTED`
- accounts/views.py `EXTRACTED`
- menu/views.py `EXTRACTED`
- tenants/views.py `EXTRACTED`
- inventory/views.py `EXTRACTED`

### rationale_for
- Safely extracts client IP address from HTTP request headers. `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*