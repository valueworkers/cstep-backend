import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from djangochannelsrestframework.consumers import AsyncAPIConsumer
from djangochannelsrestframework.decorators import action

from events.models import Event

from .services import LiveAnalyticsService
from .permissions import *
from .registry import (
    register_connection,
    unregister_connection,
    add_visual,
    remove_visual,
    remove_visuals,
)

logger = logging.getLogger(__name__)


class LiveAnalyticsConsumer(AsyncAPIConsumer):
    """
    Relays 'analytics.update' broadcasts from push_live_analytics (tasks.py),
    filtered to whichever visuals this connection has subscribed to, and
    optionally scoped per-visual to a day_id/session_id.

    Client subscribes to a visual (and optionally filters it) by sending
    its name as the action plus optional day_id/session_id, e.g.
    {"action": "no_show"} or {"action": "session_wise_feedback", "session_id": 12}.
    Re-sending the same action with different (or no) day_id/session_id
    changes/clears the filter for that visual.

    self.requested_visuals is the set of visual keys this connection wants
    (mirrored in Redis so push_live_analytics only builds what's actually
    subscribed to, across all open sockets for an event). self.visual_filters
    tracks any per-visual day_id/session_id scoping, which is connection-
    local only (not shared via Redis) since it doesn't affect what the
    periodic task needs to build for the group.
    """
    permission_classes = [IsModeratorOrAbove]

    async def connect(self):
        self.event_id = int(self.scope["url_route"]["kwargs"]["event_id"])
        self.group_name = f"live_analytics_{self.event_id}"
        self.requested_visuals = set()
        self.visual_filters = {}
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

        self.event = await database_sync_to_async(Event.objects.filter(id=self.event_id).first)()
        if self.event is None:
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
        await self.accept()
        await self.send_json({
            "action": "connect",
            "errors": [{"code": error_code, "detail": message}],
            "response_status": 401 if close_code == CLOSE_NO_USER else (403 if close_code == CLOSE_UNAUTHORIZED else 404),
        })
        await self.close(code=close_code)

    async def disconnect(self, code):
        if not self._registered:
            return
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await database_sync_to_async(unregister_connection)(self.event_id)
        await database_sync_to_async(remove_visuals)(self.event_id, self.requested_visuals)

    async def _subscribe(self, visual, day_id=None, session_id=None):
        if visual not in self.requested_visuals:
            self.requested_visuals.add(visual)
            await database_sync_to_async(add_visual)(self.event_id, visual)

        self.visual_filters[visual] = (
            {"day_id": day_id, "session_id": session_id} if (day_id or session_id) else {}
        )

        # Fresh filtered snapshot right away, rather than waiting for the
        # next periodic push, so changing a filter feels immediate.
        data = await self._query_visual(visual, day_id, session_id)
        return {
            "subscribed": sorted(self.requested_visuals),
            "filters": {v: f for v, f in self.visual_filters.items() if f},
            "data": {visual: data},
        }, 200

    @database_sync_to_async
    def _query_visual(self, visual, day_id, session_id):
        service = LiveAnalyticsService(self.event)
        return service.build_payload(visuals=[visual], day_id=day_id, session_id=session_id).get(visual)

    @action()
    async def statewise_login(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("statewise_login", day_id=day_id, session_id=session_id)

    @action()
    async def countrywise_login(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("countrywise_login", day_id=day_id, session_id=session_id)

    @action()
    async def daywise_login(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("daywise_login", day_id=day_id, session_id=session_id)

    @action()
    async def session_wise_max_virtual(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("session_wise_max_virtual", day_id=day_id, session_id=session_id)

    @action()
    async def no_show(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("no_show", day_id=day_id, session_id=session_id)

    @action()
    async def session_wise_feedback(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("session_wise_feedback", day_id=day_id, session_id=session_id)

    @action()
    async def daywise_feedback(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("daywise_feedback", day_id=day_id, session_id=session_id)

    @action()
    async def chats(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("chats", day_id=day_id, session_id=session_id)

    @action()
    async def participation_rate(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("participation_rate", day_id=day_id, session_id=session_id)

    @action()
    async def participation_time(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("participation_time", day_id=day_id, session_id=session_id)

    @action()
    async def participation_duration(self, day_id=None, session_id=None, **kwargs):
        return await self._subscribe("participation_duration", day_id=day_id, session_id=session_id)

    # ---- plain Channels group-send handler, not a DCRF @action ----
    async def analytics_update(self, event):
        payload = await self._build_response(event["data"])
        await self.send_json({"type": "update", "data": payload})

    async def _build_response(self, broadcast_data):
        result = {k: broadcast_data[k] for k in ("event_id", "generated_at") if k in broadcast_data}

        for visual in self.requested_visuals:
            filt = self.visual_filters.get(visual) or {}
            if filt:
                # Filtered connections re-query directly. Not every visual's
                # rows carry enough identifying fields (chats totals,
                # statewise/countrywise logins) to slice the unfiltered
                # broadcast payload post-hoc, so this stays consistent
                # rather than being correct only for some visuals.
                result[visual] = await self._query_visual(visual, filt.get("day_id"), filt.get("session_id"))
            elif visual in broadcast_data:
                result[visual] = broadcast_data[visual]

        return result

    def _parse_visuals_from_query_string(self):
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        raw = qs.get("visuals", [""])[0]
        return {v.strip() for v in raw.split(",") if v.strip()}