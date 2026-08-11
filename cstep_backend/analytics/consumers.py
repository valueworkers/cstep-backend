import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from djangochannelsrestframework.consumers import AsyncAPIConsumer
from djangochannelsrestframework.decorators import action
from djangochannelsrestframework.permissions import BasePermission

from events.models import Event

from .services import LiveAnalyticsService
from .registry import (
    register_connection,
    unregister_connection,
    add_visual,
    remove_visual,
    remove_visuals,
)

logger = logging.getLogger(__name__)

MODERATOR_ROLES = ("MODERATOR", "EVENT_ADMIN", "SUPER_ADMIN")

CLOSE_NO_USER = 4001
CLOSE_UNAUTHORIZED = 4003
CLOSE_EVENT_NOT_FOUND = 4004


class IsModeratorOrAbove(BasePermission):
    def has_permission(self, scope, consumer, action, **kwargs):
        user = scope.get("user")
        return getattr(user, "role", None) in MODERATOR_ROLES


class LiveAnalyticsConsumer(AsyncAPIConsumer):
    """
    Relays 'analytics.update' broadcasts from push_live_analytics (tasks.py),
    filtered to whichever visuals this connection has subscribed to.

    Client subscribes to a visual by sending its name as the action, e.g.
    {"action": "no_show"}. self.requested_visuals is a plain set of the
    keys this connection currently wants, mirrored in Redis (registry.py)
    so push_live_analytics only builds what's actually subscribed to,
    across all open sockets for an event.
    """
    permission_classes = [IsModeratorOrAbove]

    async def connect(self):
        self.event_id = int(self.scope["url_route"]["kwargs"]["event_id"])
        self.group_name = f"live_analytics_{self.event_id}"
        self.requested_visuals = set()
        self._registered = False

        user = self.scope.get("user")
        if user is None:
            await self._reject(CLOSE_NO_USER, "authentication_required", "Authentication required.")
            return

        is_authorized = await database_sync_to_async(
            lambda: getattr(user, "role", None) in MODERATOR_ROLES
        )()
        if not is_authorized:
            await self._reject(CLOSE_UNAUTHORIZED, "permission_denied", "Not permitted to view this event's analytics.")
            return

        event_exists = await database_sync_to_async(Event.objects.filter(id=self.event_id).exists)()
        if not event_exists:
            await self._reject(CLOSE_EVENT_NOT_FOUND, "not_found", f"Event {self.event_id} does not exist.")
            return

        self.requested_visuals = self._parse_visuals_from_query_string()
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        self._registered = True

        await database_sync_to_async(register_connection)(self.event_id)
        for visual in self.requested_visuals:
            await database_sync_to_async(add_visual)(self.event_id, visual)

    async def _reject(self, close_code, error_code, message):
        """Accept briefly to send one JSON error frame (ASGI requires accept
        before send), then close. Lets the frontend read a real error
        instead of just a numeric close code."""
        await self.accept()
        await self.send_json({
            "action": "connect",
            "errors": [{"code": error_code, "detail": message}],
            "response_status": 401 if close_code == CLOSE_NO_USER else (403 if close_code == CLOSE_UNAUTHORIZED else 404),
        })
        await self.close(code=close_code)

    async def disconnect(self, code):
        if not self._registered:
            return  # rejected during connect() — nothing to clean up
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await database_sync_to_async(unregister_connection)(self.event_id)
        await database_sync_to_async(remove_visuals)(self.event_id, self.requested_visuals)

    async def _subscribe(self, visual):
        if visual not in self.requested_visuals:
            self.requested_visuals.add(visual)
            await database_sync_to_async(add_visual)(self.event_id, visual)
        return {"subscribed": sorted(self.requested_visuals)}, 200

    # One action per visual key. Client sends {"action": "no_show"} etc.
    @action()
    async def statewise_login(self, **kwargs):
        return await self._subscribe("statewise_login")

    @action()
    async def countrywise_login(self, **kwargs):
        return await self._subscribe("countrywise_login")

    @action()
    async def daywise_login(self, **kwargs):
        return await self._subscribe("daywise_login")

    @action()
    async def session_wise_max_virtual(self, **kwargs):
        return await self._subscribe("session_wise_max_virtual")

    @action()
    async def no_show(self, **kwargs):
        return await self._subscribe("no_show")

    @action()
    async def session_wise_feedback(self, **kwargs):
        return await self._subscribe("session_wise_feedback")

    @action()
    async def daywise_feedback(self, **kwargs):
        return await self._subscribe("daywise_feedback")

    @action()
    async def chats(self, **kwargs):
        return await self._subscribe("chats")

    @action()
    async def participation_rate(self, **kwargs):
        return await self._subscribe("participation_rate")

    @action()
    async def participation_time(self, **kwargs):
        return await self._subscribe("participation_time")
    @action()
    async def participation_duration(self, **kwargs):
        return await self._subscribe("participation_duration")

    # ---- plain Channels group-send handler, not a DCRF @action ----
    async def analytics_update(self, event):
        await self.send_json({"type": "update", "data": self._filter_payload(event["data"])})

    def _filter_payload(self, payload):
        keep = {"event_id", "generated_at"} | self.requested_visuals
        return {k: v for k, v in payload.items() if k in keep}

    def _parse_visuals_from_query_string(self):
        """?visuals=no_show,statewise_login on the ws URL. No param, or an
        empty value -> empty set (subscribe to nothing until actions are sent)."""
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        raw = qs.get("visuals", [""])[0]
        return {v.strip() for v in raw.split(",") if v.strip()}