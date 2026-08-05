import logging
from django.utils import timezone
from .models import Event, EventStatus, BroadcastSession, ViewerSession

logger = logging.getLogger(__name__)

def _get_peak_viewers(event):
    """Approximation — count of sessions ever opened. For a true concurrent
    peak you'd need periodic snapshots via a scheduled task."""
    return event.viewer_sessions.count()


def _send_ws_event(event_id: int, payload: dict):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(
                f"event_{event_id}",
                {"type": "event.broadcast", "payload": payload},
            )
    except ImportError:
        pass


def _handle_stream_started(bs: BroadcastSession, event: Event, data: dict):
    now = data.get("timestamp") or timezone.now()

    bs.is_active = True
    bs.started_at = now
    bs.save(update_fields=["is_active", "started_at"])

    event.status = EventStatus.LIVE
    event.stream_start_time = now
    event.playback_url = event.primary_broadcast_session.playback_url
    event.save(update_fields=["status", "stream_start_time", "playback_url", "updated_at"])

    _send_ws_event(
        event.id,
        {
            "type": "stream.started",
            "camera_id": bs.id,
            "camera_name": bs.name,
            "playback_urls": list(event.broadcast_sessions.values_list("playback_url", flat=True)),
        },
    )
    logger.info("Event %s camera %s went LIVE via webhook.", event.id, bs.id)


def _handle_stream_ended(bs: BroadcastSession, event: Event):
    now = timezone.now()

    bs.is_active = False
    bs.ended_at = now
    bs.save(update_fields=["is_active", "ended_at"])

    if not event.broadcast_sessions.filter(is_active=True).exists():
        event.status = EventStatus.ENDED
        event.stream_end_time = now
        event.save(update_fields=["status", "stream_end_time", "updated_at"])

        ViewerSession.objects.filter(event=event, left_at=None).update(left_at=now)
        # from analytics.broadcast import push_live_analytics
        # push_live_analytics(event.id)

        _send_ws_event(event.id, {"type": "stream.ended", "camera_id": bs.id, "camera_name": bs.name})
        logger.info("Event %s ENDED via webhook.", event.id)
    else:
        _send_ws_event(event.id, {"type": "camera.ended", "camera_id": bs.id, "camera_name": bs.name})
        logger.info("Event %s camera %s ENDED via webhook.", event.id, bs.id)


def _handle_stream_error(bs: BroadcastSession, event: Event):
    logger.error("Stream error reported for event %s.", event.id)
    bs.is_active = False
    bs.save(update_fields=["is_active"])

    _send_ws_event(event.id, {
        "type": "stream.error",
        "camera_id": bs.id,
        "camera_name": bs.name,
        "message": "The stream encountered an error. Please try again.",
    })

def _handle_recording_ready(recording, file_url: str):
    from .constants import RecordingStatus  # adjust import path to wherever it actually lives

    recording.file_url = file_url
    recording.status = RecordingStatus.READY
    recording.save(update_fields=["file_url", "status"])

    event = recording.broadcast_session.event
    _send_ws_event(
        event.id,
        {
            "type": "recording.ready",
            "recording_id": recording.id,
            "broadcast_session_id": recording.broadcast_session_id,
            "file_url": file_url,
        },
    )
    logger.info("Recording %s for session %s is READY.", recording.id, recording.broadcast_session_id)
