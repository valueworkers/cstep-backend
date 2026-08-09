from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "notification_type", "channel", "is_read", "created_at")
    list_filter = ("channel", "notification_type", "is_read")
    search_fields = ("user__email", "title", "body")
    readonly_fields = [f.name for f in Notification._meta.fields]
    ordering = ("-created_at",)

    # def has_add_permission(self, request):
    #     # Notifications are only ever created via services.notify(); the
    #     # admin is for inspection/debugging, not manual creation.
    #     return False