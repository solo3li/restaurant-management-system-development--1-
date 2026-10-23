import sys
import uvicorn
from core.mcp.schemas import OrderItemInput
from core.mcp.resolvers import (
    _normalize_digits,
    _strip_al,
    _normalize_arabic_text,
    _canonical_food_name,
    _clean_phone,
    _parse_natural_order_text,
    _resolve_item_variant,
    _find_menu_item,
    _validate_delivery_address_completeness,
    _format_branch_closed_err,
    _resolve_delivery_coverage_and_branch,
)
from core.mcp.middleware import (
    _check_key_valid,
    _get_cached_session_key,
    _set_cached_session_key,
    _get_latest_session_for_key,
    _current_session_key,
    _is_rate_limited,
    _authenticate,
    FastMCPAuthMiddleware,
    SSEAuthMiddleware,
    build_unified_mcp_asgi,
)
from core.mcp.cart import (
    handle_cart_add_item,
    handle_cart_view,
    handle_cart_remove_item,
    handle_cart_clear,
)
from core.mcp.tools import (
    mcp,
    get_branches,
    get_digital_menu_link,
    get_menu,
    lookup_customer,
    check_delivery_coverage,
    preview_order,
    calculate_order_total,
    create_callcenter_order,
    track_order,
    cancel_order,
    list_recent_orders,
    cart_add_item,
    cart_view,
    cart_remove_item,
    cart_clear,
)


def get_mcp_asgi_app():
    """Build and return unified ASGI app for FastMCP SSE."""
    return build_unified_mcp_asgi(mcp)


def run_server(host: str = "0.0.0.0", port: int = 8002):
    """Run FastMCP server on SSE exclusively."""
    print(f"Starting Restaurant FastMCP Server on SSE http://{host}:{port}/sse ...", file=sys.stderr)
    app = get_mcp_asgi_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = [
    "mcp",
    "OrderItemInput",
    "get_branches",
    "get_digital_menu_link",
    "get_menu",
    "lookup_customer",
    "check_delivery_coverage",
    "preview_order",
    "calculate_order_total",
    "create_callcenter_order",
    "track_order",
    "cancel_order",
    "list_recent_orders",
    "cart_add_item",
    "cart_view",
    "cart_remove_item",
    "cart_clear",
    "handle_cart_add_item",
    "handle_cart_view",
    "handle_cart_remove_item",
    "handle_cart_clear",
    "_normalize_digits",
    "_strip_al",
    "_normalize_arabic_text",
    "_canonical_food_name",
    "_clean_phone",
    "_parse_natural_order_text",
    "_resolve_item_variant",
    "_find_menu_item",
    "_validate_delivery_address_completeness",
    "_format_branch_closed_err",
    "_resolve_delivery_coverage_and_branch",
    "_authenticate",
    "_current_session_key",
    "FastMCPAuthMiddleware",
    "SSEAuthMiddleware",
    "build_unified_mcp_asgi",
    "get_mcp_asgi_app",
    "run_server",
]
