from django.conf import settings
from django.db import models

from .constants import NotificationChannel, NotificationType


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.ForeignKey(
        "events.Event", on_delete=models.CASCADE, related_name="notifications", null=True, blank=True
    )
    notification_type = models.CharField(max_length=40, choices=NotificationType.choices)
    channel = models.CharField(max_length=10, choices=NotificationChannel.choices)

    title = models.CharField(max_length=255, blank=True)
    body = models.TextField()

    is_read = models.BooleanField(default=False)  # IN_APP only
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "channel", "is_read"]),
            models.Index(fields=["event", "notification_type", "title"]),
        ]

    def mark_read(self):
        if self.channel == NotificationChannel.IN_APP and not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read"])

    def __str__(self):
        return f"{self.notification_type} -> {self.user} [{self.channel}]"