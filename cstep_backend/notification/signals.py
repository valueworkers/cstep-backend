from django.db.models.signals import post_save, pre_save
from django.db import transaction
from django.dispatch import receiver

from registrations.models import Registration
from .tasks import send_notification_async

from .constants import NotificationChannel, NotificationType
from .services import notify

IN_APP = NotificationChannel.IN_APP
EMAIL = NotificationChannel.EMAIL


@receiver(pre_save, sender=Registration)
def _stash_old_status(sender, instance, **kwargs):
    instance._old_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk else None
    )

@receiver(post_save, sender=Registration)
def _notify_registration(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(lambda: send_notification_async.delay(
            instance.user_id, NotificationType.REGISTRATION_CONFIRMED,
            [IN_APP, EMAIL],
            title="Registration confirmed",
            body=f"You're registered for {instance.event.title}.",
            event_id=instance.event_id,
        ))
        return

    old_status = getattr(instance, "_old_status", None)
    if old_status is not None and old_status != instance.status:
        transaction.on_commit(lambda: send_notification_async.delay(
            instance.user_id, NotificationType.REGISTRATION_STATUS_UPDATE,
            [IN_APP, EMAIL],
            title="Registration status updated",
            body=f"Your registration for {instance.event.title} is now {instance.get_status_display()}.",
            event_id=instance.event_id,
        ))