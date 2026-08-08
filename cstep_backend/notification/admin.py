from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "channel", "is_read", "event", "created_at")
    list_filter = ("channel", "is_read", "notification_type")
    search_fields = ("user__email", "title", "body")