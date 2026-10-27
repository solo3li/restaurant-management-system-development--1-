"""
Platform HQ Tenant Module
Manages the dedicated Platform HQ tenant ("منظومة مطاعم HQ") for Super Admins.
Houses the official platform AI voice profiles, knowledge documents, and sales materials.
"""

import logging
from django.db import models

logger = logging.getLogger(__name__)

PLATFORM_HQ_NAME = "منظومة مطاعم HQ"
PLATFORM_HQ_SLUG = "platform-hq"
PLATFORM_HQ_CLIENT_ID = 49


def get_or_create_platform_hq_tenant():
    """
    Ensure the dedicated Super Admin / Platform HQ tenant exists and is fully initialized.
    Contains official platform profiles, sales knowledge documents, and is bound to partner client 49.
    """
    from apps.tenants.models import Tenant, Branch
    from apps.billing.models import SubscriptionPlan
    from apps.audit.models import KnowledgeDocument

    hq_tenant = Tenant.objects.filter(models.Q(slug=PLATFORM_HQ_SLUG) | models.Q(name=PLATFORM_HQ_NAME)).first()

    if not hq_tenant:
        hq_tenant = Tenant.objects.create(
            name=PLATFORM_HQ_NAME,
            slug=PLATFORM_HQ_SLUG,
            plan="enterprise",
            subscription_status="active",
            billing_cycle="yearly",
            voice_client_id=PLATFORM_HQ_CLIENT_ID,
            voice_username="motaem_hq",
            voice_is_active=True,
            is_active=True,
            brand_color="#0E382A",
            bio="المقر الرئيسي والمنصة المركزية لإدارة المنظومة وكول سنتر الذكاء الاصطناعي ومبيعات صفحة الهبوط.",
            email="hq@motaem.local",
            phone="920000000",
            address="الرياض، المملكة العربية السعودية",
        )
        logger.info(f"Created Platform HQ Tenant: {hq_tenant.name} (id={hq_tenant.id})")
    else:
        # Keep vital integration attributes synchronized
        updated = False
        if not hq_tenant.voice_client_id or hq_tenant.voice_client_id != PLATFORM_HQ_CLIENT_ID:
            hq_tenant.voice_client_id = PLATFORM_HQ_CLIENT_ID
            updated = True
        if not hq_tenant.voice_is_active:
            hq_tenant.voice_is_active = True
            updated = True
        if not hq_tenant.is_active:
            hq_tenant.is_active = True
            updated = True
        if updated:
            hq_tenant.save(update_fields=["voice_client_id", "voice_is_active", "is_active"])

    # 1. Ensure an enterprise SubscriptionPlan is attached
    if not hq_tenant.subscription_plan:
        plan = SubscriptionPlan.objects.filter(code="enterprise").first() or SubscriptionPlan.objects.first()
        if plan:
            hq_tenant.subscription_plan = plan
            hq_tenant.save(update_fields=["subscription_plan"])

    # 2. Ensure default HQ Branch exists
    Branch.objects.get_or_create(
        tenant=hq_tenant,
        name="المقر الرئيسي",
        defaults={
            "status": "active",
            "phone": "920000000",
            "city": "الرياض",
            "address": "الرياض، المملكة العربية السعودية",
        }
    )

    # 3. Ensure official platform knowledge documents exist
    official_knowledge_docs = [
        {
            "title": "دليل باقات الاشتراك ومزايا المنظومة السحابية (Sales & Subscriptions Guide)",
            "source_type": "faq",
        },
        {
            "title": "مستندات مبيعات كول سنتر الذكاء الاصطناعي ونقاط البيع POS وشاشات المطبخ KDS",
            "source_type": "faq",
        },
        {
            "title": "الأسئلة الشائعة للعملاء وطريقة بدء التجربة المجانية 14 يوماً بدون بطاقة",
            "source_type": "faq",
        },
    ]
    for doc in official_knowledge_docs:
        KnowledgeDocument.objects.get_or_create(
            tenant=hq_tenant,
            title=doc["title"],
            defaults={"source_type": doc["source_type"]}
        )

    return hq_tenant
