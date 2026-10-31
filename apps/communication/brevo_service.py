import logging
from typing import Optional, Dict, Any

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error
    import json

    class _MockResponse:
        def __init__(self, status_code, content, headers=None):
            self.status_code = status_code
            self.content = content
            self.text = content.decode("utf-8", errors="ignore")
            self.headers = headers or {}

        def json(self):
            return json.loads(self.text)

    class _RequestsShim:
        @staticmethod
        def post(url, data=None, json=None, headers=None, timeout=12):
            headers = headers or {}
            body = None
            if json is not None:
                headers["Content-Type"] = "application/json"
                body = __import__("json").dumps(json).encode("utf-8")
            elif data is not None:
                body = data if isinstance(data, bytes) else str(data).encode("utf-8")

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return _MockResponse(resp.getcode(), resp.read(), dict(resp.headers))
            except urllib.error.HTTPError as he:
                return _MockResponse(he.code, he.read(), dict(he.headers))
            except Exception as e:
                raise e

        @staticmethod
        def get(url, headers=None, timeout=8):
            headers = headers or {}
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return _MockResponse(resp.getcode(), resp.read(), dict(resp.headers))
            except urllib.error.HTTPError as he:
                return _MockResponse(he.code, he.read(), dict(he.headers))
            except Exception as e:
                raise e

    requests = _RequestsShim()
from typing import Optional, Dict, Any
from django.db import models
from django.utils.html import strip_tags
from django.utils import timezone
from apps.communication.models import BrevoConfiguration, EmailLog

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_brevo_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    to_name: Optional[str] = None,
    reply_to: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    config: Optional[BrevoConfiguration] = None,
) -> Dict[str, Any]:
    """
    Sends a transactional email via Brevo SMTP API.
    Persists delivery logs and status in EmailLog model.
    """
    if config is None:
        config = BrevoConfiguration.get_config()

    to_email = to_email.strip()
    to_name = to_name or to_email
    if not text_content:
        text_content = strip_tags(html_content)

    email_log = EmailLog.objects.create(
        recipient_email=to_email,
        recipient_name=to_name,
        subject=subject,
        body_preview=text_content[:200],
        status="queued",
    )

    if not config.is_active:
        msg = "Brevo email sending is deactivated in BrevoConfiguration."
        logger.warning(msg)
        email_log.status = "failed"
        email_log.error_message = msg
        email_log.save(update_fields=["status", "error_message"])
        return {"status": "error", "error": msg, "log_id": email_log.id}

    if not config.api_key:
        msg = "Brevo API key is not configured."
        logger.error(msg)
        email_log.status = "failed"
        email_log.error_message = msg
        email_log.save(update_fields=["status", "error_message"])
        return {"status": "error", "error": msg, "log_id": email_log.id}

    req_headers = {
        "accept": "application/json",
        "api-key": config.api_key,
        "content-type": "application/json",
    }
    if headers:
        req_headers.update(headers)

    default_reply_to = {"email": config.sender_email, "name": config.sender_name}
    payload = {
        "sender": {
            "name": config.sender_name,
            "email": config.sender_email,
        },
        "to": [
            {
                "email": to_email,
                "name": to_name,
            }
        ],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content,
        "replyTo": reply_to or default_reply_to,
    }

    try:
        response = requests.post(
            BREVO_API_URL,
            json=payload,
            headers=req_headers,
            timeout=12,
        )
        if response.status_code in (200, 201):
            res_data = response.json()
            message_id = res_data.get("messageId", "")
            email_log.status = "sent"
            email_log.brevo_message_id = message_id
            email_log.save(update_fields=["status", "brevo_message_id"])

            # Increment sent counter
            BrevoConfiguration.objects.filter(pk=config.pk).update(
                total_sent_count=models.F("total_sent_count") + 1
            )
            return {"status": "success", "message_id": message_id, "log_id": email_log.id}
        else:
            err_text = response.text
            logger.error(f"Brevo API failed [{response.status_code}]: {err_text}")
            email_log.status = "failed"
            email_log.error_message = f"HTTP {response.status_code}: {err_text}"
            email_log.save(update_fields=["status", "error_message"])
            return {"status": "error", "error": err_text, "status_code": response.status_code, "log_id": email_log.id}

    except Exception as exc:
        err_msg = str(exc)
        logger.exception(f"Exception while sending email via Brevo: {err_msg}")
        email_log.status = "failed"
        email_log.error_message = err_msg
        email_log.save(update_fields=["status", "error_message"])
        return {"status": "error", "error": err_msg, "log_id": email_log.id}


def get_branded_email_wrapper(content_html: str, title: str = "منظومة مطاعم") -> str:
    """Standardized high-craft email layout matching Motaem Slate theme."""
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #f8fafc; direction: rtl; text-align: right;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #0f172a; padding: 40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 580px; background-color: #1e293b; border: 1px solid #334155; border-radius: 20px; overflow: hidden; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);">
          <!-- Header -->
          <tr>
            <td style="padding: 32px 36px 20px 36px; border-bottom: 1px solid #334155; background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="right" style="vertical-align: middle;">
                    <div style="display: inline-block;">
                      <h1 style="margin: 0; font-size: 22px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">مطاعم</h1>
                      <div style="font-size: 11px; font-weight: 700; color: #8b5cf6; text-transform: uppercase; letter-spacing: 1px; margin-top: 2px;">Cloud Restaurant OS</div>
                    </div>
                  </td>
                  <td align="left" style="vertical-align: middle;">
                    <span style="display: inline-block; padding: 6px 12px; background-color: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 10px; font-size: 11px; font-weight: 700; color: #c4b5fd;">
                      إشعار نظامي
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding: 36px; color: #e2e8f0; font-size: 14px; line-height: 1.7;">
              {content_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 24px 36px; background-color: #0f172a; border-top: 1px solid #334155; text-align: center; color: #64748b; font-size: 11px; line-height: 1.6;">
              <p style="margin: 0 0 6px 0;">منظومة مطاعم السحابية لإدارة المطاعم ونقاط البيع الذكية © 2026</p>
              <p style="margin: 0; color: #475569;">هذا البريد تم إرساله تلقائياً عبر منصة Brevo المعتمدة من مطاعم Cloud OS.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_password_reset_code(email: str, code: str, user=None) -> Dict[str, Any]:
    """Sends the 6-character alphanumeric verification code for password reset."""
    subject = f"رمز إعادة تعيين كلمة المرور: {code} — منظومة مطاعم"
    content = f"""
    <div style="text-align: right;">
      <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 700; color: #ffffff;">طلب إعادة تعيين كلمة المرور</h2>
      <p style="margin: 0 0 20px 0; color: #94a3b8; font-size: 14px;">
        تلقينا طلباً لإعادة تعيين كلمة المرور الخاصة بحسابك في منظومة مطاعم. يرجى استخدام الرمز الأبجدي الرقمي التالي لإتمام العملية:
      </p>

      <!-- 6-Char Alphanumeric Code Display -->
      <div style="background-color: #0f172a; border: 2px dashed #8b5cf6; border-radius: 16px; padding: 24px; text-align: center; margin: 28px 0;">
        <span style="font-size: 11px; font-weight: 700; color: #a78bfa; text-transform: uppercase; letter-spacing: 1.5px; display: block; margin-bottom: 8px;">رمز التحقق (6 خانات)</span>
        <div style="font-family: 'Courier New', Courier, monospace; font-size: 38px; font-weight: 900; letter-spacing: 12px; color: #ffffff; text-shadow: 0 0 20px rgba(139, 92, 246, 0.6);">{code}</div>
      </div>

      <div style="background-color: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 12px; padding: 14px 18px; margin-bottom: 24px;">
        <p style="margin: 0; font-size: 12px; font-weight: 600; color: #fbbf24;">
          ⏰ <strong>تنبيه الصلاحية:</strong> هذا الرمز صالح للاستخدام لمدة <strong>ساعة واحدة فقط (1 Hour)</strong> من وقت إرساله.
        </p>
      </div>

      <p style="margin: 0; color: #64748b; font-size: 12px; line-height: 1.6;">
        إذا لم تطلب إعادة تعيين كلمة المرور بنفسك، يمكنك تجاهل هذه الرسالة بأمان وستظل كلمة مرورك الحالية نشطة ومحمية.
      </p>
    </div>
    """
    html = get_branded_email_wrapper(content, title="إعادة تعيين كلمة المرور")
    return send_brevo_email(to_email=email, subject=subject, html_content=html, to_name=user.get_full_name() if user else None)


def send_email_verification_code(email: str, code: str, user=None) -> Dict[str, Any]:
    """Sends the 6-character alphanumeric verification code for email verification."""
    subject = f"تأكيد البريد الإلكتروني: {code} — منظومة مطاعم"
    content = f"""
    <div style="text-align: right;">
      <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 700; color: #ffffff;">تأكيد البريد الإلكتروني</h2>
      <p style="margin: 0 0 20px 0; color: #94a3b8; font-size: 14px;">
        شكراً لانضمامك إلى منظومة مطاعم. يرجى إدخال رمز التحقق التالي لتأكيد بريدك الإلكتروني وتفعيل كافة صلاحيات المنشأة:
      </p>

      <div style="background-color: #0f172a; border: 2px dashed #10b981; border-radius: 16px; padding: 24px; text-align: center; margin: 28px 0;">
        <span style="font-size: 11px; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 1.5px; display: block; margin-bottom: 8px;">رمز التأكيد</span>
        <div style="font-family: 'Courier New', Courier, monospace; font-size: 38px; font-weight: 900; letter-spacing: 12px; color: #ffffff;">{code}</div>
      </div>

      <p style="margin: 0; font-size: 12px; font-weight: 600; color: #94a3b8;">
        ⏰ هذا الرمز صالح لمدة <strong>ساعة واحدة</strong>.
      </p>
    </div>
    """
    html = get_branded_email_wrapper(content, title="تأكيد البريد الإلكتروني")
    return send_brevo_email(to_email=email, subject=subject, html_content=html, to_name=user.get_full_name() if user else None)


def send_direct_custom_email(
    to_email: str,
    subject: str,
    body_content: str,
    to_name: Optional[str] = None
) -> Dict[str, Any]:
    """Sends an arbitrary direct custom email from Django Admin to a customer or user."""
    # Check if body_content already has HTML doctype or tags
    if "<html" in body_content.lower():
        html = body_content
    else:
        # Wrap paragraphs
        paragraphs = "".join(f"<p style='margin: 0 0 14px 0;'>{p.strip()}</p>" for p in body_content.split("\n\n") if p.strip())
        content = f"""
        <div style="text-align: right;">
          <h2 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 700; color: #ffffff;">{subject}</h2>
          <div style="color: #cbd5e1; font-size: 14px; line-height: 1.8;">
            {paragraphs or body_content}
          </div>
        </div>
        """
        html = get_branded_email_wrapper(content, title=subject)

    return send_brevo_email(to_email=to_email, subject=subject, html_content=html, to_name=to_name)


def send_ticket_notification(
    ticket,
    event_type: str = "new_ticket",
    message_obj=None,
    recipient_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Sends transactional notification email regarding Support Ticket events.
    Format includes ticket number in subject (e.g. [TCK-202610-1234]) to enable inbound webhook replies!
    """
    config = BrevoConfiguration.get_config()
    target_email = recipient_email
    if not target_email:
        if event_type == "new_reply" and message_obj and message_obj.sender_type == "support":
            # Notify the customer / tenant creator
            target_email = ticket.creator.email or ticket.tenant.email
        elif event_type == "new_reply" and message_obj and message_obj.sender_type == "tenant":
            # Notify support / admin
            target_email = config.sender_email
        else:
            target_email = ticket.creator.email or ticket.tenant.email

    if not target_email:
        return {"status": "skipped", "reason": "No valid recipient email"}

    subject = f"[{ticket.ticket_number}] {ticket.subject}"
    preview_msg = message_obj.message if message_obj else ticket.description

    content = f"""
    <div style="text-align: right;">
      <div style="margin-bottom: 16px;">
        <span style="display: inline-block; padding: 4px 10px; background-color: #334155; border-radius: 8px; font-size: 12px; font-family: monospace; color: #cbd5e1; font-weight: 700;">
          {ticket.ticket_number}
        </span>
        <span style="display: inline-block; margin-right: 8px; font-size: 12px; color: #94a3b8;">
          الحالة: <strong>{ticket.get_status_display()}</strong>
        </span>
      </div>

      <h2 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 700; color: #ffffff;">{ticket.subject}</h2>

      <div style="background-color: #0f172a; border-right: 4px solid #8b5cf6; padding: 18px 20px; border-radius: 8px; margin: 20px 0; color: #e2e8f0; font-size: 14px; line-height: 1.7; white-space: pre-wrap;">
        {preview_msg}
      </div>

      <p style="margin: 20px 0 0 0; color: #94a3b8; font-size: 12px;">
        💡 يمكنك الرد مباشرة على هذه الرسالة البريدية لإضافة ردك تلقائياً إلى التذكرة، أو متابعة التذكرة عبر لوحة تحكم المنظومة.
      </p>
    </div>
    """
    html = get_branded_email_wrapper(content, title=f"تذكرة دعم {ticket.ticket_number}")
    return send_brevo_email(to_email=target_email, subject=subject, html_content=html)
