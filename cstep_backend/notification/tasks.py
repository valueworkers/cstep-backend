from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from events.constants import ScheduleItemType
from events.models import Event, ScheduleItem
from registrations.constants import RegistrationStatus
from registrations.models import Registration, RegistrationSession

from .constants import (
    DeliveryStatus,
    NotificationChannel,
    REMINDER_CHECK_WINDOW_MINUTES,
    ReminderTarget,
)
from .models import Notification, ReminderRule, ScheduledReminder
from .services import NotificationService


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification(self, notification_id):
    """Delivers a single Notification row over its channel. Idempotent."""
    try:
        notification = Notification.objects.select_related("user").get(pk=notification_id)
    except Notification.DoesNotExist:
        return

    if notification.status == DeliveryStatus.SENT:
        return

    try:
        if notification.channel == NotificationChannel.EMAIL:
            _send_email(notification)
        elif notification.channel == NotificationChannel.SMS:
            _send_sms(notification)
        # IN_APP has nothing further to do — the row itself *is* the delivery.

        notification.status = DeliveryStatus.SENT
        notification.sent_at = timezone.now()
        notification.save(update_fields=["status", "sent_at", "updated_at"])

    except Exception as exc:
        notification.status = DeliveryStatus.FAILED
        notification.error_message = str(exc)[:500]
        notification.retry_count += 1
        notification.save(update_fields=["status", "error_message", "retry_count", "updated_at"])
        raise self.retry(exc=exc)


def _send_email(notification):
    from django.core.mail import send_mail

    if not notification.user.email:
        raise ValueError("User has no email address on file.")
    send_mail(
        subject=notification.title or notification.notification_type,
        message=notification.body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[notification.user.email],
        fail_silently=False,
    )


def _send_sms(notification):
    from .sms import send_sms  # raises sms.Fast2SMSError on failure

    user = notification.user
    if not user.phone_number:
        raise ValueError("User has no phone number on file.")
    send_sms(to=f"{user.country_code}{user.phone_number}", message=notification.body)


@shared_task
def generate_reminders():
    """
    Run every REMINDER_CHECK_WINDOW_MINUTES (or more often) via Celery
    beat. Evaluates active ReminderRules against upcoming Event/ScheduleItem
    start times and queues reminder notifications for registered users.
    ScheduledReminder rows make this safe to run repeatedly / on overlapping
    windows without double-sending.
    """
    now = timezone.now()
    rules = ReminderRule.objects.filter(is_active=True).select_related("event")

    for rule in rules:
        for target, user, context in _resolve_targets(rule, now):
            _fire_once(rule, target, user, context)


def _fire_once(rule, target, user, context):
    content_type = ContentType.objects.get_for_model(target)
    already_sent = ScheduledReminder.objects.filter(
        reminder_rule=rule, user=user, content_type=content_type, object_id=target.pk
    ).exists()
    if already_sent:
        return

    with transaction.atomic():
        # Row-level lock via get_or_create prevents two concurrent beat
        # runs from both winning the dedup check and double-sending.
        _, created = ScheduledReminder.objects.get_or_create(
            reminder_rule=rule, user=user, content_type=content_type, object_id=target.pk,
        )
        if not created:
            return
        notifications = NotificationService.notify(
            user, rule.notification_type, rule.channels,
            context=context, event=rule.event, related_object=target,
        )
        if notifications:
            ScheduledReminder.objects.filter(
                reminder_rule=rule, user=user, content_type=content_type, object_id=target.pk,
            ).update(notification=notifications[0])


def _resolve_targets(rule, now):
    """Yields (target_obj, user, context) whose reminder window is open now."""
    window = timedelta(minutes=REMINDER_CHECK_WINDOW_MINUTES)

    if rule.applies_to == ReminderTarget.EVENT:
        event = rule.event
        if not event.scheduled_start:
            return
        fire_at = event.scheduled_start - timedelta(minutes=rule.offset_minutes_before)
        if not (fire_at <= now < fire_at + window):
            return
        registrations = Registration.objects.filter(
            event=event, status=RegistrationStatus.ACCEPTED
        ).select_related("user")
        for reg in registrations:
            yield event, reg.user, {
                "event_title": event.title,
                "start_time": event.scheduled_start.isoformat(),
            }

    elif rule.applies_to == ReminderTarget.SCHEDULE_ITEM:
        items = ScheduleItem.objects.filter(
            day__event=rule.event, item_type=ScheduleItemType.SESSION
        ).select_related("day")
        for item in items:
            start_dt = datetime.combine(item.day.date, item.start_time)
            if timezone.is_naive(start_dt):
                start_dt = timezone.make_aware(start_dt)
            fire_at = start_dt - timedelta(minutes=rule.offset_minutes_before)
            if not (fire_at <= now < fire_at + window):
                continue
            registrations = RegistrationSession.objects.filter(
                session=item, status=RegistrationStatus.ACCEPTED
            ).select_related("registration__user")
            for rs in registrations:
                yield item, rs.registration.user, {
                    "session_title": item.title,
                    "start_time": start_dt.isoformat(),
                    "room": item.room,
                }