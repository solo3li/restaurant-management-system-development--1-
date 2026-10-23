# Community 45

> 27 nodes

## Key Concepts

- **Tenant** (31 connections) — `apps/tenants/models.py`
- **SubscriptionPlan** (12 connections) — `apps/billing/models.py`
- **get_currency_info()** (12 connections) — `core/currencies.py`
- **api_request_upgrade()** (9 connections) — `apps/billing/views.py`
- **landing_view()** (7 connections) — `core/views.py`
- **api_digital_menu_branch_areas()** (6 connections) — `apps/menu/views.py`
- **.get_currency_name_ar()** (2 connections) — `apps/tenants/models.py`
- **.get_currency_symbol_ar()** (2 connections) — `apps/tenants/models.py`
- **.get_currency_symbol_en()** (2 connections) — `apps/tenants/models.py`
- **.get_currency_name_ar()** (2 connections) — `apps/tenants/models.py`
- **.get_currency_symbol_ar()** (2 connections) — `apps/tenants/models.py`
- **.get_currency_symbol_en()** (2 connections) — `apps/tenants/models.py`
- **.is_subscription_active()** (2 connections) — `apps/tenants/models.py`
- **.is_subscription_expired()** (2 connections) — `apps/tenants/models.py`
- **Meta** (1 connections) — `apps/billing/models.py`
- **Meta** (1 connections) — `apps/tenants/models.py`
- **.__str__()** (1 connections) — `apps/billing/models.py`
- **.can_add_branch()** (1 connections) — `apps/tenants/models.py`
- **.can_add_employee()** (1 connections) — `apps/tenants/models.py`
- **.days_until_expiry()** (1 connections) — `apps/tenants/models.py`
- **.has_feature()** (1 connections) — `apps/tenants/models.py`
- **.__str__()** (1 connections) — `apps/tenants/models.py`
- **login_required** (1 connections)
- **API for tenant owner to submit an upgrade request.** (1 connections) — `apps/billing/views.py`
- **Return JSON list of delivery areas for chosen branch.** (1 connections) — `apps/menu/views.py`
- *... and 2 more nodes in this community*

## Relationships

- [Community 2](Community_2.md) (22 shared connections)
- [Community 3](Community_3.md) (8 shared connections)
- [Community 4](Community_4.md) (6 shared connections)
- [Community 7](Community_7.md) (4 shared connections)
- [Community 12](Community_12.md) (3 shared connections)
- [Community 195](Community_195.md) (2 shared connections)
- [Community 134](Community_134.md) (1 shared connections)
- [Community 90](Community_90.md) (1 shared connections)
- [Community 74](Community_74.md) (1 shared connections)

## Source Files

- `apps/billing/models.py`
- `apps/billing/views.py`
- `apps/menu/views.py`
- `apps/tenants/models.py`
- `core/currencies.py`
- `core/views.py`

## Audit Trail

- EXTRACTED: 60 (78%)
- INFERRED: 17 (22%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*