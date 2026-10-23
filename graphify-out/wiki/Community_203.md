# Community 203

> 6 nodes

## Key Concepts

- **sync_tenant_live_context()** (8 connections) — `core/partner_service.py`
- **update_client_live_context()** (5 connections) — `core/partner_service.py`
- **build_tenant_live_context_payload()** (4 connections) — `core/partner_service.py`
- **Atomically overwrite structured live context in DB and Redis cache (<2ms).** (1 connections) — `core/partner_service.py`
- **Build a comprehensive, clean JSON payload representing restaurant branches,…** (1 connections) — `core/partner_service.py`
- **Generate the complete live context payload for the tenant and push it…** (1 connections) — `core/partner_service.py`

## Relationships

- [Community 40](Community_40.md) (4 shared connections)
- [Community 91](Community_91.md) (3 shared connections)
- [Community 3](Community_3.md) (2 shared connections)
- [Community 20](Community_20.md) (1 shared connections)

## Source Files

- `core/partner_service.py`

## Audit Trail

- EXTRACTED: 15 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*