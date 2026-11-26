from django.contrib import admin

from .models import (
    BlacklistEntry,
    ParkingEvent,
    ParkingSession,
    ParkingTariff,
    UserNotification,
    VehiclePlate,
)


@admin.register(VehiclePlate)
class VehiclePlateAdmin(admin.ModelAdmin):
    list_display = ("plate_number", "owner", "is_active", "created_at", "is_blacklisted")
    search_fields = ("plate_number", "owner__username", "owner__email")
    list_filter = ("is_active", "created_at")
    list_editable = ("is_active",)

    @admin.display(boolean=True, description="У чорному списку")
    def is_blacklisted(self, obj):
        return hasattr(obj, "blacklist_entry")


@admin.register(ParkingTariff)
class ParkingTariffAdmin(admin.ModelAdmin):
    list_display = ("name", "hourly_rate", "alert_limit", "is_active", "updated_at")
    list_editable = ("hourly_rate", "alert_limit", "is_active")


@admin.register(BlacklistEntry)
class BlacklistEntryAdmin(admin.ModelAdmin):
    list_display = ("plate", "reason", "created_by", "created_at")
    search_fields = ("plate__plate_number", "reason")
    autocomplete_fields = ("plate",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ParkingSession)
class ParkingSessionAdmin(admin.ModelAdmin):
    list_display = ("plate", "entry_at", "exit_at", "hourly_rate")
    list_filter = ("entry_at", "exit_at")
    search_fields = ("plate__plate_number",)
    readonly_fields = ("entry_at",)


@admin.register(ParkingEvent)
class ParkingEventAdmin(admin.ModelAdmin):
    list_display = ("plate_text", "event_type", "actor", "confidence", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("plate_text",)
    readonly_fields = tuple(field.name for field in ParkingEvent._meta.fields)


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "created_at", "read_at")
    list_filter = ("created_at", "read_at")
    search_fields = ("user__username", "message")
