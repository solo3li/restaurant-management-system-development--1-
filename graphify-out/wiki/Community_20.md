# Community 20

> 43 nodes

## Key Concepts

- **get_redis_client()** (30 connections) — `core/redis_mcp_cache.py`
- **redis_mcp_cache.py** (29 connections) — `core/redis_mcp_cache.py`
- **track_order()** (16 connections) — `core/mcp/tools.py`
- **cart_get()** (15 connections) — `core/redis_mcp_cache.py`
- **signals.py** (14 connections) — `core/signals.py`
- **test_mcp_end_to_end.py** (14 connections) — `scratch/test_mcp_end_to_end.py`
- **remove_active_order()** (13 connections) — `core/redis_mcp_cache.py`
- **cache_active_order()** (12 connections) — `core/redis_mcp_cache.py`
- **get_active_order_by_number()** (11 connections) — `core/redis_mcp_cache.py`
- **run_tests()** (11 connections) — `scratch/test_mcp_end_to_end.py`
- **cart_add_item()** (10 connections) — `core/redis_mcp_cache.py`
- **get_active_order_by_phone()** (10 connections) — `core/redis_mcp_cache.py`
- **cart_clear()** (9 connections) — `core/redis_mcp_cache.py`
- **Any** (9 connections)
- **cart_remove_item()** (8 connections) — `core/redis_mcp_cache.py`
- **get_branch_menu_matrix()** (8 connections) — `core/redis_mcp_cache.py`
- **_cart_key()** (5 connections) — `core/redis_mcp_cache.py`
- **invalidate_branch_menu_cache()** (5 connections) — `core/redis_mcp_cache.py`
- **sync_order_redis_cache()** (5 connections) — `core/signals.py`
- **trigger_voice_ai_context_sync()** (5 connections) — `core/signals.py`
- **update_active_order_status()** (4 connections) — `core/redis_mcp_cache.py`
- **invalidate_tenant_api_key_redis_cache()** (4 connections) — `core/signals.py`
- **threading** (4 connections)
- **_async_sync()** (3 connections) — `core/signals.py`
- **receiver** (3 connections)
- *... and 18 more nodes in this community*

## Relationships

- [Community 26](Community_26.md) (33 shared connections)
- [Community 13](Community_13.md) (27 shared connections)
- [Community 36](Community_36.md) (22 shared connections)
- [Community 4](Community_4.md) (8 shared connections)
- [Community 7](Community_7.md) (4 shared connections)
- [Community 34](Community_34.md) (3 shared connections)
- [Community 203](Community_203.md) (1 shared connections)
- [Community 91](Community_91.md) (1 shared connections)

## Source Files

- `core/mcp/tools.py`
- `core/redis_mcp_cache.py`
- `core/signals.py`
- `scratch/test_mcp_end_to_end.py`

## Audit Trail

- EXTRACTED: 180 (96%)
- INFERRED: 7 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*