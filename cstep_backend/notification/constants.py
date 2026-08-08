from django.db import models


class NotificationChannel(models.TextChoices):
    IN_APP = "IN_APP", "In-App"
    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "SMS"


class NotificationType(models.TextChoices):
    REGISTRATION_CONFIRMED = "REGISTRATION_CONFIRMED", "Registration Confirmed"
    REGISTRATION_STATUS_UPDATE = "REGISTRATION_STATUS_UPDATE", "Registration Status Update"
    ASSISTANCE_STATUS_UPDATE = "ASSISTANCE_STATUS_UPDATE", "Assistance Status Update"
    EVENT_REMINDER = "EVENT_REMINDER", "Event Reminder"
    BROADCAST_LIVE = "BROADCAST_LIVE", "Broadcast Went Live"
    GENERAL = "GENERAL", "General Announcement"