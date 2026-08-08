from channels.generic.websocket import AsyncJsonWebsocketConsumer


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    One connection per authenticated user. Connect to: wss://<host>/ws/notifications/
    Auth: relies on Django's session cookie via Channels' default
    AuthMiddlewareStack (see INTEGRATION.md) — scope["user"] must be set.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or user.is_anonymous:
            await self.close(code=4401)
            return
        self.group_name = f"notifications_user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Dispatched by channel_layer.group_send(..., {"type": "notification_message", ...})
    async def notification_message(self, event):
        await self.send_json({"notification": event["notification"]})