import os
import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Q

from apps.tenants.helpers import get_active_tenant
from apps.accounts.helpers import user_has_perm
from apps.support.models import SupportTicket, TicketMessage, TicketAttachment
from apps.communication.brevo_service import send_ticket_notification

logger = logging.getLogger(__name__)


@login_required
def support_tickets_view(request):
    """
    Full-Page Support Ticket System in General Administration tabs (_admin_nav_tabs.html):
    Provides status filtering (All, Open, In Progress, Resolved, Closed), search, metrics cards,
    and new ticket submission modal.
    """
    active_tenant = get_active_tenant(request)
    is_platform_admin = request.user.is_superuser or getattr(getattr(request.user, "profile", None), "is_platform_admin", False)

    # Tenant Scoping
    if is_platform_admin and not active_tenant:
        tickets_qs = SupportTicket.objects.all()
    else:
        if not active_tenant:
            return HttpResponseForbidden("لم يتم تحديد المنشأة النشطة للوصول إلى تذاكر الدعم.")
        tickets_qs = SupportTicket.objects.filter(tenant=active_tenant)

    # Metrics
    open_count = tickets_qs.filter(status="open").count()
    in_progress_count = tickets_qs.filter(status="in_progress").count()
    resolved_count = tickets_qs.filter(status="resolved").count()
    closed_count = tickets_qs.filter(status="closed").count()
    total_count = tickets_qs.count()

    # Filtering
    status_filter = request.GET.get("status", "all").strip().lower()
    if status_filter in ("open", "in_progress", "resolved", "closed"):
        tickets_qs = tickets_qs.filter(status=status_filter)

    category_filter = request.GET.get("category", "").strip()
    if category_filter:
        tickets_qs = tickets_qs.filter(category=category_filter)

    search_query = request.GET.get("q", "").strip()
    if search_query:
        tickets_qs = tickets_qs.filter(
            Q(ticket_number__icontains=search_query)
            | Q(subject__icontains=search_query)
            | Q(description__icontains=search_query)
        )

    tickets = tickets_qs.select_related("creator", "tenant").prefetch_related("attachments", "messages").order_by("-updated_at")

    context = {
        "tickets": tickets,
        "active_tab": "support_tickets",
        "status_filter": status_filter,
        "category_filter": category_filter,
        "search_query": search_query,
        "stats": {
            "open": open_count,
            "in_progress": in_progress_count,
            "resolved": resolved_count,
            "closed": closed_count,
            "total": total_count,
        },
        "open_tickets_count": open_count,
        "category_choices": SupportTicket.CATEGORY_CHOICES,
        "priority_choices": SupportTicket.PRIORITY_CHOICES,
        "tenant": active_tenant,
        "is_owner": getattr(getattr(request.user, "profile", None), "role", "") == "owner" or is_platform_admin,
    }
    return render(request, "support_tickets.html", context)


@login_required
def support_ticket_detail_view(request, ticket_id):
    """
    Dedicated view for a single Support Ticket conversation thread:
    Displays customer vs support agent messages, inline voice notes with HTML5 player,
    image thumbnails with lightbox viewer, inline video players, and quick reply form.
    """
    active_tenant = get_active_tenant(request)
    is_platform_admin = request.user.is_superuser or getattr(getattr(request.user, "profile", None), "is_platform_admin", False)

    ticket = get_object_or_404(SupportTicket.objects.select_related("creator", "tenant", "assigned_to"), pk=ticket_id)

    # Multi-tenant isolation enforcement
    if not is_platform_admin and ticket.tenant != active_tenant:
        return HttpResponseForbidden("غير مصرح لك باستعراض هذه التذكرة.")

    messages = ticket.messages.select_related("sender").prefetch_related("attachments").order_by("created_at")
    ticket_attachments = ticket.attachments.filter(message__isnull=True).order_by("created_at")

    open_count = SupportTicket.objects.filter(tenant=ticket.tenant, status="open").count()

    context = {
        "ticket": ticket,
        "messages": messages,
        "ticket_attachments": ticket_attachments,
        "active_tab": "support_tickets",
        "open_tickets_count": open_count,
        "tenant": active_tenant or ticket.tenant,
        "is_owner": getattr(getattr(request.user, "profile", None), "role", "") == "owner" or is_platform_admin,
        "is_platform_admin": is_platform_admin,
    }
    return render(request, "support_ticket_detail.html", context)


@login_required
def api_create_ticket(request):
    """
    API endpoint to create a new Support Ticket with rich media attachments (up to 25MB per file)
    and optional browser-recorded voice note.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST method allowed.")

    active_tenant = get_active_tenant(request)
    if not active_tenant and not request.user.is_superuser:
        return JsonResponse({"status": "error", "message": "لم يتم تحديد منشأة نشطة."}, status=400)

    post_data = request.POST
    subject = post_data.get("subject", "").strip()
    description = post_data.get("description", "").strip()
    category = post_data.get("category", "technical").strip()
    priority = post_data.get("priority", "medium").strip()

    if not subject or not description:
        return JsonResponse({"status": "error", "message": "يرجى كتابة عنوان التذكرة وتفاصيل المشكلة."}, status=400)

    # File size validation (Max 25MB per file)
    max_size = TicketAttachment.MAX_FILE_SIZE_BYTES
    uploaded_files = request.FILES.getlist("attachments")
    audio_note = request.FILES.get("audio_note")
    all_incoming_files = list(uploaded_files)
    if audio_note:
        all_incoming_files.append(audio_note)

    for f in all_incoming_files:
        if f.size > max_size:
            return JsonResponse({
                "status": "error",
                "message": f"الملف '{f.name}' يتجاوز الحد الأقصى المسموح به (25 ميجابايت). حجم الملف الحالي: {f.size / (1024*1024):.1f} MB."
            }, status=400)

    ticket_number = SupportTicket.generate_ticket_number()
    ticket = SupportTicket.objects.create(
        tenant=active_tenant,
        ticket_number=ticket_number,
        creator=request.user,
        subject=subject,
        description=description,
        category=category,
        priority=priority,
        status="open",
    )

    # Save media attachments
    for f in uploaded_files:
        file_type = TicketAttachment.detect_file_type(f.name, getattr(f, "content_type", ""))
        TicketAttachment.objects.create(
            ticket=ticket,
            message=None,
            file=f,
            file_type=file_type,
            file_name=f.name,
            file_size=f.size,
        )

    # Save voice note if recorded in browser
    if audio_note:
        raw_duration = post_data.get("audio_duration", "0")
        try:
            duration_sec = int(float(raw_duration))
        except Exception:
            duration_sec = 0

        TicketAttachment.objects.create(
            ticket=ticket,
            message=None,
            file=audio_note,
            file_type="audio",
            file_name=audio_note.name or "voice_recording.webm",
            file_size=audio_note.size,
            duration_seconds=duration_sec,
        )

    # Dispatch Brevo Notification
    try:
        send_ticket_notification(ticket, event_type="new_ticket")
    except Exception as ex:
        logger.warning(f"Failed to dispatch Brevo ticket notification: {ex}")

    return JsonResponse({
        "status": "success",
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "message": f"تم فتح التذكرة بنجاح برقم {ticket.ticket_number}",
        "redirect_url": reverse("support_ticket_detail", args=[ticket.id])
    })


@login_required
def api_ticket_reply(request, ticket_id):
    """
    API endpoint to append a reply to a ticket thread with optional rich media attachments
    (images, videos, audio notes up to 25MB).
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST method allowed.")

    active_tenant = get_active_tenant(request)
    is_platform_admin = request.user.is_superuser or getattr(getattr(request.user, "profile", None), "is_platform_admin", False)

    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    if not is_platform_admin and ticket.tenant != active_tenant:
        return JsonResponse({"status": "error", "message": "غير مصرح لك بالرد على هذه التذكرة."}, status=403)

    post_data = request.POST
    message_text = post_data.get("message", "").strip()

    uploaded_files = request.FILES.getlist("attachments")
    audio_note = request.FILES.get("audio_note")

    if not message_text and not uploaded_files and not audio_note:
        return JsonResponse({"status": "error", "message": "يرجى كتابة رد أو إرفاق ملف/تسجيل صوتي."}, status=400)

    # Validate file sizes <= 25MB
    max_size = TicketAttachment.MAX_FILE_SIZE_BYTES
    all_incoming_files = list(uploaded_files)
    if audio_note:
        all_incoming_files.append(audio_note)

    for f in all_incoming_files:
        if f.size > max_size:
            return JsonResponse({
                "status": "error",
                "message": f"الملف '{f.name}' يتجاوز الحد الأقصى (25 ميجابايت). الحجم الحالي: {f.size / (1024*1024):.1f} MB."
            }, status=400)

    sender_type = "support" if (request.user.is_superuser or request.user.is_staff or is_platform_admin) else "tenant"

    if not message_text and audio_note:
        message_text = "🎙️ تسجيل صوتي مرسل"

    msg = TicketMessage.objects.create(
        ticket=ticket,
        sender=request.user,
        sender_type=sender_type,
        message=message_text,
    )

    # Save regular attachments
    for f in uploaded_files:
        ftype = TicketAttachment.detect_file_type(f.name, getattr(f, "content_type", ""))
        TicketAttachment.objects.create(
            ticket=ticket,
            message=msg,
            file=f,
            file_type=ftype,
            file_name=f.name,
            file_size=f.size,
        )

    # Save voice note
    if audio_note:
        raw_duration = post_data.get("audio_duration", "0")
        try:
            duration_sec = int(float(raw_duration))
        except Exception:
            duration_sec = 0

        TicketAttachment.objects.create(
            ticket=ticket,
            message=msg,
            file=audio_note,
            file_type="audio",
            file_name=audio_note.name or "voice_reply.webm",
            file_size=audio_note.size,
            duration_seconds=duration_sec,
        )

    # Status transitions:
    # 1. Tenant reply on resolved/closed ticket reopens it to in_progress
    # 2. Support staff reply on open ticket moves it to in_progress
    if sender_type == "tenant" and ticket.status in ("resolved", "closed"):
        ticket.status = "in_progress"
        ticket.save(update_fields=["status", "updated_at"])
    elif sender_type == "support" and ticket.status == "open":
        ticket.status = "in_progress"
        ticket.save(update_fields=["status", "updated_at"])
    else:
        ticket.updated_at = timezone.now()
        ticket.save(update_fields=["updated_at"])

    # Brevo notification
    try:
        send_ticket_notification(ticket, event_type="new_reply", message_obj=msg)
    except Exception as ex:
        logger.warning(f"Brevo reply notification warning: {ex}")

    return JsonResponse({
        "status": "success",
        "message_id": msg.id,
        "sender_name": request.user.get_full_name() or request.user.username,
        "sender_type": sender_type,
        "message": msg.message,
        "created_at": msg.created_at.strftime("%Y-%m-%d %H:%M"),
        "ticket_status": ticket.status,
    })


@login_required
def api_ticket_update_status(request, ticket_id):
    """
    API endpoint to transition ticket status (open, in_progress, resolved, closed).
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST method allowed.")

    active_tenant = get_active_tenant(request)
    is_platform_admin = request.user.is_superuser or getattr(getattr(request.user, "profile", None), "is_platform_admin", False)

    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    if not is_platform_admin and ticket.tenant != active_tenant:
        return JsonResponse({"status": "error", "message": "غير مصرح لك بتعديل حالة هذه التذكرة."}, status=403)

    post_data = request.POST
    if "application/json" in (request.content_type or "") and request.body:
        try:
            post_data = json.loads(request.body.decode("utf-8"))
        except Exception:
            post_data = request.POST

    new_status = post_data.get("status", "").strip().lower()
    valid_statuses = [s[0] for s in SupportTicket.STATUS_CHOICES]
    if new_status not in valid_statuses:
        return JsonResponse({"status": "error", "message": f"الحالة '{new_status}' غير صالحة."}, status=400)

    ticket.status = new_status
    if new_status == "resolved":
        ticket.resolved_at = timezone.now()
    elif new_status == "closed":
        ticket.closed_at = timezone.now()
    elif new_status in ("open", "in_progress"):
        ticket.resolved_at = None
        ticket.closed_at = None

    ticket.save()

    return JsonResponse({
        "status": "success",
        "ticket_id": ticket.id,
        "new_status": ticket.status,
        "new_status_display": ticket.get_status_display(),
    })
