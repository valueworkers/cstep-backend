# tasks.py
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from events.models import Event
from registrations.constants import RegistrationStatus
from registrations.models import Registration

from .constants import NotificationChannel, NotificationType
from .models import Notification
from .services import notify

# How often generate_event_reminders is expected to run via Celery beat.
# Keep this <= the smallest gap between entries in REMINDER_OFFSETS_MINUTES.
REMINDER_CHECK_WINDOW_MINUTES = 15

# (minutes_before_event_start, human label). Label doubles as the dedupe key
# (see generate_event_reminders) and gets baked into the notification title.
REMINDER_OFFSETS_MINUTES = [
    (24 * 60, "24 hours before"),
    (60, "1 hour before"),
]

REMINDER_CHANNELS = [NotificationChannel.EMAIL, NotificationChannel.IN_APP]


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_async(self, user_id, notification_type, channels, title="", body="", event_id=None):
    """
    Async wrapper around services.notify(). Creates + delivers the
    Notification row(s) inside the worker instead of blocking the caller
    (e.g. call this from a view or signal instead of notify() directly
    when you don't want to eat SMTP/SMS latency inline).
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return

    event = None
    if event_id is not None:
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist:
            pass

    try:
        notify(user, notification_type, channels, title=title, body=body, event=event)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def generate_event_reminders():
    """
    Run every REMINDER_CHECK_WINDOW_MINUTES via Celery beat. For each
    upcoming Event and each hardcoded offset in REMINDER_OFFSETS_MINUTES,
    fires an EVENT_REMINDER notification to every ACCEPTED registrant
    whose reminder window is currently open.

    Dedup: Notification no longer carries a reminder-tracking row, so we
    key on (user, event, notification_type, title) - the title bakes in
    the offset label so the 24h and 1h reminders never collide with each
    other, and an existing row with that exact title means it already went out.
    """
    now = timezone.now()
    window = timedelta(minutes=REMINDER_CHECK_WINDOW_MINUTES)

    events = Event.objects.filter(scheduled_start__gte=now)

    for event in events:
        for offset_minutes, label in REMINDER_OFFSETS_MINUTES:
            fire_at = event.scheduled_start - timedelta(minutes=offset_minutes)
            if not (fire_at <= now < fire_at + window):
                continue

            title = f"Event Reminder ({label})"
            registrations = Registration.objects.filter(
                event=event, status=RegistrationStatus.ACCEPTED
            ).select_related("user")

            # One query for the whole event/offset instead of one exists()
            # check per registrant (same N+1 pattern already fixed elsewhere
            # in the registrations app via bulk_create/bulk_update).
            already_notified_user_ids = set(
                Notification.objects.filter(
                    event=event,
                    notification_type=NotificationType.EVENT_REMINDER,
                    title=title,
                ).values_list("user_id", flat=True)
            )

            body = (
                f'Reminder: "{event.title}" starts '
                f"{label.replace(' before', '')} — "
                f"{event.scheduled_start.strftime('%b %d, %Y %I:%M %p')}."
            )

            for reg in registrations:
                if reg.user_id in already_notified_user_ids:
                    continue

                # Fan out to the queue instead of calling notify() inline here:
                # notify() hits SMTP/SMS synchronously, and this task is
                # already running once per beat tick for potentially every
                # registrant of every upcoming event — inlining it would
                # block the beat task's worker slot for however long
                # send_mail/Fast2SMS takes, per registrant.
                send_notification_async.delay(
                    reg.user_id,
                    NotificationType.EVENT_REMINDER,
                    REMINDER_CHANNELS,
                    title=title,
                    body=body,
                    event_id=event.id,
                )

