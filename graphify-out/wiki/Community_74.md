# Community 74

> 19 nodes

## Key Concepts

- **UpgradeRequest** (12 connections) — `apps/billing/models.py`
- **sync_tenant_voice_caps()** (9 connections) — `core/partner_service.py`
- **ensure_tenant_registered()** (8 connections) — `core/partner_service.py`
- **get_plan_voice_caps()** (8 connections) — `core/partner_service.py`
- **get_client_usage()** (7 connections) — `core/partner_service.py`
- **update_client_cap()** (6 connections) — `core/partner_service.py`
- **test_voice_partner_quota_integration()** (6 connections) — `test_voice_quota_partner_sync.py`
- **register_sub_client()** (5 connections) — `core/partner_service.py`
- **.apply_upgrade()** (4 connections) — `apps/billing/models.py`
- **.save()** (2 connections) — `apps/billing/models.py`
- **Meta** (1 connections) — `apps/billing/models.py`
- **.__str__()** (1 connections) — `apps/billing/models.py`
- **Apply requested plan and extension to the tenant.** (1 connections) — `apps/billing/models.py`
- **Direct Partner API call to update call minute and spending caps for a client.…** (1 connections) — `core/partner_service.py`
- **Fetch live usage statistics, consumption, and cap limits for a sub-client from…** (1 connections) — `core/partner_service.py`
- **Synchronize call minute and spending caps to the Voice AI partner platform for…** (1 connections) — `core/partner_service.py`
- **Register a new sub-client tenant on the Voice AI partner platform.** (1 connections) — `core/partner_service.py`
- **Ensure a tenant has a registered voice client and owner credentials saved.** (1 connections) — `core/partner_service.py`
- **Resolve minute and spending caps based on tenant subscription plan tier.…** (1 connections) — `core/partner_service.py`

## Relationships

- [Community 40](Community_40.md) (9 shared connections)
- [Community 3](Community_3.md) (7 shared connections)
- [Community 91](Community_91.md) (6 shared connections)
- [Community 4](Community_4.md) (3 shared connections)
- [Community 2](Community_2.md) (2 shared connections)
- [Community 134](Community_134.md) (1 shared connections)
- [Community 137](Community_137.md) (1 shared connections)
- [Community 45](Community_45.md) (1 shared connections)

## Source Files

- `apps/billing/models.py`
- `core/partner_service.py`
- `test_voice_quota_partner_sync.py`

## Audit Trail

- EXTRACTED: 49 (92%)
- INFERRED: 4 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*