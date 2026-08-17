# events/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .webhooks import media_server_webhook

app_name = "events"

router = DefaultRouter()
router.register("event", views.EventViewSet, basename="event")
router.register("event", views.EventBroadcastViewSet, basename="event-broadcast")
router.register("event", views.EventViewerViewSet, basename="event-viewer")
router.register("broadcast-sessions", views.BroadcastSessionViewSet, basename="broadcast-session")
router.register("event-days", views.EventDayViewSet, basename="event-day")
router.register("recordings", views.StreamRecordingViewSet, basename="recording")
router.register("schedule-items", views.ScheduleItemViewSet, basename="schedule-item")
router.register("feedback", views.FeedbackViewSet, basename="feedback")
router.register("chat-messages", views.ChatMessageViewSet, basename="chat-message")

urlpatterns = [
    path("", include(router.urls)),
    path("webhooks/stream/", media_server_webhook, name="stream-webhook"),
]