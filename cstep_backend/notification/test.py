"""
Run with: python manage.py test notification

Uses Django's built-in test runner (unittest-style), not pytest — so
DJANGO_SETTINGS_MODULE is picked up automatically from manage.py, no
pytest.ini needed.

Adjust the User/Event/Registration creation calls below to match your real
required fields — these use minimal kwargs since no factory module was
provided. If accounts.models.User requires phone_number/country_code etc.
at creation time, add them here.
"""
from datetime import timedelta
from unittest.mock import patch

from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from notification.consumers import NotificationConsumer
from notification.constants import NotificationChannel, NotificationType
from notification.models import Notification
from notification.services import notify
from notification.tasks import generate_event_reminders

User = get_user_model()


def make_user(email="test@example.com", phone_number="9876543210"):
    """
    Your UserManager.create_user() requires phone_number positionally.
    If your User model has other required fields (country_code, role, etc.)
    that don't have defaults, add them here too — check accounts/models.py's
    UserManager.create_user signature for the full list.
    """
    return User.objects.create_user(
        email=email, phone_number=phone_number, password="pass1234",
    )


# ---------------------------------------------------------------------------
# services.notify() — the actual bug that was fixed (EMAIL/SMS never sent)
# ---------------------------------------------------------------------------

class NotifyServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_notify_creates_one_row_per_channel(self):
        created = notify(
            self.user, NotificationType.GENERAL,
            [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
            title="Hi", body="Body",
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 2)

    def test_email_channel_actually_calls_send_mail(self):
        """Regression test: _send_email was previously commented out."""
        with patch("notification.services._send_email") as mock_send:
            notify(self.user, NotificationType.GENERAL, [NotificationChannel.EMAIL],
                   title="Hi", body="Body")
        mock_send.assert_called_once()

    def test_sms_channel_actually_calls_send_sms(self):
        """Regression test: _send_sms was previously commented out."""
        with patch("notification.services._send_sms") as mock_send:
            notify(self.user, NotificationType.GENERAL, [NotificationChannel.SMS],
                   title="Hi", body="Body")
        mock_send.assert_called_once()

    def test_bad_channel_does_not_break_the_others(self):
        with patch("notification.services._send_sms", side_effect=Exception("boom")):
            created = notify(
                self.user, NotificationType.GENERAL,
                [NotificationChannel.SMS, NotificationChannel.IN_APP],
                title="Hi", body="Body",
            )
        self.assertEqual(len(created), 2)  # both rows created despite SMS failure


# ---------------------------------------------------------------------------
# signals.py -> tasks.send_notification_async
# ---------------------------------------------------------------------------

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RegistrationSignalTests(TestCase):
    def test_registration_created_fires_notification(self):
        from events.models import Event
        from registrations.models import Registration

        user = make_user()
        event = Event.objects.create(title="Conf", scheduled_start=timezone.now() + timedelta(days=5))
        Registration.objects.create(user=user, event=event)

        self.assertTrue(
            Notification.objects.filter(
                user=user, notification_type=NotificationType.REGISTRATION_CONFIRMED
            ).exists()
        )


# ---------------------------------------------------------------------------
# consumers.py — WebSocket push
#
# TransactionTestCase (not TestCase) is required here: the consumer runs in
# a separate thread/event loop, and TestCase's default wrap-everything-in-
# one-atomic-transaction behaviour isn't visible across threads, so a plain
# TestCase will intermittently show "row not found" here.
#
# Also overrides CHANNEL_LAYERS to the in-memory backend so this doesn't
# need a real Redis instance running just to execute tests.
# ---------------------------------------------------------------------------

@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class NotificationConsumerTests(TransactionTestCase):
    """
    Django's test runner supports `async def test_...` methods directly
    (since Django 4.1) — no manual async_to_sync wrapping needed here.
    """

    async def test_websocket_receives_pushed_notification(self):
        from channels.db import database_sync_to_async

        user = await database_sync_to_async(make_user)(email="wstest@example.com")

        communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        communicator.scope["user"] = user  # bypass JWT middleware directly in the test

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        snapshot = await communicator.receive_json_from()
        self.assertEqual(snapshot["type"], "unread_count")

        await database_sync_to_async(notify)(
            user, NotificationType.GENERAL, [NotificationChannel.IN_APP],
            title="Push test", body="Body",
        )

        pushed = await communicator.receive_json_from(timeout=2)
        self.assertEqual(pushed["type"], "notification")
        self.assertEqual(pushed["notification"]["title"], "Push test")

        await communicator.disconnect()

    async def test_websocket_rejects_anonymous(self):
        communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)


# ---------------------------------------------------------------------------
# tasks.generate_event_reminders — dedupe behaviour
# ---------------------------------------------------------------------------

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ReminderTaskTests(TestCase):
    def test_reminder_task_dedupes_on_second_run(self):
        from events.models import Event
        from registrations.constants import RegistrationStatus
        from registrations.models import Registration

        user = make_user()
        event = Event.objects.create(
            title="Conf",
            scheduled_start=timezone.now() + timedelta(minutes=59),  # inside "1 hour before" window
        )
        Registration.objects.create(user=user, event=event, status=RegistrationStatus.ACCEPTED)

        generate_event_reminders()
        first_count = Notification.objects.filter(
            user=user, notification_type=NotificationType.EVENT_REMINDER
        ).count()

        generate_event_reminders()  # immediate second run should not duplicate
        second_count = Notification.objects.filter(
            user=user, notification_type=NotificationType.EVENT_REMINDER
        ).count()

        self.assertGreater(first_count, 0)
        self.assertEqual(second_count, first_count)


# ---------------------------------------------------------------------------
# views.py — REST endpoints
# ---------------------------------------------------------------------------

class NotificationViewSetTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_unread_count_endpoint(self):
        Notification.objects.create(
            user=self.user, notification_type=NotificationType.GENERAL,
            channel=NotificationChannel.IN_APP, body="x",
        )
        response = self.client.get("/api/notifications/unread-count/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unread_count"], 1)

    def test_mark_read_endpoint(self):
        n = Notification.objects.create(
            user=self.user, notification_type=NotificationType.GENERAL,
            channel=NotificationChannel.IN_APP, body="x",
        )
        response = self.client.post(f"/api/notifications/{n.id}/read/")
        n.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(n.is_read)

    def test_read_all_endpoint(self):
        Notification.objects.create(
            user=self.user, notification_type=NotificationType.GENERAL,
            channel=NotificationChannel.IN_APP, body="x",
        )
        Notification.objects.create(
            user=self.user, notification_type=NotificationType.GENERAL,
            channel=NotificationChannel.IN_APP, body="y",
        )
        response = self.client.post("/api/notifications/read-all/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["marked_read"], 2)