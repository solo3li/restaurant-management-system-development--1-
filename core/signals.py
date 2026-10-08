import logging
import threading
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from core.models import MenuItem, Branch, DeliveryArea

logger = logging.getLogger(__name__)

def _async_sync(tenant):
    try:
        from core import partner_service as ps
        ps.sync_tenant_live_context(tenant)
        logger.info(f"[VOICE AI SYNC] Successfully synced live context to Voice AI for tenant: {tenant.name}")
    except Exception as e:
        logger.warning(f"[VOICE AI SYNC] Could not push live context for tenant {tenant.name}: {e}")

@receiver([post_save, post_delete], sender=MenuItem)
@receiver([post_save, post_delete], sender=Branch)
@receiver([post_save, post_delete], sender=DeliveryArea)
def trigger_voice_ai_context_sync(sender, instance, **kwargs):
    tenant = getattr(instance, "tenant", None)
    if not tenant and hasattr(instance, "branch") and instance.branch:
        tenant = getattr(instance.branch, "tenant", None)

    if tenant and hasattr(tenant, "has_feature") and tenant.has_feature("call_center"):
        threading.Thread(target=_async_sync, args=(tenant,), daemon=True).start()
