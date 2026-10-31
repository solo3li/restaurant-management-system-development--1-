import re
import json
import base64
import logging
from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils import timezone
from django.utils.html import strip_tags
from django.core.files.base import ContentFile

from apps.communication.models import BrevoConfiguration, VerificationCode, EmailLog, InboundEmailLog
from apps.communication.brevo_service import (
    send_brevo_email,
    send_password_reset_code,
    send_email_verification_code,
    send_direct_custom_email,
)
from apps.support.models import SupportTicket, TicketMessage, TicketAttachment

logger = logging.getLogger(__name__)


def forgot_password_view(request):
    """
    Full workflow for forgot password, verification code check, and reset password.
    Supports both interactive HTML page and asynchronous AJAX JSON calls.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        is_json = (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
            or "application/json" in (request.content_type or "")
        )
        post_data = request.POST
        if "application/json" in (request.content_type or "") and request.body:
            try:
                post_data = json.loads(request.body.decode("utf-8"))
            except Exception:
                post_data = request.POST

        identifier = post_data.get("identifier", "").strip() or post_data.get("email", "").strip()
        if not identifier:
            err_msg = "يرجى إدخال اسم المستخدم أو البريد الإلكتروني المسجل."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg})

        # Locate User
        user = User.objects.filter(email__iexact=identifier).first()
        if not user:
            user = User.objects.filter(username__iexact=identifier).first()

        target_email = ""
        if user and user.email:
            target_email = user.email.strip().lower()
        elif "@" in identifier:
            target_email = identifier.strip().lower()

        if not target_email:
            err_msg = "لم نتمكن من العثور على بريد إلكتروني مرتبط بهذا الحساب. يرجى التواصل مع الإدارة."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "identifier": identifier})

        # Generate 6-char alphanumeric code with 1-hour expiration
        code_obj = VerificationCode.generate_code(
            email=target_email,
            user=user,
            purpose="password_reset",
            expiry_hours=1
        )

        # Dispatch via Brevo
        send_res = send_password_reset_code(email=target_email, code=code_obj.code, user=user)

        # Mask email for privacy display (e.g. h***i@gmail.com)
        parts = target_email.split("@")
        masked_local = parts[0][:2] + "***" + parts[0][-1:] if len(parts[0]) > 2 else parts[0] + "***"
        masked_email = f"{masked_local}@{parts[1]}" if len(parts) > 1 else target_email

        if is_json:
            return JsonResponse({
                "status": "success",
                "message": f"تم إرسال رمز التحقق الأبجدي الرقمي المكون من 6 خانات إلى بريدك الإلكتروني ({masked_email}). الرمز صالح لمدة ساعة واحدة.",
                "email": target_email,
                "masked_email": masked_email,
                "step": "verify",
                "brevo_status": send_res.get("status")
            })

        return render(request, "forgot_password.html", {
            "success": True,
            "email": target_email,
            "masked_email": masked_email,
            "step": "verify",
        })

    return render(request, "forgot_password.html", {"step": "request", "email": "", "masked_email": ""})


def verify_code_view(request):
    """
    Validates the 6-character alphanumeric code for password reset or email verification.
    Strictly enforces 1-hour expiration time and single-use constraint.
    """
    if request.method == "POST":
        is_json = (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
            or "application/json" in (request.content_type or "")
        )
        post_data = request.POST
        if "application/json" in (request.content_type or "") and request.body:
            try:
                post_data = json.loads(request.body.decode("utf-8"))
            except Exception:
                post_data = request.POST

        email = post_data.get("email", "").strip().lower()
        code = post_data.get("code", "").strip().upper()
        purpose = post_data.get("purpose", "password_reset").strip()

        if not email or not code:
            err_msg = "يرجى إدخال البريد الإلكتروني ورمز التحقق المكون من 6 خانات."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "step": "verify"})

        code_obj = VerificationCode.objects.filter(
            email=email,
            code=code,
            purpose=purpose
        ).order_by("-created_at").first()

        if not code_obj:
            err_msg = "رمز التحقق غير صحيح، يرجى التأكد من كتابة الأحرف الكبيرة والأرقام بدقة."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "step": "verify"})

        if code_obj.is_used:
            err_msg = "تم استخدام هذا الرمز مسبقاً. يرجى طلب رمز تحقق جديد."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "step": "verify"})

        if timezone.now() > code_obj.expires_at:
            err_msg = "انتهت صلاحية رمز التحقق (الصلاحية مدتها ساعة واحدة فقط). يرجى طلب رمز جديد."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "step": "verify"})

        # If purpose is email verification, mark code as used immediately and complete workflow
        if purpose == "email_verification":
            code_obj.is_used = True
            code_obj.save(update_fields=["is_used"])
            success_msg = "تم تأكيد وتوثيق البريد الإلكتروني بنجاح!"
            if is_json:
                return JsonResponse({
                    "status": "success",
                    "message": success_msg,
                    "email": email,
                    "code": code,
                    "verified": True,
                })
            return render(request, "forgot_password.html", {
                "success": True,
                "success_message": success_msg,
                "email": email,
                "verified": True,
                "step": "done"
            })

        if is_json:
            return JsonResponse({
                "status": "success",
                "message": "تم التحقق من الرمز بنجاح. يمكنك الآن تعيين كلمة المرور الجديدة.",
                "email": email,
                "code": code,
                "step": "reset"
            })

        return render(request, "forgot_password.html", {
            "email": email,
            "code": code,
            "step": "reset"
        })

    email = request.GET.get("email", "")
    return render(request, "forgot_password.html", {"email": email, "step": "verify"})


def send_verification_code_view(request):
    """
    Generates and dispatches a 6-character alphanumeric verification code via Brevo.
    Supports email_verification and account_security purposes with strict 1-hour expiration.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST method allowed.")

    is_json = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
        or "application/json" in (request.content_type or "")
    )
    post_data = request.POST
    if "application/json" in (request.content_type or "") and request.body:
        try:
            post_data = json.loads(request.body.decode("utf-8"))
        except Exception:
            post_data = request.POST

    target_email = post_data.get("email", "").strip().lower()
    purpose = post_data.get("purpose", "email_verification").strip()

    target_user = None
    if request.user.is_authenticated:
        target_user = request.user
        if not target_email and request.user.email:
            target_email = request.user.email.strip().lower()

    if not target_email and target_user:
        target_email = target_user.email.strip().lower() if target_user.email else ""

    if not target_email:
        target_username = post_data.get("username", "").strip()
        if target_username:
            u = User.objects.filter(username__iexact=target_username).first()
            if u and u.email:
                target_user = u
                target_email = u.email.strip().lower()

    if not target_email or "@" not in target_email:
        err_msg = "يرجى تحديد عنوان بريد إلكتروني صالح لاستلام رمز التحقق."
        if is_json:
            return JsonResponse({"status": "error", "message": err_msg}, status=400)
        return HttpResponseBadRequest(err_msg)

    # Generate 6-char alphanumeric code with 1-hour expiration
    code_obj = VerificationCode.generate_code(
        email=target_email,
        user=target_user,
        purpose=purpose,
        expiry_hours=1
    )

    if purpose == "email_verification":
        send_res = send_email_verification_code(email=target_email, code=code_obj.code, user=target_user)
    else:
        send_res = send_password_reset_code(email=target_email, code=code_obj.code, user=target_user)

    msg = f"تم إرسال رمز التحقق الأبجدي الرقمي المكون من 6 خانات إلى البريد ({target_email}). الرمز صالح لمدة ساعة واحدة."
    return JsonResponse({
        "status": "success",
        "message": msg,
        "email": target_email,
        "purpose": purpose,
        "code_id": code_obj.id,
        "brevo_status": send_res.get("status")
    })



def reset_password_view(request):
    """
    Resets the user's password after verifying the 6-character code.
    Marks the code as used immediately.
    """
    if request.method == "POST":
        is_json = (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
            or "application/json" in (request.content_type or "")
        )
        post_data = request.POST
        if "application/json" in (request.content_type or "") and request.body:
            try:
                post_data = json.loads(request.body.decode("utf-8"))
            except Exception:
                post_data = request.POST

        email = post_data.get("email", "").strip().lower()
        code = post_data.get("code", "").strip().upper()
        new_password = post_data.get("new_password", "").strip()
        confirm_password = post_data.get("confirm_password", "").strip()

        if not email or not code or not new_password:
            err_msg = "يرجى تعبئة كافة الحقول المطلوبة."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "code": code, "step": "reset"})

        if len(new_password) < 6:
            err_msg = "كلمة المرور الجديدة يجب أن لا تقل عن 6 خانات."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "code": code, "step": "reset"})

        if confirm_password and new_password != confirm_password:
            err_msg = "كلمتا المرور غير متطابقتين."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "code": code, "step": "reset"})

        # Verify Code
        code_obj = VerificationCode.objects.filter(
            email=email,
            code=code,
            purpose="password_reset"
        ).order_by("-created_at").first()

        if not code_obj or not code_obj.is_valid:
            err_msg = "رمز التحقق غير صالح أو انتهت صلاحيته (1 ساعة). يرجى المحاولة من جديد."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "email": email, "step": "request"})

        # Find user to reset
        user = code_obj.user or User.objects.filter(email__iexact=email).first()
        if not user:
            err_msg = "تعذر تحديد حساب المستخدم المرتبط بهذا البريد."
            if is_json:
                return JsonResponse({"status": "error", "message": err_msg}, status=400)
            return render(request, "forgot_password.html", {"error": err_msg, "step": "request"})

        # Apply new password
        user.set_password(new_password)
        user.save()

        # Mark code as used
        code_obj.is_used = True
        code_obj.save(update_fields=["is_used"])

        success_msg = "تم إعادة تعيين كلمة المرور بنجاح! يمكنك الآن تسجيل الدخول بكلمة المرور الجديدة."
        if is_json:
            return JsonResponse({
                "status": "success",
                "message": success_msg,
                "redirect": reverse("login")
            })

        return render(request, "login.html", {
            "success_message": success_msg
        })

    return redirect("forgot_password")


@csrf_exempt
def brevo_inbound_webhook_view(request):
    """
    Receives and processes inbound email webhooks and transaction events from Brevo.
    Parses sender, recipient, subject, body text, body html, and links incoming reply emails
    to the corresponding SupportTicket if a ticket reference is found.
    Supports validating optional webhook_secret and extracting binary attachments up to 25MB.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST method allowed.")

    config = BrevoConfiguration.get_config()
    # Webhook secret protection if configured
    if config.webhook_secret:
        incoming_secret = (
            request.GET.get("secret")
            or request.GET.get("token")
            or request.headers.get("X-Webhook-Secret")
            or request.headers.get("X-Brevo-Token")
            or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        )
        if incoming_secret != config.webhook_secret:
            logger.warning("Brevo inbound webhook rejected: invalid secret or token")
            return HttpResponseForbidden("Invalid webhook secret.")

    payload = {}
    content_type = request.content_type or ""

    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception as ex:
            logger.warning(f"Failed to parse Brevo webhook JSON: {ex}")
            payload = {"raw": request.body.decode("utf-8", errors="ignore")}
    else:
        payload = request.POST.dict()

    # Extract headers
    req_headers = {k: v for k, v in request.headers.items()}

    # Brevo inbound payloads can be formatted with 'items' array or direct fields
    items = payload.get("items") if isinstance(payload.get("items"), list) else [payload]

    processed_logs = []

    for item in items:
        # Determine sender email and name
        sender_email = ""
        sender_name = ""
        from_field = item.get("From") or item.get("from") or item.get("sender") or {}
        if isinstance(from_field, dict):
            sender_email = from_field.get("Address") or from_field.get("email") or ""
            sender_name = from_field.get("Name") or from_field.get("name") or ""
        elif isinstance(from_field, str):
            sender_email = from_field

        # Determine recipient email
        recipient_email = ""
        to_field = item.get("To") or item.get("to") or item.get("recipient") or []
        if isinstance(to_field, list) and to_field:
            first_to = to_field[0]
            if isinstance(first_to, dict):
                recipient_email = first_to.get("Address") or first_to.get("email") or ""
            else:
                recipient_email = str(first_to)
        elif isinstance(to_field, str):
            recipient_email = to_field

        subject = item.get("Subject") or item.get("subject") or item.get("title") or "No Subject"
        body_text = item.get("RawTextBody") or item.get("ExtractedMarkdownMessage") or item.get("text") or item.get("content") or ""
        body_html = item.get("RawHtmlBody") or item.get("html") or ""
        msg_id = item.get("MessageId") or item.get("message-id") or item.get("message_id") or ""

        # Event type if delivered/opened/reply event webhook
        event = item.get("event") or ""
        if event and not body_text:
            body_text = f"Brevo Email Event: {event} for {item.get('email', '')}"

        # Create InboundEmailLog
        log_entry = InboundEmailLog.objects.create(
            message_id=msg_id,
            sender_email=sender_email[:255] if sender_email else "unknown@brevo.webhook",
            sender_name=sender_name[:255],
            recipient_email=recipient_email[:255],
            subject=subject[:500],
            body_text=body_text,
            body_html=body_html,
            raw_payload=payload if isinstance(payload, dict) else {"payload": payload},
            headers=req_headers,
            is_processed=False
        )

        # Inspect subject, body text, and body HTML for ticket reference: TCK-YYYYMM-XXXX
        ticket_match = (
            re.search(r'TCK-\d{6}-[A-Za-z0-9]+', subject)
            or re.search(r'TCK-\d{6}-[A-Za-z0-9]+', body_text)
            or re.search(r'TCK-\d{6}-[A-Za-z0-9]+', body_html)
        )
        if ticket_match:
            ticket_num = ticket_match.group(0)
            ticket = SupportTicket.objects.filter(ticket_number=ticket_num).first()
            if ticket:
                log_entry.ticket = ticket

                # Determine sender user
                sender_user = User.objects.filter(email__iexact=sender_email).first()
                if not sender_user:
                    sender_user = ticket.creator

                # Check if sender is tenant or support
                is_tenant_sender = (
                    sender_email.lower() == (ticket.creator.email or "").lower()
                    or sender_email.lower() == (ticket.tenant.email or "").lower()
                )
                sender_type = "tenant" if is_tenant_sender else "support"

                reply_text = body_text.strip()
                if not reply_text and body_html:
                    reply_text = strip_tags(body_html).strip()

                if reply_text or item.get("Attachments") or item.get("attachments"):
                    msg_content = reply_text if reply_text else "مرفقات واردة عبر البريد الإلكتروني"
                    ticket_msg = TicketMessage.objects.create(
                        ticket=ticket,
                        sender=sender_user,
                        sender_type=sender_type,
                        message=msg_content
                    )

                    # Ingest attachments from Brevo Inbound payload if present
                    attachments_list = item.get("Attachments") or item.get("attachments") or []
                    if isinstance(attachments_list, list):
                        for att_dict in attachments_list:
                            if not isinstance(att_dict, dict):
                                continue
                            att_name = att_dict.get("Name") or att_dict.get("name") or "attachment"
                            att_content_b64 = att_dict.get("Content") or att_dict.get("content") or ""
                            att_content_type = att_dict.get("ContentType") or att_dict.get("contentType") or ""
                            if att_content_b64:
                                try:
                                    raw_bytes = base64.b64decode(att_content_b64)
                                    if len(raw_bytes) <= TicketAttachment.MAX_FILE_SIZE_BYTES:
                                        cfile = ContentFile(raw_bytes, name=att_name)
                                        ftype = TicketAttachment.detect_file_type(att_name, att_content_type)
                                        TicketAttachment.objects.create(
                                            ticket=ticket,
                                            message=ticket_msg,
                                            file=cfile,
                                            file_type=ftype,
                                            file_name=att_name,
                                            file_size=len(raw_bytes),
                                        )
                                except Exception as att_ex:
                                    logger.warning(f"Failed to process inbound attachment {att_name}: {att_ex}")

                    # Update ticket status if closed/resolved or if support replied to open ticket
                    if sender_type == "tenant" and ticket.status in ("resolved", "closed"):
                        ticket.status = "in_progress"
                        ticket.save(update_fields=["status", "updated_at"])
                    elif sender_type == "support" and ticket.status == "open":
                        ticket.status = "in_progress"
                        ticket.save(update_fields=["status", "updated_at"])
                    else:
                        ticket.updated_at = timezone.now()
                        ticket.save(update_fields=["updated_at"])

                    log_entry.is_processed = True
                    log_entry.save(update_fields=["ticket", "is_processed"])
                    logger.info(f"Inbound reply mapped to SupportTicket {ticket_num}")

        processed_logs.append(log_entry.id)

    return JsonResponse({
        "status": "success",
        "processed_count": len(processed_logs),
        "log_ids": processed_logs
    })



@staff_member_required
def admin_send_direct_email_view(request):
    """
    Dedicated Django Admin Tool to compose and dispatch formatted custom emails
    directly to a selected user or customer via the Brevo API.
    """
    config = BrevoConfiguration.get_config()
    users = User.objects.filter(is_active=True).exclude(email="").order_by("username")

    initial_email = request.GET.get("email", "")
    initial_name = request.GET.get("name", "")
    initial_user_id = request.GET.get("user_id", "")
    if initial_user_id and not initial_email:
        u = User.objects.filter(pk=initial_user_id).first()
        if u:
            initial_email = u.email
            initial_name = u.get_full_name() or u.username

    feedback = None

    if request.method == "POST":
        recipient_email = request.POST.get("recipient_email", "").strip()
        recipient_name = request.POST.get("recipient_name", "").strip()
        subject = request.POST.get("subject", "").strip()
        body_content = request.POST.get("body_content", "").strip()

        if not recipient_email or not subject or not body_content:
            feedback = {"type": "error", "message": "يرجى إدخال البريد المستلم، عنوان الرسالة، ومحتوى الرسالة."}
        else:
            result = send_direct_custom_email(
                to_email=recipient_email,
                subject=subject,
                body_content=body_content,
                to_name=recipient_name
            )
            if result.get("status") == "success":
                msg_id = result.get("message_id", "")
                feedback = {
                    "type": "success",
                    "message": f"تم إرسال البريد الإلكتروني بنجاح عبر Brevo! معرف الرسالة: {msg_id}"
                }
            else:
                feedback = {
                    "type": "error",
                    "message": f"فشل إرسال البريد عبر Brevo: {result.get('error', 'خطأ غير معروف')}"
                }

    context = {
        "title": "إرسال بريد إلكتروني مخصص عبر Brevo",
        "config": config,
        "users": users,
        "initial_email": initial_email,
        "initial_name": initial_name,
        "feedback": feedback,
    }
    return render(request, "admin/brevo/send_custom_email.html", context)
