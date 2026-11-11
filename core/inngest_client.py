import os
import logging
from datetime import timedelta
from django.utils import timezone
import inngest
import inngest.django

logger = logging.getLogger(__name__)

# Initialize Inngest client
INNGEST_APP_ID = os.getenv("INNGEST_APP_ID", "motaem-restaurant-os")
INNGEST_SIGNING_KEY = os.getenv("INNGEST_SIGNING_KEY", None)
INNGEST_EVENT_KEY = os.getenv("INNGEST_EVENT_KEY", None)
INNGEST_IS_PRODUCTION = os.getenv("INNGEST_IS_PRODUCTION", "False").lower() in ("true", "1", "yes")

inngest_client = inngest.Inngest(
    app_id=INNGEST_APP_ID,
    signing_key=INNGEST_SIGNING_KEY,
    event_key=INNGEST_EVENT_KEY,
    is_production=INNGEST_IS_PRODUCTION,
)


def run_subscription_transitions():
    """
    Core logic for subscription status transitions:
    - Active / Trial -> Grace Period (within 3 days post-expiration)
    - Grace Period -> Expired (Read-Only hard lockout after 3 days)
    - Restores Active if extended
    """
    from apps.tenants.models import Tenant

    now = timezone.now()
    three_days_ago = now - timedelta(days=3)

    active_or_trial_tenants = Tenant.objects.filter(
        subscription_status__in=["active", "trial"],
        subscription_end__isnull=False,
    )

    entered_grace = 0
    entered_expired = 0

    for t in active_or_trial_tenants:
        if t.subscription_end and t.subscription_end < now:
            if t.subscription_end >= three_days_ago:
                t.subscription_status = "grace_period"
                t.save(update_fields=["subscription_status"])
                entered_grace += 1
            else:
                t.subscription_status = "expired"
                t.save(update_fields=["subscription_status"])
                entered_expired += 1

    grace_tenants = Tenant.objects.filter(subscription_status="grace_period")
    for t in grace_tenants:
        if t.subscription_end:
            if t.subscription_end < three_days_ago:
                t.subscription_status = "expired"
                t.save(update_fields=["subscription_status"])
                entered_expired += 1
            elif t.subscription_end > now:
                t.subscription_status = "active"
                t.save(update_fields=["subscription_status"])

    logger.info(f"[Inngest Cron] Subscription transitions check completed. Grace: {entered_grace}, Expired: {entered_expired}")
    return {
        "status": "completed",
        "timestamp": now.isoformat(),
        "entered_grace": entered_grace,
        "entered_expired": entered_expired,
    }


@inngest_client.create_function(
    fn_id="check-subscription-transitions",
    trigger=inngest.TriggerCron(cron="0 0 * * *"),
)
def check_subscription_transitions(ctx, step):
    """Daily midnight cron job."""
    return run_subscription_transitions()


def run_reset_monthly_quotas():
    """
    Core logic for monthly quota resets:
    Runs daily to identify tenants reaching their monthly billing cycle reset day,
    resetting PBX voice minutes and message/character allowances to plan quotas.
    """
    from apps.tenants.models import Tenant
    from core import partner_service as ps

    now = timezone.now()
    active_tenants = Tenant.objects.filter(
        subscription_status__in=["active", "trial"],
        subscription_plan__isnull=False,
    )

    reset_count = 0
    for tenant in active_tenants:
        start_day = tenant.subscription_start.day if tenant.subscription_start else 1
        is_reset_day = (now.day == start_day) or (now.day == 1 and start_day > 28)

        if is_reset_day:
            try:
                ps.sync_tenant_voice_caps(tenant, reset_to_plan=True)
                reset_count += 1
            except Exception as e:
                logger.warning(f"[Inngest Quota Reset] Failed for {tenant.slug}: {e}")

    logger.info(f"[Inngest Cron] Monthly quota reset processed for {reset_count} tenants.")
    return {
        "status": "completed",
        "tenants_reset": reset_count,
        "timestamp": now.isoformat(),
    }


@inngest_client.create_function(
    fn_id="reset-monthly-tenant-quotas",
    trigger=inngest.TriggerCron(cron="0 1 * * *"),
)
def reset_monthly_tenant_quotas(ctx, step):
    """Monthly quota reset cron job."""
    return run_reset_monthly_quotas()


def run_upgrade_approved(tenant_id, request_id=None):
    """Core logic to push quota and dispatch notification email when upgrade is approved."""
    from apps.tenants.models import Tenant
    from apps.billing.models import UpgradeRequest
    from apps.billing.notifications import send_upgrade_approved_notification
    from core import partner_service as ps

    result = {"quota": None, "email": None}

    tenant = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None
    if tenant:
        try:
            ps.sync_tenant_voice_caps(tenant, reset_to_plan=True)
            logger.info(f"[Inngest Event] Quota push executed for upgraded tenant {tenant.slug}")
            result["quota"] = "synced"
            result["tenant"] = tenant.slug
        except Exception as e:
            logger.warning(f"[Inngest Event] Quota push failed for {tenant.slug}: {e}")
            result["quota"] = f"failed: {e}"
    else:
        result["quota"] = "tenant_not_found"

    if request_id:
        req = UpgradeRequest.objects.filter(id=request_id).first()
        if req:
            try:
                email_result = send_upgrade_approved_notification(req)
                logger.info(f"[Inngest Event] Brevo notification email processed for upgrade #{request_id}")
                result["email"] = "sent" if email_result else "logged"
            except Exception as e:
                logger.warning(f"[Inngest Event] Brevo notification email failed for #{request_id}: {e}")
                result["email"] = f"failed: {e}"
        else:
            result["email"] = "request_not_found"

    return result


@inngest_client.create_function(
    fn_id="on-upgrade-approved",
    trigger=inngest.TriggerEvent(event="upgrade.approved"),
)
def on_upgrade_approved(ctx, step):
    """Event-driven job fired when an upgrade request is approved."""
    event_data = ctx.event.data or {}
    tenant_id = event_data.get("tenant_id")
    request_id = event_data.get("request_id")
    return run_upgrade_approved(tenant_id, request_id)


def send_inngest_event(name: str, data: dict):
    """Safely dispatches an event to Inngest with fault tolerance."""
    import asyncio
    try:
        event = inngest.Event(name=name, data=data)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(inngest_client.send(event))
            else:
                loop.run_until_complete(inngest_client.send(event))
        except RuntimeError:
            asyncio.run(inngest_client.send(event))
    except Exception as e:
        logger.warning(f"Inngest event {name} dispatch skipped/failed: {e}")


# Django URLPattern for Inngest webhook endpoint
inngest_url_pattern = inngest.django.serve(
    inngest_client,
    [check_subscription_transitions, reset_monthly_tenant_quotas, on_upgrade_approved],
    serve_path="/api/inngest/",
)
