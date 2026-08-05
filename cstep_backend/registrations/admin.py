from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Registration,
    RegistrationDay,
    RegistrationSession,
    AccommodationAssistance,
    TravelAssistance,
    MedicalAssistance,
    TranslationAssistance,
)


class RegistrationDayInline(admin.TabularInline):
    model = RegistrationDay
    extra = 0
    fields = ("day", "attendance_mode", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("day",)
    show_change_link = True


class RegistrationSessionInline(admin.TabularInline):
    model = RegistrationSession
    extra = 0
    fields = ("session", "status", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("session",)
    show_change_link = True


class AccommodationAssistanceInline(admin.StackedInline):
    model = AccommodationAssistance
    extra = 0
    fields = (
        "hotel_name",
        "address",
        "room_no",
        ("from_date", "to_date"),
        "status",
    )


class TravelAssistanceInline(admin.TabularInline):
    model = TravelAssistance
    extra = 0
    fields = ("transport_mode", "source_location", "destination_location", "travel_date", "status")


class MedicalAssistanceInline(admin.StackedInline):
    model = MedicalAssistance
    extra = 0
    fields = ("medical_needs", "date", "status")


class TranslationAssistanceInline(admin.StackedInline):
    model = TranslationAssistance
    extra = 0
    fields = ("language", "date", "status")


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "event", "status", "day_count", "session_count", "created_at")
    list_filter = ("status", "event")
    search_fields = ("user__email", "user__first_name", "user__last_name", "event__title")
    autocomplete_fields = ("user", "event")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = ["mark_accepted", "mark_rejected", "mark_HOLD"]
    inlines = [
        RegistrationDayInline,
        RegistrationSessionInline,
        AccommodationAssistanceInline,
        TravelAssistanceInline,
        MedicalAssistanceInline,
        TranslationAssistanceInline,
    ]

    @admin.display(description="Days")
    def day_count(self, obj):
        return obj.days.count()

    @admin.display(description="Sessions")
    def session_count(self, obj):
        return obj.sessions.count()

    @admin.action(description="Mark selected registrations as ACCEPTED")
    def mark_accepted(self, request, queryset):
        self._bulk_status(queryset, "ACCEPTED")

    @admin.action(description="Mark selected registrations as REJECTED")
    def mark_rejected(self, request, queryset):
        self._bulk_status(queryset, "REJECTED")

    @admin.action(description="Mark selected registrations as HOLD")
    def mark_HOLD(self, request, queryset):
        self._bulk_status(queryset, "HOLD")

    def _bulk_status(self, queryset, status):
        for registration in queryset:
            registration.bulk_update_status(status)


@admin.register(RegistrationDay)
class RegistrationDayAdmin(admin.ModelAdmin):
    list_display = ("id", "registration", "day", "attendance_mode", "created_at")
    list_filter = ("attendance_mode", "day__event")
    search_fields = ("registration__user__email", "day__event__title")
    autocomplete_fields = ("registration", "day")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RegistrationSession)
class RegistrationSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "registration__user", "session", "status", "created_at")
    list_filter = ("status", "session__day__event", "registration__user")
    search_fields = ("registration__user__email", "session__title")
    autocomplete_fields = ("registration", "session")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccommodationAssistance)
class AccommodationAssistanceAdmin(admin.ModelAdmin):
    list_display = ("id", "registration", "hotel_name", "room_no", "from_date", "to_date", "status")
    list_filter = ("status",)
    search_fields = ("hotel_name", "registration__user__email")
    autocomplete_fields = ("registration",)


@admin.register(TravelAssistance)
class TravelAssistanceAdmin(admin.ModelAdmin):
    list_display = ("id", "registration", "transport_mode", "source_location", "destination_location", "travel_date", "status")
    list_filter = ("transport_mode", "status")
    search_fields = ("registration__user__email", "source_location", "destination_location")
    autocomplete_fields = ("registration",)


@admin.register(MedicalAssistance)
class MedicalAssistanceAdmin(admin.ModelAdmin):
    list_display = ("id", "registration", "date", "status")
    list_filter = ("status",)
    search_fields = ("registration__user__email",)
    autocomplete_fields = ("registration",)


@admin.register(TranslationAssistance)
class TranslationAssistanceAdmin(admin.ModelAdmin):
    list_display = ("id", "registration", "language", "date", "status")
    list_filter = ("language", "status")
    search_fields = ("registration__user__email",)
    autocomplete_fields = ("registration",)