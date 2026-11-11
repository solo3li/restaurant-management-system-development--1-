import logging
from django.utils import timezone
from apps.communication.brevo_service import send_brevo_email

logger = logging.getLogger(__name__)


def send_upgrade_approved_notification(upgrade_request):
    """
    Sends a confirmation email to the tenant owner via Brevo upon upgrade request approval.
    """
    tenant = upgrade_request.tenant
    plan = upgrade_request.requested_plan

    # Resolve recipient email
    recipient_email = ""
    recipient_name = ""

    if upgrade_request.requested_by and upgrade_request.requested_by.email:
        recipient_email = upgrade_request.requested_by.email
        recipient_name = upgrade_request.requested_by.get_full_name() or upgrade_request.requested_by.username
    elif tenant.email:
        recipient_email = tenant.email
        recipient_name = tenant.name
    else:
        owner_profile = tenant.user_profiles.filter(role="owner").select_related("user").first()
        if owner_profile and owner_profile.user and owner_profile.user.email:
            recipient_email = owner_profile.user.email
            recipient_name = owner_profile.user.get_full_name() or owner_profile.user.username

    if not recipient_email:
        logger.warning(f"No valid recipient email found for tenant {tenant.slug} upgrade notification.")
        return None

    cycle_display = upgrade_request.get_billing_cycle_display()
    currency = upgrade_request.currency or "USD"
    amount = upgrade_request.amount or (plan.price_yearly if upgrade_request.billing_cycle == "yearly" else plan.price_monthly)
    end_date_str = tenant.subscription_end.strftime("%Y-%m-%d") if tenant.subscription_end else "—"

    subject = f"🎉 تم تفعيل اشتراكك في «{plan.name}» بنجاح | Subscription Activated"

    html_content = f"""
    <div dir="rtl" style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden;">
        <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 32px 24px; text-align: center; color: #ffffff;">
            <h1 style="margin: 0; font-size: 24px; font-weight: bold;">تهانينا! تم تفعيل اشتراكك بنجاح 🎉</h1>
            <p style="margin: 8px 0 0 0; font-size: 14px; opacity: 0.9;">نظام مطاعم معتم السحابي (Motaem Cloud Restaurant OS)</p>
        </div>

        <div style="padding: 28px 24px; color: #1e293b; line-height: 1.6;">
            <p style="font-size: 15px; margin-top: 0;">مرحباً <strong>{recipient_name}</strong>،</p>
            <p style="font-size: 14px; color: #475569;">
                يسرنا إبلاغك بأنه تمت مراجعة واعتماد طلب الاشتراك الخاص بمنشأة <strong>«{tenant.name}»</strong> بنجاح.
            </p>

            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin: 20px 0;">
                <h3 style="margin: 0 0 12px 0; font-size: 15px; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">تفاصيل الخطة والاشتراك:</h3>
                <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 6px 0; color: #64748b;">الباقة المفعلة:</td>
                        <td style="padding: 6px 0; font-weight: bold; color: #4f46e5; text-align: left;">{plan.name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748b;">دورة الفوترة:</td>
                        <td style="padding: 6px 0; font-weight: bold; color: #0f172a; text-align: left;">{cycle_display}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748b;">المبلغ المسدد:</td>
                        <td style="padding: 6px 0; font-weight: bold; color: #10b981; text-align: left;">{amount} {currency}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748b;">طريقة الدفع:</td>
                        <td style="padding: 6px 0; font-weight: bold; color: #0f172a; text-align: left;">{upgrade_request.get_payment_method_display()}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748b;">تاريخ انتهاء الاشتراك:</td>
                        <td style="padding: 6px 0; font-weight: bold; color: #0f172a; text-align: left;">{end_date_str}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748b;">دقائق الكول سنتر المضمنة:</td>
                        <td style="padding: 6px 0; font-weight: bold; color: #0f172a; text-align: left;">{plan.monthly_voice_minutes} دقيقة / شهر</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748b;">حصص رسائل الواتساب:</td>
                        <td style="padding: 6px 0; font-weight: bold; color: #0f172a; text-align: left;">{plan.monthly_messages_quota} رسالة / شهر</td>
                    </tr>
                </table>
            </div>

            <p style="font-size: 13px; color: #64748b; margin-bottom: 24px;">
                تم تحديث سعة الفروع والموظفين وميزات النظام وربط الكول سنتر تلقائياً بحسابك.
            </p>

            <div style="text-align: center; margin: 30px 0;">
                <a href="https://uggu.space/dashboard/" style="background: #4f46e5; color: #ffffff; padding: 12px 32px; border-radius: 8px; font-size: 14px; font-weight: bold; text-decoration: none; display: inline-block;">
                    الدخول إلى لوحة العمليات
                </a>
            </div>
        </div>

        <div style="background-color: #f1f5f9; padding: 16px 24px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0;">
            <p style="margin: 0;">شكراً لثقتكم بنظام معتم لإدارة وتشغيل المطاعم السحابية.</p>
            <p style="margin: 4px 0 0 0;">لأي استفسار أو دعم فني يرجى التواصل معنا عبر تذاكر الدعم بالمنصة.</p>
        </div>
    </div>
    """

    return send_brevo_email(
        to_email=recipient_email,
        subject=subject,
        html_content=html_content,
        to_name=recipient_name,
    )
