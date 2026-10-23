import logging
import threading
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from core.models import MenuItem, MenuItemVariant, BranchMenuAvailability, Branch, DeliveryArea, Order, TenantApiKey

logger = logging.getLogger(__name__)

def _async_sync(tenant):
    from django.db import connections
    try:
        from core import partner_service as ps
        ps.sync_tenant_live_context(tenant)
        logger.info(f"[VOICE AI SYNC] Successfully synced live context to Voice AI for tenant: {tenant.name}")
    except Exception as e:
        logger.warning(f"[VOICE AI SYNC] Could not push live context for tenant {tenant.name}: {e}")
    finally:
        connections.close_all()


@receiver([post_save, post_delete], sender=MenuItem)
@receiver([post_save, post_delete], sender=MenuItemVariant)
@receiver([post_save, post_delete], sender=BranchMenuAvailability)
@receiver([post_save, post_delete], sender=Branch)
@receiver([post_save, post_delete], sender=DeliveryArea)
def trigger_voice_ai_context_sync(sender, instance, **kwargs):
    tenant = None
    branch_id = None
    try:
        tenant = getattr(instance, "tenant", None)
        if not tenant and hasattr(instance, "branch") and instance.branch:
            tenant = getattr(instance.branch, "tenant", None)
            branch_id = instance.branch.id
        elif not tenant and hasattr(instance, "menu_item") and instance.menu_item:
            tenant = getattr(instance.menu_item, "tenant", None)

        if hasattr(instance, "branch_id"):
            branch_id = instance.branch_id
        elif sender == Branch:
            branch_id = instance.id
    except Exception:
        tenant = None

    # 1. Invalidate Redis in-memory menu matrix cache immediately
    if tenant:
        try:
            from core.redis_mcp_cache import invalidate_branch_menu_cache
            invalidate_branch_menu_cache(tenant.id, branch_id)
        except Exception as ex:
            logger.warning(f"Error invalidating Redis menu matrix cache: {ex}")

    # 2. Push live context to Voice AI partner service
    if tenant and hasattr(tenant, "has_feature") and tenant.has_feature("call_center"):
        threading.Thread(target=_async_sync, args=(tenant,), daemon=True).start()


@receiver(post_save, sender=Order)
def sync_order_redis_cache(sender, instance, **kwargs):
    """Keep active orders in Redis in perfect sync with all DB order status changes (Admin, POS, Kitchen)."""
    try:
        from core.redis_mcp_cache import cache_active_order, remove_active_order
        if instance.status in ["delivered", "cancelled", "canceled"]:
            remove_active_order(instance.tenant_id, instance.order_number)
        elif instance.status in ["new", "preparing", "ready", "out_for_delivery", "on_way"]:
            cache_active_order(instance)
    except Exception as e:
        logger.warning(f"Error syncing order status in Redis cache: {e}")


@receiver([post_save, post_delete], sender=TenantApiKey)
def invalidate_tenant_api_key_redis_cache(sender, instance, **kwargs):
    """Purge cached API key from Redis immediately when modified, disabled, or deleted."""
    try:
        from core.redis_mcp_cache import invalidate_api_key
        if instance.key:
            invalidate_api_key(instance.key)
    except Exception as e:
        logger.warning(f"Error invalidating API key cache: {e}")


