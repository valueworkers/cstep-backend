import logging

from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from events.models import Event
from events.constants import EventStatus
from .services import LiveAnalyticsService
from .registry import get_active_event_ids

logger = logging.getLogger(__name__)


@shared_task
def push_live_analytics():
    channel_layer = get_channel_layer()
    active_ids = get_active_event_ids()

    events_qs = Event.objects.filter(status=EventStatus.LIVE)
    if active_ids is not None:
        events_qs = events_qs.filter(id__in=active_ids)
    # else: registry read failed — fall back to all live events rather than
    # silently going quiet for every event.

    for event in events_qs:
        try:
            payload = LiveAnalyticsService(event).build_payload(visuals=None)
        except Exception:
            logger.exception("push_live_analytics: failed building payload for event %s", event.id)
            continue

        try:
            async_to_sync(channel_layer.group_send)(
                f"live_analytics_{event.id}",
                {"type": "analytics.update", "data": payload},
            )
        except Exception:
            logger.exception("push_live_analytics: failed broadcasting for event %s", event.id)