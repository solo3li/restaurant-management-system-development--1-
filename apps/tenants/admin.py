from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import reverse
from .models import Tenant, Branch, DeliveryArea, PlatformConfiguration


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "subscription_plan",
        "subscription_status_badge",
        "billing_cycle",
        "subscription_end",
        "is_active",
        "branches_count",
        "enter_dashboard_button",
        "created_at",
    )
    list_filter = ("subscription_status", "billing_cycle", "subscription_plan", "is_active")
    search_fields = ("name", "slug", "phone", "email")
    prepopulated_fields = {"slug": ("name",)}

    fieldsets = (
        ("بيانات المنشأة الأساسية", {
            "fields": ("name", "slug", "logo_emoji", "phone", "email", "address", "is_active")
        }),
        ("الاشتراك والباقة", {
            "fields": ("subscription_plan", "subscription_status", "billing_cycle", "subscription_start", "subscription_end")
        }),
        ("العملة والخرائط (Google Maps & Localization)", {
            "fields": ("default_currency", "google_maps_api_key"),
            "description": "حدد العملة الافتراضية للمنشأة. كما يمكنك تخصيص مفتاح Google Maps خاص بهذه المنشأة فقط للاستفادة من رصيدها، أو تركه فارغاً لاستخدام المفتاح المركزي العام للمنصة."
        }),
        ("الكول سنتر الصوتي والذكاء الاصطناعي (Voice AI PBX)", {
            "fields": ("voice_is_active", "voice_client_id", "voice_username", "voice_password"),
            "classes": ("collapse",),
            "description": "بيانات الربط مع سنترال الذكاء الاصطناعي السحابي وخدمة الرد الآلي."
        }),
    )

    @admin.display(description="حالة الاشتراك")
    def subscription_status_badge(self, obj):
        if obj.subscription_status == "active":
            return mark_safe('<span style="color: #257a4e; font-weight: bold;">نشط ✓</span>')
        elif obj.subscription_status == "trial":
            return mark_safe('<span style="color: #1f6e7e; font-weight: bold;">تجريبي</span>')
        return format_html('<span style="color: #b53a2b; font-weight: bold;">{}</span>', obj.get_subscription_status_display())

    @admin.display(description="الفروع")
    def branches_count(self, obj):
        return obj.branches.count()

    @admin.display(description="لوحة التحكم")
    def enter_dashboard_button(self, obj):
        url = reverse("switch_tenant", args=[obj.id])
        return format_html(
            '<a href="{}" target="_blank" style="background-color: #2563eb; color: #ffffff; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px; text-decoration: none; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.1);">'
            'دخول المنشأة ↗'
            '</a>',
            url
        )


@admin.register(PlatformConfiguration)
class PlatformConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "has_google_key",
        "default_delivery_base_fee",
        "default_delivery_per_km_fee",
        "max_delivery_radius_km",
        "updated_at",
    )
    fieldsets = (
        ("تكامل خرائط وذكاء التوصيل (Google Maps Platform)", {
            "fields": ("google_maps_api_key",),
            "description": "ضع هنا مفتاح Google Maps API العام للمنصة للاستفادة من تحويل العناوين (Geocoding)، وقراءة معالم الأحياء والكومبوندات، وحساب مسافة ووقت القيادة اللحظي (Distance Matrix)، وتتبع روابط خرائط جوجل المرسلة على الواتساب."
        }),
        ("قواعد تسعير التوصيل الذكي (Dynamic Delivery Pricing)", {
            "fields": (
                "default_delivery_base_fee",
                "default_base_distance_km",
                "default_delivery_per_km_fee",
                "max_delivery_radius_km",
                "average_kitchen_prep_minutes",
            ),
            "description": "المعادلة المطبقة عندما يكون العنوان حراً وخارج الكومبوندات المحددة سلفاً: السعر = رسوم فتحة العداد + (المسافة الزائدة عن الكيلومترات الأساسية × سعر الكيلومتر الإضافي)."
        }),
    )

    def has_add_permission(self, request):
        return not PlatformConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(boolean=True, description="مفتاح Google مفعل")
    def has_google_key(self, obj):
        return bool(obj.google_maps_api_key and len(obj.google_maps_api_key.strip()) > 8)


@admin.register(DeliveryArea)
class DeliveryAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "area_type", "delivery_fee", "estimated_time_minutes", "is_active", "created_at")
    list_filter = ("branch__tenant", "branch", "area_type", "is_active")
    search_fields = ("name", "notes", "branch__name")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "city", "phone", "status", "created_at")
    list_filter = ("tenant", "status", "city")
    search_fields = ("name", "city", "phone")
