import logging

from django.conf import settings

from .constants import NotificationChannel
from .models import Notification

logger = logging.getLogger(__name__)


def notify(user, notification_type, channels, title="", body="", event=None):
    """
    Creates a Notification row per channel and delivers it immediately —
    no task queue. Email/SMS failures are logged, not raised, so one bad
    channel (e.g. missing phone number) never breaks the request/signal
    that triggered this call.
    """
    created = []
    for channel in channels:
        notification = Notification.objects.create(
            user=user, event=event, notification_type=notification_type,
            channel=channel, title=title, body=body,
        )
        _deliver(notification)
        created.append(notification)
    return created


def _deliver(notification):
    try:
        if notification.channel == NotificationChannel.EMAIL:
            _send_email(notification)
        elif notification.channel == NotificationChannel.SMS:
            _send_sms(notification)
        elif notification.channel == NotificationChannel.IN_APP:
            _push_in_app(notification)
    except Exception:
        logger.exception("Failed to deliver notification %s", notification.pk)


def _send_email(notification):
    from django.core.mail import send_mail

    if not notification.user.email:
        return
    send_mail(
        subject=notification.title or notification.notification_type,
        message=notification.body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[notification.user.email],
        fail_silently=False,
    )


def _send_sms(notification):
    from .sms import send_sms

    user = notification.user
    if not user.phone_number:
        return
    send_sms(to=f"{user.country_code}{user.phone_number}", message=notification.body)


def _push_in_app(notification):
    """Push over the websocket group; a no-op if Channels isn't set up."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        f"notifications_user_{notification.user_id}",
        {
            "type": "notification_message",
            "notification": {
                "id": notification.id,
                "notification_type": notification.notification_type,
                "title": notification.title,
                "body": notification.body,
                "created_at": notification.created_at.isoformat(),
            },
        },
    )