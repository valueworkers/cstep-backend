import json
import logging
from channels.exceptions import DenyConnection
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


class EventStreamConsumer(AsyncWebsocketConsumer):
    """
    WebSocket endpoint: ws://host/ws/events/{event_id}/

    Each connected client joins the group "event_{event_id}".
    The server pushes stream lifecycle events (started, ended, viewer counts).
    The client can send heartbeat pings.

    Authentication: JWT token passed as query param ?token=<jwt>
    (or via cookie if using session auth).
    """

    async def connect(self):
        self.event_id = self.scope["url_route"]["kwargs"]["event_id"]
        self.group_name = f"event_{self.event_id}"
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            raise DenyConnection("Authentication required")

        event = await self._get_event(self.event_id)
        if not event:
            raise DenyConnection("Event not found")

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send current stream state immediately on connect
        await self.send(text_data=json.dumps({
            "type": "stream.state",
            "status": event.status,
            "broadcast_sessions": await self._get_broadcast_sessions(self.event_id),
            "concurrent_viewers": await self._get_concurrent_viewers(self.event_id),
            "video_muted_by_default": event.video_muted_by_default,
        }))

        logger.info("WS connected: user=%s event=%s", self.user.id, self.event_id)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info("WS disconnected: user=%s event=%s code=%s", self.user.id if self.user else "?", self.event_id, close_code)

    async def receive(self, text_data=None, bytes_data=None):
        """Handle messages from the client."""
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")

        if msg_type == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))

        elif msg_type == "heartbeat":
            # Client is still watching — update ViewerSession
            await self._update_heartbeat(self.user.id, self.event_id)
            await self.send(text_data=json.dumps({"type": "heartbeat.ack"}))

    # ------------------------------------------------------------------
    # Group message handlers (called by channel layer)
    # ------------------------------------------------------------------

    async def event_broadcast(self, message):
        """
        Receives messages sent via:
            layer.group_send(f"event_{id}", {"type": "event.broadcast", "payload": {...}})
        Channels converts "event.broadcast" → "event_broadcast" handler.
        """
        await self.send(text_data=json.dumps(message["payload"]))

    # ------------------------------------------------------------------
    # DB helpers (sync → async)
    # ------------------------------------------------------------------

    @database_sync_to_async
    def _get_event(self, event_id):
        from .models import Event
        try:
            return Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return None

    @database_sync_to_async
    def _get_concurrent_viewers(self, event_id):
        from .models import ViewerSession
        return ViewerSession.objects.filter(event_id=event_id, left_at=None).count()

    @database_sync_to_async
    def _get_broadcast_sessions(self, event_id):
        from .models import BroadcastSession
        sessions = list(
            BroadcastSession.objects.filter(event_id=event_id).values(
                "id", "name", "is_primary", "is_active", "playback_url",
                "started_at", "ended_at",
                "is_recording", "allow_viewer_recording",   # add
            )
        )
        for session in sessions:
            for key in ("started_at", "ended_at"):
                if session[key]:
                    session[key] = session[key].isoformat()
        return sessions
    
    @database_sync_to_async
    def _update_heartbeat(self, user_id, event_id):
        from .models import ViewerSession
        now = timezone.now()
        session = ViewerSession.objects.filter(
            user_id=user_id, event_id=event_id, left_at=None
        ).first()
        if session:
            if session.last_heartbeat:
                elapsed = int((now - session.last_heartbeat).total_seconds())
                session.watch_duration_seconds += min(elapsed, 60)
            session.last_heartbeat = now
            session.save(update_fields=["last_heartbeat", "watch_duration_seconds"])
