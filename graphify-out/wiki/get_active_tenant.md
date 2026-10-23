# get_active_tenant()

> God node · 112 connections · `apps/tenants/helpers.py`

**Community:** [Community 3](Community_3.md)

## Connections by Relation

### calls
- _check_callcenter_admin() `EXTRACTED`
- get_active_branch() `EXTRACTED`
- api_create_order() `EXTRACTED`
- order_edit_view() `EXTRACTED`
- api_update_menu_item() `EXTRACTED`
- api_create_menu_item() `EXTRACTED`
- api_create_employee() `EXTRACTED`
- api_ai_callcenter_update_mcp_url() `EXTRACTED`
- _validate_callcenter_page_access() `EXTRACTED`
- api_update_branch_item_price() `EXTRACTED`
- api_update_item_branch_prices() `EXTRACTED`
- api_delivery_live() `EXTRACTED`
- api_update_order() `EXTRACTED`
- delivery_view() `EXTRACTED`
- dashboard_view() `EXTRACTED`
- api_update_employee() `EXTRACTED`
- owner_subscription_view() `EXTRACTED`
- api_ai_callcenter_sync_mcp() `EXTRACTED`
- kitchen_view() `EXTRACTED`
- api_ai_callcenter_dial_customer() `EXTRACTED`
- *…and 77 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- tenants/helpers.py `EXTRACTED`

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
- audit/views.py `EXTRACTED`

### indirect_call
- delivery_stream_view() `INFERRED`
- kitchen_stream_view() `INFERRED`

### rationale_for
- Resolve the active tenant for the current request. `EXTRACTED`

### uses
- Tenant `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*