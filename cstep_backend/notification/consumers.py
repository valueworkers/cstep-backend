from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    One connection per authenticated user. Connect to:
    wss://<host>/ws/notifications/?token=<jwt_access_token>

    Auth: this project authenticates via SimpleJWT, not session cookies, so
    the default Channels AuthMiddlewareStack will NOT populate scope["user"].
    Wire up a JWT-aware channel middleware in asgi.py so scope["user"] is set
    from the access token before connect() runs (see INTEGRATION.md). If you
    already have JWT channel middleware from the chat or analytics consumers,
    reuse that exact stack here rather than adding a second implementation.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or user.is_anonymous:
            await self.close(code=4401)
            return
        self.group_name = f"notifications_user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Push an initial snapshot so the client doesn't need a separate
        # REST round trip just to populate the unread badge on connect.
        unread_count = await self._get_unread_count(user.id)
        await self.send_json({"type": "unread_count", "unread_count": unread_count})

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Dispatched by channel_layer.group_send(..., {"type": "notification_message", ...})
    async def notification_message(self, event):
        await self.send_json({"type": "notification", "notification": event["notification"]})

    @staticmethod
    @database_sync_to_async
    def _get_unread_count(user_id):
        from .constants import NotificationChannel
        from .models import Notification

        return Notification.objects.filter(
            user_id=user_id, channel=NotificationChannel.IN_APP, is_read=False
        ).count()