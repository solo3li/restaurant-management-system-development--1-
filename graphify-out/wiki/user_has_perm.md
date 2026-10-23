# user_has_perm()

> God node · 70 connections · `apps/accounts/helpers.py`

**Community:** [Community 2](Community_2.md)

## Connections by Relation

### calls
- _check_callcenter_admin() `EXTRACTED`
- get_active_branch() `EXTRACTED`
- api_create_order() `EXTRACTED`
- order_edit_view() `EXTRACTED`
- api_update_menu_item() `EXTRACTED`
- api_create_menu_item() `EXTRACTED`
- api_create_employee() `EXTRACTED`
- api_update_branch_item_price() `EXTRACTED`
- api_update_item_branch_prices() `EXTRACTED`
- api_delivery_live() `EXTRACTED`
- api_update_order() `EXTRACTED`
- delivery_view() `EXTRACTED`
- dashboard_view() `EXTRACTED`
- api_update_employee() `EXTRACTED`
- owner_subscription_view() `EXTRACTED`
- kitchen_view() `EXTRACTED`
- run_e2e_tests() `INFERRED`
- api_create_inventory() `EXTRACTED`
- branch_menu_view() `EXTRACTED`
- api_cancel_order() `EXTRACTED`
- *…and 35 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- accounts/helpers.py `EXTRACTED`

### imports
- core/views.py `EXTRACTED`
- callcenter/views.py `EXTRACTED`
- orders/views.py `EXTRACTED`
- accounts/views.py `EXTRACTED`
- menu/views.py `EXTRACTED`
- tenants/views.py `EXTRACTED`
- billing/views.py `EXTRACTED`
- inventory/views.py `EXTRACTED`
- kitchen/views.py `EXTRACTED`
- tenants/helpers.py `EXTRACTED`
- audit/views.py `EXTRACTED`

### indirect_call
- delivery_stream_view() `INFERRED`
- kitchen_stream_view() `INFERRED`

### rationale_for
- Unified pure Django auth permission check. Bypasses for superuser and tenant… `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*