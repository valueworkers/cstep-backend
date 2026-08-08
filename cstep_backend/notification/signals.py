from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from registrations.models import Registration

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
        notify(
            instance.user, NotificationType.REGISTRATION_CONFIRMED, [IN_APP, EMAIL],
            title="Registration confirmed",
            body=f"You're registered for {instance.event.title}.",
            event=instance.event,
        )
        return

    old_status = getattr(instance, "_old_status", None)
    if old_status is not None and old_status != instance.status:
        notify(
            instance.user, NotificationType.REGISTRATION_STATUS_UPDATE, [IN_APP, EMAIL],
            title="Registration status updated",
            body=f"Your registration for {instance.event.title} is now {instance.get_status_display()}.",
            event=instance.event,
        )