# Community 41

> 28 nodes

## Key Concepts

- **SSEAuthMiddleware** (8 connections) — `core/mcp/middleware.py`
- **build_unified_mcp_asgi()** (8 connections) — `core/mcp/middleware.py`
- **run_asgi_tests()** (8 connections) — `scratch/test_mcp_sse_transport.py`
- **run_server()** (6 connections) — `core/mcp/__init__.py`
- **get_mcp_asgi_app()** (5 connections) — `core/mcp/__init__.py`
- **Command** (4 connections) — `core/management/commands/run_asgi.py`
- **Command** (4 connections) — `core/management/commands/run_callcenter_mcp.py`
- **run_asgi.py** (4 connections) — `core/management/commands/run_asgi.py`
- **run_callcenter_mcp.py** (4 connections) — `core/management/commands/run_callcenter_mcp.py`
- **django_core_management_base** (3 connections)
- **uvicorn** (3 connections)
- **.handle()** (2 connections) — `core/management/commands/run_callcenter_mcp.py`
- **uuid** (2 connections)
- **.add_arguments()** (1 connections) — `core/management/commands/run_asgi.py`
- **.handle()** (1 connections) — `core/management/commands/run_asgi.py`
- **.add_arguments()** (1 connections) — `core/management/commands/run_callcenter_mcp.py`
- **unified_mcp_asgi()** (1 connections) — `core/mcp/middleware.py`
- **.__init__()** (1 connections) — `core/mcp/middleware.py`
- **mock_app()** (1 connections) — `scratch/test_mcp_sse_transport.py`
- **mock_msg_app()** (1 connections) — `scratch/test_mcp_sse_transport.py`
- **mock_recv()** (1 connections) — `scratch/test_mcp_sse_transport.py`
- **mock_send()** (1 connections) — `scratch/test_mcp_sse_transport.py`
- **BaseCommand** (1 connections)
- **BaseCommand** (1 connections)
- **Build and return unified ASGI app for FastMCP SSE.** (1 connections) — `core/mcp/__init__.py`
- *... and 3 more nodes in this community*

## Relationships

- [Community 36](Community_36.md) (5 shared connections)
- [Community 13](Community_13.md) (5 shared connections)
- [Community 26](Community_26.md) (5 shared connections)
- [Community 4](Community_4.md) (5 shared connections)

## Source Files

- `core/management/commands/run_asgi.py`
- `core/management/commands/run_callcenter_mcp.py`
- `core/mcp/__init__.py`
- `core/mcp/middleware.py`
- `scratch/test_mcp_sse_transport.py`

## Audit Trail

- EXTRACTED: 40 (83%)
- INFERRED: 8 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*