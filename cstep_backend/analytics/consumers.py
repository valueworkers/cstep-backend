import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from djangochannelsrestframework.consumers import AsyncAPIConsumer
from djangochannelsrestframework.decorators import action
from djangochannelsrestframework.permissions import BasePermission

from .registry import register_connection, unregister_connection

logger = logging.getLogger(__name__)

MODERATOR_ROLES = ("MODERATOR", "EVENT_ADMIN", "SUPER_ADMIN")


class IsModeratorOrAbove(BasePermission):
    """Used on individual @action methods (not on connect — DCRF's
    check_permissions only runs inside the action dispatch path, so the
    initial connect-time check below is separate and manual)."""

    def has_permission(self, scope, consumer, action, **kwargs):
        user = scope.get("user")
        return getattr(user, "role", None) in MODERATOR_ROLES


class LiveAnalyticsConsumer(AsyncAPIConsumer):
    """
    Sends no 'existing' data on connect — that's LiveAnalyticsSnapshotView's
    (and the per-visual views') job over REST. This socket only relays
    'analytics.update' broadcasts pushed by push_live_analytics (tasks.py),
    filtered to whichever visuals this specific connection has subscribed to.
    """
    permission_classes = (IsModeratorOrAbove,)

    async def connect(self):
        self.event_id = int(self.scope["url_route"]["kwargs"]["event_id"])
        self.group_name = f"live_analytics_{self.event_id}"
        user = self.scope.get("user")

        if user is None:
            await self.close(code=4001)
            return

        is_authorized = await database_sync_to_async(
            lambda: getattr(user, "role", None) in MODERATOR_ROLES
        )()
        if not is_authorized:
            await self.close(code=4003)
            return

        self.requested_visuals = self._parse_visuals_from_query_string()
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await database_sync_to_async(register_connection)(self.event_id)

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await database_sync_to_async(unregister_connection)(self.event_id)

    @action()
    async def subscribe(self, visuals=None, **kwargs):
        """
        Client sends: {"action": "subscribe", "request_id": 1, "visuals": ["statewise_login", ...]}
        `visuals` omitted or null -> everything. Empty list -> nothing but
        event_id/generated_at. DCRF wraps the return in the standard
        {"action": "subscribe", "response_status": 200, "data": {...}, "request_id": 1} envelope.
        Never triggers a DB read — only changes what future 'update' pushes
        are filtered down to for this socket.
        """
        self.requested_visuals = set(visuals) if visuals is not None else None
        return {"subscribed": sorted(self.requested_visuals) if self.requested_visuals else "all"}, 200

    # ---- plain Channels group-send handler, not a DCRF @action ----
    async def analytics_update(self, event):
        """Invoked by channel_layer.group_send(type='analytics.update', ...)
        from tasks.py — unrelated to DCRF's action dispatch system."""
        await self.send_json({"type": "update", "data": self._filter_payload(event["data"])})

    def _filter_payload(self, payload):
        if self.requested_visuals is None:
            return payload
        keep = {"event_id", "generated_at"} | self.requested_visuals
        return {k: v for k, v in payload.items() if k in keep}

    def _parse_visuals_from_query_string(self):
        """?visuals=statewise_login,countrywise_login on the ws URL.
        No param at all -> None (everything). ?visuals= (empty) -> empty set (nothing)."""
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        raw = qs.get("visuals", [None])[0]
        if raw is None:
            return None
        return {v.strip() for v in raw.split(",") if v.strip()}