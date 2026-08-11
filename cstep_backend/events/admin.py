from django.contrib import admin

from .models import (
    Event,
    EventDay,
    ScheduleItem,
    BroadcastSession,
    ViewerSession,
    StreamRecording,
    Feedback,
    ChatMessage
)


class ScheduleItemInline(admin.TabularInline):
    model = ScheduleItem
    extra = 0
    fields = ("item_type", "title", "track", "room", "start_time", "end_time", "order", "speaker_name")
    ordering = ("track", "order", "start_time")
    show_change_link = True


class EventDayInline(admin.TabularInline):
    model = EventDay
    extra = 0
    fields = ("day_number", "date", "label", "allowed_attendance_modes")
    ordering = ("day_number",)
    show_change_link = True


class BroadcastSessionInline(admin.TabularInline):
    model = BroadcastSession
    extra = 0
    fields = ("name", "is_primary", "is_active", "is_recording", "stream_key", "started_at", "ended_at")
    readonly_fields = ("stream_key",)
    show_change_link = True


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "schedule_type", "scheduled_start", "scheduled_end", "created_by")
    list_filter = ("status", "schedule_type")
    search_fields = ("title", "description", "created_by__email")
    autocomplete_fields = ("created_by",)
    readonly_fields = ("created_at", "updated_at", "playback_url", "recording_url")
    date_hierarchy = "scheduled_start"
    actions = ["regenerate_days"]
    inlines = [EventDayInline, BroadcastSessionInline]

    @admin.action(description="Generate/sync EventDay rows from scheduled dates")
    def regenerate_days(self, request, queryset):
        for event in queryset:
            event.generate_days()


@admin.register(EventDay)
class EventDayAdmin(admin.ModelAdmin):
    list_display = ("id", "event", "day_number", "date", "label", "allowed_attendance_modes")
    list_filter = ("event",)
    search_fields = ("event__title", "label")
    autocomplete_fields = ("event",)
    ordering = ("event", "day_number")
    inlines = [ScheduleItemInline]


@admin.register(ScheduleItem)
class ScheduleItemAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "day", "item_type", "track", "room", "start_time", "end_time", "order")
    list_filter = ("item_type", "track", "day__event")
    search_fields = ("title", "speaker_name", "day__event__title")
    autocomplete_fields = ("day",)
    ordering = ("day", "track", "order", "start_time")
    actions = ["resequence_selected_days"]

    @admin.action(description="Resequence order for the day(s) of selected items")
    def resequence_selected_days(self, request, queryset):
        days = {item.day for item in queryset}
        for day in days:
            ScheduleItem.resequence(day)


@admin.register(BroadcastSession)
class BroadcastSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "event", "is_primary", "is_active", "is_recording", "started_at", "ended_at")
    list_filter = ("is_primary", "is_active", "is_recording")
    search_fields = ("name", "event__title", "stream_key")
    autocomplete_fields = ("event", "broadcaster")
    readonly_fields = ("stream_key", "created_at")


@admin.register(ViewerSession)
class ViewerSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "event", "state", "joined_at", "left_at", "watch_duration_seconds", "is_active_display")
    list_filter = ("event",)
    search_fields = ("user__email", "event__title", "ip_address", "state")
    autocomplete_fields = ("user", "event")
    readonly_fields = ("joined_at",)

    @admin.display(description="Active", boolean=True)
    def is_active_display(self, obj):
        return obj.is_active


@admin.register(StreamRecording)
class StreamRecordingAdmin(admin.ModelAdmin):
    list_display = ("id", "broadcast_session", "status", "started_by", "started_at", "ended_at")
    list_filter = ("status",)
    search_fields = ("broadcast_session__name", "broadcast_session__event__title")
    autocomplete_fields = ("broadcast_session", "started_by")
    readonly_fields = ("started_at",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "event", "target_display", "user", "rating", "is_overall_rating", "created_at")
    list_filter = ("is_overall_rating", "event")
    search_fields = ("event__title", "user__email", "comment")
    autocomplete_fields = ("event", "event_date", "schedule_item", "user")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Target")
    def target_display(self, obj):
        return "Overall" if obj.is_overall_rating else str(obj.schedule_item)

from django.contrib import admin
from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "sender",
        "message_preview",
        "status",
        "created_at",
        "edited_at",
    )

    list_filter = (
        "is_deleted",
        "event",
        "created_at",
    )

    search_fields = (
        "message",
        "sender__email",
        "sender__username",
        "event__title",
    )

    autocomplete_fields = (
        "event",
        "sender",
    )

    readonly_fields = (
        "created_at",
        "edited_at",
    )

    @admin.display(description="Message")
    def message_preview(self, obj):
        if len(obj.message) > 60:
            return f"{obj.message[:60]}..."
        return obj.message

    @admin.display(description="Status")
    def status(self, obj):
        if obj.is_deleted:
            return "Deleted"
        elif obj.edited_at:
            return "Edited"
        return "Active"