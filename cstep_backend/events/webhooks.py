import hashlib
import hmac
import logging

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from events.constants import RecordingStatus

from .models import Event, EventStatus, BroadcastSession, ViewerSession
from .serializers import StreamWebhookSerializer
from .utils import _handle_stream_started, _handle_stream_ended, _handle_stream_error,_handle_recording_ready, _send_ws_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_webhook_signature(request) -> bool:
    """
    Verify HMAC-SHA256 signature sent by the media server.
    Media server must set: X-Webhook-Signature: sha256=<hex_digest>

    Set MEDIA_SERVER_WEBHOOK_SECRET in settings.py.
    Skip verification in DEBUG mode (for local testing).
    """
    if settings.DEBUG:
        return True

    secret = getattr(settings, "MEDIA_SERVER_WEBHOOK_SECRET", None)
    if not secret:
        logger.warning("MEDIA_SERVER_WEBHOOK_SECRET not configured — rejecting webhook.")
        return False

    signature_header = request.META.get("HTTP_X_WEBHOOK_SIGNATURE", "")
    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        key=secret.encode(),
        msg=request.body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    received = signature_header[7:]

    return hmac.compare_digest(expected, received)


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def media_server_webhook(request):
    """
    POST /webhooks/stream/

    Called by your media server (nginx-rtmp, LiveKit, Agora, etc.)
    when a stream starts, ends, or errors.

    Expected payload:
    {
        "action": "stream.started" | "stream.ended" | "stream.error",
        "stream_key": "<key>",
        "playback_url": "https://cdn.example.com/live/stream.m3u8",  # on started
        "timestamp": "2024-01-01T12:00:00Z"
    }
    """
    if not _verify_webhook_signature(request):
        logger.warning("Webhook signature verification failed. IP: %s", request.META.get("REMOTE_ADDR"))
        return Response({"detail": "Invalid signature."}, status=status.HTTP_401_UNAUTHORIZED)

    serializer = StreamWebhookSerializer(data=request.data)
    if not serializer.is_valid():
        logger.error("Invalid webhook payload: %s", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    action = serializer.validated_data["action"]
    bs: BroadcastSession = serializer.broadcast_session
    event: Event = bs.event

    logger.info("Webhook received: action=%s event_id=%s", action, event.id)

    if action == "stream.started":
        _handle_stream_started(bs, event, serializer.validated_data)

    elif action == "stream.ended":
        _handle_stream_ended(bs, event)

    elif action == "stream.error":
        _handle_stream_error(bs, event)
        
    elif action == "recording.ready":
        recording = bs.recordings.filter(status=RecordingStatus.PROCESSING).order_by("-started_at").first()
        if not recording:
            logger.warning("recording.ready webhook for session %s but no PROCESSING recording found.", bs.id)
            return Response({"detail": "No matching recording."}, status=status.HTTP_400_BAD_REQUEST)
        file_url = serializer.validated_data.get("file_url", "")
        _handle_recording_ready(recording, file_url)

    return Response({"status": "ok"})

