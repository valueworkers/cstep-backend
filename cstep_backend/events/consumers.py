from datetime import timedelta
from channels.exceptions import DenyConnection
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .permissions import MODERATOR_ROLES
from .models import Event, ChatMessage
from .constants import ChatReactionType, MIN_SECONDS_BETWEEN_MESSAGES, MAX_MESSAGE_LENGTH, EDIT_WINDOW_SECONDS, DELETE_WINDOW_SECONDS
from .chat_redis import increment_reaction, get_reaction_counts

from .serializers import ChatMessageSerializer

import logging

logger = logging.getLogger(__name__)


class EventStreamConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket endpoint:
        ws://host/ws/events/<event_id>/

    Uses JSON automatically.
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

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

        # Send current stream state
        await self.send_json({
            "type": "stream.state",
            "status": event.status,
            "broadcast_sessions": await self._get_broadcast_sessions(self.event_id),
            "concurrent_viewers": await self._get_concurrent_viewers(self.event_id),
            "video_muted_by_default": event.video_muted_by_default,
        })

        logger.info(
            "WS connected: user=%s event=%s",
            self.user.id,
            self.event_id,
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name,
        )

        logger.info(
            "WS disconnected: user=%s event=%s code=%s",
            getattr(self.user, "id", "?"),
            self.event_id,
            close_code,
        )

    async def receive_json(self, content, **kwargs):
        """
        Handles JSON received from the client.
        """

        msg_type = content.get("type")

        if msg_type == "ping":
            await self.send_json({
                "type": "pong"
            })

        elif msg_type == "heartbeat":
            await self._update_heartbeat(
                self.user.id,
                self.event_id,
            )

            await self.send_json({
                "type": "heartbeat.ack"
            })

    # ---------------------------------------------------------
    # Group Events
    # ---------------------------------------------------------

    async def event_broadcast(self, event):
        """
        group_send(
            "event_1",
            {
                "type": "event.broadcast",
                "payload": {...}
            }
        )
        """
        await self.send_json(event["payload"])

    # ---------------------------------------------------------
    # Database Helpers
    # ---------------------------------------------------------

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

        return ViewerSession.objects.filter(
            event_id=event_id,
            left_at=None,
        ).count()

    @database_sync_to_async
    def _get_broadcast_sessions(self, event_id):
        from .models import BroadcastSession

        sessions = list(
            BroadcastSession.objects.filter(
                event_id=event_id
            ).values(
                "id",
                "name",
                "is_primary",
                "is_active",
                "playback_url",
                "started_at",
                "ended_at",
                "is_recording",
                "allow_viewer_recording",
            )
        )

        for session in sessions:
            if session["started_at"]:
                session["started_at"] = session["started_at"].isoformat()

            if session["ended_at"]:
                session["ended_at"] = session["ended_at"].isoformat()

        return sessions

    @database_sync_to_async
    def _update_heartbeat(self, user_id, event_id):
        from .models import ViewerSession

        now = timezone.now()

        session = ViewerSession.objects.filter(
            user_id=user_id,
            event_id=event_id,
            left_at=None,
        ).first()

        if not session:
            return

        if session.last_heartbeat:
            elapsed = int(
                (now - session.last_heartbeat).total_seconds()
            )

            session.watch_duration_seconds += min(elapsed, 60)

        session.last_heartbeat = now

        session.save(
            update_fields=[
                "last_heartbeat",
                "watch_duration_seconds",
            ]
        )


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.event_id = self.scope["url_route"]["kwargs"]["event_id"]
        self.group_name = f"chat_{self.event_id}"
        self._last_sent_at = None
 
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return
 
        if not await self._event_exists(self.event_id):
            await self.close(code=4004)
            return
 
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
 
        history = await self._get_recent_messages(self.event_id)
        await self.send_json({"type": "history", "messages": history})
 
        counts = await database_sync_to_async(get_reaction_counts)(self.event_id)
        await self.send_json({"type": "reaction_counts", "counts": counts})
 
    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
 
    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "message":
            await self._handle_message(content)
        elif msg_type == "edit":
            await self._handle_edit(content)
        elif msg_type == "reaction":
            await self._handle_reaction(content)
        elif msg_type == "delete":
            await self._handle_delete(content)
        else:
            await self.send_json({"type": "error", "detail": "Unknown message type."})
 
    # ---- incoming actions ----
 
    async def _handle_message(self, content):
        text = (content.get("message") or "").strip()
        if not text:
            return
        if len(text) > MAX_MESSAGE_LENGTH:
            await self.send_json(
                {"type": "error", "detail": f"Message too long (max {MAX_MESSAGE_LENGTH} chars)."}
            )
            return
 
        now = timezone.now()
        if self._last_sent_at and (now - self._last_sent_at).total_seconds() < MIN_SECONDS_BETWEEN_MESSAGES:
            await self.send_json({"type": "error", "detail": "You're sending messages too fast."})
            return
        self._last_sent_at = now
 
        message = await self._create_message(self.event_id, self.user.id, text)
        await self.channel_layer.group_send(
            self.group_name, {"type": "chat.message.broadcast", "message": message}
        )
 
    async def _handle_edit(self, content):
        message_id = content.get("message_id")
        new_text = (content.get("message") or "").strip()
        if not message_id or not new_text:
            return
        if len(new_text) > MAX_MESSAGE_LENGTH:
            await self.send_json(
                {"type": "error", "detail": f"Message too long (max {MAX_MESSAGE_LENGTH} chars)."}
            )
            return

        message = await self._edit_message(message_id, self.event_id, self.user.id, new_text)
        if message is None:
            await self.send_json(
                {"type": "error", "detail": "You can only edit your own messages within "
                                             f"{EDIT_WINDOW_SECONDS // 60} minutes of sending."}
            )
            return

        await self.channel_layer.group_send(
            self.group_name, {"type": "chat.edit.broadcast", "message": message}
        ) 

    async def _handle_reaction(self, content):
        reaction_type = content.get("reaction")
        if reaction_type not in {choice.value for choice in ChatReactionType}:
            await self.send_json({"type": "error", "detail": "Invalid reaction type."})
            return
 
        counts = await database_sync_to_async(self._increment_and_get)(self.event_id, reaction_type)
        await self.channel_layer.group_send(
            self.group_name, {"type": "chat.reaction.broadcast", "counts": counts}
        )
 
    async def _handle_delete(self, content):
        message_id = content.get("message_id")
        if not message_id:
            return

        deleted = await self._soft_delete_message(message_id, self.event_id, self.user)
        if not deleted:
            is_moderator = getattr(self.user, "role", None) in MODERATOR_ROLES
            detail = (
                "Message not found."
                if is_moderator
                else "You can only delete your own messages within "
                     f"{DELETE_WINDOW_SECONDS // 60} minutes of sending."
            )
            await self.send_json({"type": "error", "detail": detail})
            return

        await self.channel_layer.group_send(
            self.group_name, {"type": "chat.delete.broadcast", "message_id": message_id}
        )
 
    # ---- group event handlers: fan out to this socket ----
 
    async def chat_message_broadcast(self, event):
        await self.send_json({"type": "message", "message": event["message"]})
 
    async def chat_edit_broadcast(self, event):
        await self.send_json({"type": "message_edited", "message": event["message"]})
 
    async def chat_reaction_broadcast(self, event):
        await self.send_json({"type": "reaction_counts", "counts": event["counts"]})
 
    async def chat_delete_broadcast(self, event):
        await self.send_json({"type": "message_deleted", "message_id": event["message_id"]})
 
    # ---- helpers ----
 
    @staticmethod
    def _increment_and_get(event_id, reaction_type):
        increment_reaction(event_id, reaction_type)
        return get_reaction_counts(event_id)
 
    @database_sync_to_async
    def _event_exists(self, event_id):
        return Event.objects.filter(pk=event_id).exists()
 
    @database_sync_to_async
    def _create_message(self, event_id, user_id, text):
        msg = ChatMessage.objects.select_related("sender").get(
            pk=ChatMessage.objects.create(event_id=event_id, sender_id=user_id, message=text).pk
        )
        return ChatMessageSerializer(msg).data
 
    @database_sync_to_async
    def _get_recent_messages(self, event_id, limit=50):
        qs = (
            ChatMessage.objects.filter(event_id=event_id, is_deleted=False)
            .select_related("sender")
            .order_by("-created_at")[:limit]
        )
        messages = list(reversed(list(qs)))
        return ChatMessageSerializer(messages, many=True).data
 
    @database_sync_to_async
    def _edit_message(self, message_id, event_id, user_id, new_text):
        """Owner-only, and only within EDIT_WINDOW_SECONDS of sending —
        no moderator override. Moderators moderate by deleting, not by
        rewriting someone else's words."""
        cutoff = timezone.now() - timedelta(seconds=EDIT_WINDOW_SECONDS)
        updated = ChatMessage.objects.filter(
            pk=message_id,
            event_id=event_id,
            sender_id=user_id,
            is_deleted=False,
            created_at__gte=cutoff,
        ).update(message=new_text, edited_at=timezone.now())
        if not updated:
            return None
        msg = ChatMessage.objects.select_related("sender").get(pk=message_id)
        return ChatMessageSerializer(msg).data
 
    @database_sync_to_async
    def _soft_delete_message(self, message_id, event_id, user):
        """Moderators can delete any message at any time. Regular senders
        can only delete their own message, and only within
        DELETE_WINDOW_SECONDS of sending it."""
        is_moderator = getattr(user, "role", None) in MODERATOR_ROLES
        qs = ChatMessage.objects.filter(pk=message_id, event_id=event_id)
        if not is_moderator:
            cutoff = timezone.now() - timedelta(seconds=DELETE_WINDOW_SECONDS)
            qs = qs.filter(sender_id=user.id, created_at__gte=cutoff)
        updated = qs.update(is_deleted=True, edited_at=timezone.now())
        return updated > 0