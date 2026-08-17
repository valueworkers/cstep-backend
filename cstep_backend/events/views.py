# events/views.py
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models import Avg, Q, F, Exists, Max, OuterRef, Value, BooleanField, Count
from django.db import transaction
import django_filters
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from accounts.models import UserRole
from .constants import ScheduleItemType

from .utils import _get_peak_viewers, _send_ws_event
from .models import Event, EventDay, EventStatus, BroadcastSession, ScheduleItem, Feedback, ViewerSession,ChatMessage
from registrations.models import Registration
from registrations.constants import RegistrationStatus

from .serializers import *
from .permissions import (
    IsModeratorOrAbove,
    IsBroadcasterOrAdmin,
)

class EventViewSet(viewsets.ModelViewSet):
    """
    list:   GET  /event/                  — all users
    create: POST /event/                  — EVENT_ADMIN+
    detail: GET  /event/{id}/             — all users
    update: PUT  /event/{id}/             — creator or admin
    delete: DELETE /event/{id}/           — creator or admin

    Custom actions:
      GET  /event/upcoming/               — Upcoming events for all users, with registration status
      GET  /event/dropdown/               — lightweight id/title list for selects
      GET  /event/{id}/days/              — full schedule (all days + items)
      POST /event/{id}/regenerate_days/   — EVENT_ADMIN+ / creator — fill in missing dates
      GET  /event/{id}/analytics/         — MODERATOR+
      GET  /event/{id}/viewers/           — MODERATOR+

    Stream lifecycle (go_live/end_stream/broadcast) and viewer-session
    actions (watch/join/leave/heartbeat) live on EventBroadcastViewSet
    and EventViewerViewSet respectively — same "event" URL prefix.
    """
    queryset = Event.objects.select_related("created_by").prefetch_related("days__items").all()
    search_fields = [
        "title", "description",
        "created_by__first_name", "created_by__last_name", "created_by__email",
    ]
    filterset_fields = {
        "status": ["exact"],
        "schedule_type": ["exact"],
        "created_by": ["exact"],
        "video_muted_by_default": ["exact"],
        "pause_continue_enabled": ["exact"],
        "scheduled_start": ["gte", "lte"],
        "scheduled_end": ["gte", "lte"],
        "created_at": ["gte", "lte"],
    }
    ordering_fields = [
        "title", "status", "schedule_type", "scheduled_start", "scheduled_end",
        "stream_start_time", "stream_end_time", "created_at", "updated_at",
    ]

    def get_serializer_class(self):
        if self.action == "list":
            return EventListSerializer
        if self.action == "upcoming":
            return UpcomingEventSerializer
        if self.action in ("create", "update", "partial_update"):
            return EventCreateUpdateSerializer
        if self.action == "days":
            return EventDaySerializer
        return EventDetailSerializer

    def get_permissions(self):
        if self.action in ("upcoming", "days"):
            return [AllowAny()]
        if self.action in ("create", "update", "partial_update", "destroy", "analytics", "viewers"):
            return [IsModeratorOrAbove()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        event_type = self.request.query_params.get("type")
        if self.action == "list" and event_type:
            TYPE_FILTERS = {
                "upcoming": (Q(scheduled_start__gt=timezone.now()), "scheduled_start"),
                "live": (
                    Q(scheduled_start__lte=timezone.now())
                    & (Q(scheduled_end__gte=timezone.now()) | Q(scheduled_end__isnull=True)),
                    "scheduled_start",
                ),
                "past": (Q(scheduled_end__lt=timezone.now()), "-scheduled_end"),
            }
            entry = TYPE_FILTERS.get(event_type)
            if entry is None:
                raise ValidationError(
                    {"type": f"Invalid value. Choose from: {', '.join(TYPE_FILTERS)}"}
                )
            condition, ordering = entry
            queryset = queryset.filter(condition).order_by(ordering)
        return queryset

    # ------------------------------------------------------------------
    # Dropdowns
    # ------------------------------------------------------------------
    @action(detail=False, methods=["get"], url_path="dropdown")
    def dropdown(self, request):
        """GET events/event/dropdown — lightweight id,title,schedule_type list for select inputs."""
        queryset = Event.objects.only("id", "title", "schedule_type", "scheduled_start", "scheduled_end").order_by("title")
        return Response(EventDropdownSerializer(queryset, many=True).data)

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    @action(detail=True, methods=["get"], url_path="days")
    def days(self, request, pk=None):
        """Full schedule for the event — every EventDay with its ordered ScheduleItems."""
        event = self.get_object()
        days = event.days.prefetch_related("items").all()
        return Response(EventDaySerializer(days, many=True).data)

    @action(detail=True, methods=["post"], url_path="regenerate_days")
    def regenerate_days(self, request, pk=None):
        """
        Call after editing scheduled_start/scheduled_end/schedule_type on
        an existing event. Idempotent — only creates EventDay rows for
        dates that don't already exist; never touches or deletes existing
        days, so in-progress MULTI_SESSION schedules are preserved.
        """
        event = self.get_object()
        event.generate_days()
        return Response(EventDaySerializer(event.days.all(), many=True).data)

    @action(detail=False, methods=["get"])
    def upcoming(self, request):
        queryset = Event.objects.filter(scheduled_start__gte=timezone.now()).annotate(
            total_registered_users=Count("registrations__user", distinct=True),
            participants_attended=Count(
                "registrations",
                filter=Q(registrations__user__viewer_sessions__event=F("pk")),
                distinct=True,
            ),
            participants_accepted=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.ACCEPTED),
                distinct=True,
            ),
            participants_rejected=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.REJECTED),
                distinct=True,
            ),
            participants_pending=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.PENDING),
                distinct=True,
            ),
            participants_hold=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.HOLD),
                distinct=True,
            ),
        ).order_by("scheduled_start")
        if request.user.is_authenticated:
            user_registered = Registration.objects.filter(event=OuterRef("pk"), user=request.user)
            queryset = queryset.annotate(is_registered=Exists(user_registered))
        else:
            queryset = queryset.annotate(is_registered=Value(False, output_field=BooleanField()))

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = UpcomingEventSerializer(page, many=True, context=self.get_serializer_context())
            return self.get_paginated_response(serializer.data)

        serializer = UpcomingEventSerializer(queryset, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    @action(detail=True, methods=["get"], url_path="analytics")
    def analytics(self, request, pk=None):
        event = self.get_object()
        sessions = event.viewer_sessions.all()

        duration_minutes = None
        if event.stream_start_time and event.stream_end_time:
            delta = event.stream_end_time - event.stream_start_time
            duration_minutes = round(delta.total_seconds() / 60, 1)

        avg_watch = sessions.aggregate(avg=Avg("watch_duration_seconds"))["avg"] or 0

        payload = {
            "event_id": event.id,
            "event_title": event.title,
            "status": event.status,
            "total_joins": sessions.count(),
            "concurrent_viewers": sessions.filter(left_at=None).count(),
            "peak_viewers": _get_peak_viewers(event),
            "avg_watch_duration_minutes": round(avg_watch / 60, 1),
            "stream_duration_minutes": duration_minutes,
        }
        return Response(EventAnalyticsSerializer(payload).data)

    @action(detail=True, methods=["get"], url_path="viewers")
    def viewers(self, request, pk=None):
        event = self.get_object()
        sessions = event.viewer_sessions.select_related("user").filter(left_at=None)
        return Response(ViewerSessionSerializer(sessions, many=True).data)

class EventBroadcastViewSet(viewsets.GenericViewSet):
    """
    Broadcaster/admin-facing stream control — same "event" URL prefix as
    EventViewSet, registered separately so permissions/serializers stay
    scoped to BroadcastSession concerns.

    GET  /event/{id}/go_live/               — EVENT_ADMIN+ — preview readiness
    POST /event/{id}/go_live/               — EVENT_ADMIN+
    GET  /event/{id}/end_stream/            — EVENT_ADMIN+ — preview readiness
    POST /event/{id}/end_stream/            — EVENT_ADMIN+
    GET  /event/{id}/broadcast/             — the broadcaster (or admin) — WHIP ingest URL
    GET  /event/{id}/broadcast_sessions/    — EVENT_ADMIN+ — list cameras
    POST /event/{id}/broadcast_sessions/    — EVENT_ADMIN+ — add a camera
    """
    queryset = Event.objects.prefetch_related("broadcast_sessions").all()

    def get_serializer_class(self):
        if self.action == "broadcast_sessions":
            return BroadcastSessionCreateSerializer
        return BroadcastSessionSerializer

    def get_permissions(self):
        if self.action == "broadcast":
            return [IsAuthenticated()]
        return [IsModeratorOrAbove()]

    @action(detail=True, methods=["get", "post"], url_path="go_live")
    def go_live(self, request, pk=None):
        event = self.get_object()

        if request.method == "GET":
            sessions = list(event.broadcast_sessions.all())
            return Response({
                "event_id": event.id,
                "status": event.status,
                "is_live": event.status == EventStatus.LIVE,
                "can_go_live": event.status != EventStatus.LIVE and bool(sessions),
                "broadcast_session_count": len(sessions),
            })

        serializer = GoLiveSerializer(data={}, context={"event": event})
        serializer.is_valid(raise_exception=True)

        sessions = list(event.broadcast_sessions.all())
        primary_session = next((s for s in sessions if s.is_primary), sessions[0])

        event.status = EventStatus.LIVE
        event.stream_start_time = timezone.now()
        event.playback_url = primary_session.playback_url
        event.save(update_fields=["status", "stream_start_time", "playback_url", "updated_at"])

        event.broadcast_sessions.update(is_active=True, started_at=event.stream_start_time)

        _send_ws_event(
            event.id,
            {
                "type": "stream.started",
                "playback_urls": [s.playback_url for s in sessions],
            },
        )

        return Response(EventDetailSerializer(event, context={"request": request}).data)

    @action(detail=True, methods=["get", "post"], url_path="end_stream")
    def end_stream(self, request, pk=None):
        event = self.get_object()

        if request.method == "GET":
            return Response({
                "event_id": event.id,
                "status": event.status,
                "is_live": event.status == EventStatus.LIVE,
                "can_end_stream": event.status == EventStatus.LIVE,
                "stream_start_time": event.stream_start_time,
            })

        serializer = EndStreamSerializer(data={}, context={"event": event})
        serializer.is_valid(raise_exception=True)

        now = timezone.now()
        event.status = EventStatus.ENDED
        event.stream_end_time = now
        event.save(update_fields=["status", "stream_end_time", "updated_at"])

        event.broadcast_sessions.update(is_active=False, ended_at=now)

        ViewerSession.objects.filter(event=event, left_at=None).update(left_at=now)
        # from analytics.broadcast import push_live_analytics
        # push_live_analytics(event.id)
        RegistrationDay.objects.filter(day__event=event, registration__user=request.user).update(is_attended=True)
        _send_ws_event(event.id, {"type": "stream.ended"})

        return Response({"detail": "Stream ended."})

    @action(detail=True, methods=["get"], url_path="broadcast")
    def broadcast(self, request, pk=None):
        """
        WHIP is POST-based SDP signaling — the publisher's WebRTC client
        does the handshake via fetch(), so this just hands back the ingest
        URL + key as JSON rather than redirecting a browser to it.
        """
        event = self.get_object()

        if request.user.role in ("EVENT_ADMIN", "SUPER_ADMIN"):
            visible_sessions = event.broadcast_sessions.all()
        else:
            visible_sessions = event.broadcast_sessions.filter(broadcaster=request.user)

        if not visible_sessions.exists():
            return Response(
                {"detail": "No broadcast session configured. Create one first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        camera = CameraSelectSerializer(data=request.query_params)
        camera.is_valid(raise_exception=True)
        if camera.select(visible_sessions) is None:
            return Response({"detail": "Camera not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "broadcast_sessions": BroadcastSessionSerializer(
                visible_sessions, many=True, context={"request": request}
            ).data,
        })

    @action(detail=True, methods=["get", "post"], url_path="broadcast_sessions")
    def broadcast_sessions(self, request, pk=None):
        """GET lists cameras for the event; POST adds a new one."""
        event = self.get_object()

        if request.method == "GET":
            sessions = event.broadcast_sessions.all()
            return Response(
                BroadcastSessionSerializer(sessions, many=True, context={"request": request}).data
            )

        data = {**request.data, "event": event.id}
        serializer = BroadcastSessionCreateSerializer(data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return Response(
            BroadcastSessionSerializer(session, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

class EventViewerViewSet(viewsets.GenericViewSet):
    """
    Viewer-facing playback + presence — same "event" URL prefix as
    EventViewSet, registered separately so permissions/serializers stay
    scoped to ViewerSession concerns.

    GET  /event/{id}/watch/      — any viewer — WHEP playback URL
    GET  /event/{id}/join/       — authenticated viewer — preview join eligibility
    POST /event/{id}/join/       — authenticated viewer
    GET  /event/{id}/leave/      — authenticated viewer — current session status
    POST /event/{id}/leave/      — authenticated viewer
    GET  /event/{id}/heartbeat/  — authenticated viewer — current session status
    POST /event/{id}/heartbeat/  — authenticated viewer
    """
    queryset = Event.objects.prefetch_related("broadcast_sessions").all()
    permission_classes = [IsAuthenticated]
    serializer_class = ViewerSessionSerializer

    def get_permissions(self):
        if self.action == "watch":
            return [AllowAny()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["get"], url_path="watch")
    def watch(self, request, pk=None):
        """Returns the WHEP playback URL for the viewer's client to subscribe to."""
        event = self.get_object()
        sessions = event.broadcast_sessions.all()

        if not sessions.exists():
            return Response(
                {"detail": "No broadcast session configured. Create one first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        camera = CameraSelectSerializer(data=request.query_params)
        camera.is_valid(raise_exception=True)
        if camera.select(sessions) is None:
            return Response({"detail": "Camera not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "broadcast_sessions": BroadcastSessionSerializer(
                sessions, many=True, context={"request": request}
            ).data,
        })

    @action(detail=True, methods=["get", "post"], url_path="join")
    def join(self, request, pk=None):
        event = self.get_object()

        if request.method == "GET":
            existing = ViewerSession.objects.filter(
                event=event, user=request.user, left_at=None
            ).first()
            return Response({
                "event_id": event.id,
                "is_live": event.status == EventStatus.LIVE,
                "can_join": event.status == EventStatus.LIVE,
                "active_session": ViewerSessionSerializer(existing).data if existing else None,
            })

        if event.status != EventStatus.LIVE:
            return Response({"detail": "Event is not currently live."}, status=status.HTTP_400_BAD_REQUEST)

        location = ViewerSessionLocationSerializer(data=request.data, context={"event": event})
        location.is_valid(raise_exception=True)

        validated = dict(location.validated_data)
        session_id = validated.pop("session_id", None)

        ViewerSession.objects.filter(event=event, user=request.user, left_at=None).update(
            left_at=timezone.now()
        )
        RegistrationDay.objects.filter(day__event=event, registration__user=request.user).update(is_attended=True)

        viewer_session = ViewerSession.objects.create(
            user=request.user,
            event=event,
            session_id=session_id,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            **validated,
        )

        concurrent = event.viewer_sessions.filter(left_at=None).count()
        _send_ws_event(event.id, {"type": "viewer.joined", "concurrent_viewers": concurrent})

        payload = {
            "event_id": event.id,
            "day_id": viewer_session.day_id,
            "session_id": viewer_session.session_id,
            "event_title": event.title,
            "broadcast_sessions": event.broadcast_sessions.all(),
            "viewer_session_id": viewer_session.id,
            "concurrent_viewers": concurrent,
            "video_muted_by_default": event.video_muted_by_default,
        }
        return Response(ViewerJoinSerializer(payload, context={"request": request}).data)

    @action(detail=True, methods=["get", "post"], url_path="leave")
    def leave(self, request, pk=None):
        event = self.get_object()
        session = ViewerSession.objects.filter(event=event, user=request.user, left_at=None).first()

        if request.method == "GET":
            return Response({
                "event_id": event.id,
                "has_active_session": session is not None,
                "active_session": ViewerSessionSerializer(session).data if session else None,
            })

        now = timezone.now()
        updated = ViewerSession.objects.filter(event=event, user=request.user, left_at=None).update(left_at=now)
        RegistrationDay.objects.filter(day__event=event, registration__user=request.user).update(is_attended=True)
        if not updated:
            return Response({"detail": "No active viewer session found."}, status=status.HTTP_404_NOT_FOUND)

        concurrent = event.viewer_sessions.filter(left_at=None).count()
        # from analytics.broadcast import push_live_analytics
        # push_live_analytics(event.id)
        _send_ws_event(event.id, {"type": "viewer.left", "concurrent_viewers": concurrent})

        return Response({"detail": "Left the stream."})

    @action(detail=True, methods=["get", "post"], url_path="heartbeat")
    def heartbeat(self, request, pk=None):
        event = self.get_object()
        session = ViewerSession.objects.filter(event=event, user=request.user, left_at=None).first()      

        if request.method == "GET":
            if not session:
                return Response({"detail": "No active session."}, status=status.HTTP_404_NOT_FOUND)
            return Response({
                "status": "active",
                "watch_duration_seconds": session.watch_duration_seconds,
                "last_heartbeat": session.last_heartbeat,
            })

        if not session:
            return Response({"detail": "No active session."}, status=status.HTTP_404_NOT_FOUND)

        validator = HeartbeatSerializer(data={}, context={"session": session})
        validator.is_valid(raise_exception=True)

        now = timezone.now()
        if session.last_heartbeat:
            elapsed = int((now - session.last_heartbeat).total_seconds())
            session.watch_duration_seconds += min(elapsed, 60)
        session.last_heartbeat = now
        session.save(update_fields=["last_heartbeat", "watch_duration_seconds"])

        return Response(
            HeartbeatSerializer({"status": "ok", "watch_duration_seconds": session.watch_duration_seconds}).data
        )
    
class EventDayViewSet(viewsets.ModelViewSet):
    """
    list:     GET   /event-days/?event={id}   — all users
    retrieve: GET   /event-days/{id}/          — all users
    dropdown: GET   /event-days/dropdown/?event={id} — all users
    set_label: PATCH /event-days/{id}/label/   — event creator, EVENT_ADMIN, SUPER_ADMIN

    Days are generated by Event.generate_days() — never created directly
    by clients. Only the label is editable, via the set_label action
    (PATCH /event-days/{id}/label/). Item CRUD goes through ScheduleItemViewSet.
    """
    queryset = EventDay.objects.select_related("event").prefetch_related("items").all()
    serializer_class = EventDaySerializer
    filterset_fields = {"event": ["exact"], "date": ["exact", "gte", "lte"]}
    ordering_fields = ["date", "day_number"]
    permission_classes = [IsModeratorOrAbove]

    def get_permissions(self):
        if self.action in ("list", "retrieve", "dropdown"):
            return [IsAuthenticated()]
        return super().get_permissions()

    @action(detail=False, methods=["get"], url_path="dropdown")
    def dropdown(self, request):
        """GET events/event-days/dropdown/?event=<id> — lightweight day list for select inputs."""
        event_id = request.query_params.get("event")
        if not event_id:
            raise ValidationError({"event": "This query param is required."})

        queryset = EventDay.objects.filter(event_id=event_id).only(
            "id", "day_number", "date", "label", "event_id"
        )
        return Response(EventDayDropdownSerializer(queryset, many=True).data)

class ScheduleItemViewSet(viewsets.ModelViewSet):
    """
    list:     GET    /schedule-items/?day={id}          — all users
    create:   POST   /schedule-items/                   — event creator/admin
    detail:   GET    /schedule-items/{id}/              — all users
    update:   PATCH  /schedule-items/{id}/              — event creator/admin
    delete:   DELETE /schedule-items/{id}/              — event creator/admin

    Custom actions:
      POST /schedule-items/reorder/?day={id}   — bulk reorder/reschedule after drag-drop
      GET  /schedule-items/dropdown/?day={id}  — all users
    """

    queryset = ScheduleItem.objects.select_related("day__event").all()
    serializer_class = ScheduleItemSerializer
    filterset_fields = {"day": ["exact"], "item_type": ["exact"], "track": ["exact"]}
    ordering_fields = ["order", "start_time"]
    permission_classes = [IsModeratorOrAbove]

    def get_permissions(self):
        if self.action in ("list", "retrieve", "dropdown"):
            return [IsAuthenticated()]
        return super().get_permissions()

    @action(detail=False, methods=["get"], url_path="dropdown")
    def dropdown(self, request):
        """GET events/schedule-items/dropdown/?day=<id> — lightweight item list for select inputs."""
        day_id = request.query_params.get("day")
        if not day_id:
            raise ValidationError({"day": "This query param is required."})

        queryset = ScheduleItem.objects.filter(day_id=day_id, item_type=ScheduleItemType.SESSION).only(
            "id", "title", "start_time", "end_time", "item_type", "speaker_name"
        ).order_by("order", "start_time")
        return Response(ScheduleItemDropdownSerializer(queryset, many=True).data)

    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request):
        """
        Body: { "items": [{"id": 4, "order": 0, "track": "main",
                            "start_time": "09:00", "end_time": "09:45"}, ...] }
        Frontend sends the full new arrangement for a day (or a single
        track within a day) after a drag-and-drop operation.
        """
        serializer = ScheduleItemReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entries = serializer.validated_data["items"]

        if not entries:
            return Response({"detail": "No items provided."}, status=status.HTTP_400_BAD_REQUEST)

        item_ids = [entry["id"] for entry in entries]
        items = {
            item.id: item
            for item in ScheduleItem.objects.select_related("day__event").filter(id__in=item_ids)
        }

        missing = set(item_ids) - set(items)
        if missing:
            return Response(
                {"detail": f"Schedule item(s) not found: {sorted(missing)}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # All items must belong to the same event, and the requester must
        # be that event's creator/admin — checked once up front.
        events = {item.day.event_id for item in items.values()}
        if len(events) > 1:
            return Response(
                {"detail": "All reordered items must belong to the same event."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        sample_event = next(iter(items.values())).day.event
        if not (
            request.user.is_authenticated
            and (request.user == sample_event.created_by or request.user.role in ("EVENT_ADMIN", "SUPER_ADMIN"))
        ):
            return Response({"detail": "Not permitted."}, status=status.HTTP_403_FORBIDDEN)

        updated = []
        with transaction.atomic():
            for entry in entries:
                item = items[entry["id"]]
                item.order = entry["order"]
                if "track" in entry:
                    item.track = entry["track"]
                if "start_time" in entry:
                    item.start_time = entry["start_time"]
                if "end_time" in entry:
                    item.end_time = entry["end_time"]
                item.full_clean()
                item.save()
                updated.append(item)

        return Response(ScheduleItemSerializer(updated, many=True).data)

class BroadcastSessionViewSet(viewsets.ModelViewSet):
    """
    POST   /broadcast-sessions/                     — create (EVENT_ADMIN+)
    GET    /broadcast-sessions/{id}/                — retrieve (broadcaster or admin)
    DELETE /broadcast-sessions/{id}/                — destroy

    POST /broadcast-sessions/{id}/regenerate_key/          — rotate key + URLs together
    POST /broadcast-sessions/{id}/toggle_viewer_recording/ — allow/disallow viewer self-recording (EVENT_ADMIN+)
    POST /broadcast-sessions/{id}/start_recording/         — begin server-side recording (EVENT_ADMIN+)
    POST /broadcast-sessions/{id}/stop_recording/          — end server-side recording (EVENT_ADMIN+)
    GET  /broadcast-sessions/{id}/recordings/              — list READY recordings (any authenticated viewer)
    """

    queryset = BroadcastSession.objects.select_related("event", "broadcaster").all()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return BroadcastSessionCreateSerializer
        return BroadcastSessionSerializer

    def get_permissions(self):
        if self.action in ("retrieve", "recordings"):
            return [IsBroadcasterOrAdmin()]
        return [IsModeratorOrAbove()]

    @action(detail=True, methods=["post"], url_path="regenerate_key")
    def regenerate_key(self, request, pk=None):
        session = self.get_object()
        if session.is_active:
            return Response(
                {"detail": "Cannot rotate key while stream is active."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session.stream_key = BroadcastSession.generate_stream_key()
        session.ingest_url = ""
        session.playback_url = ""
        session.save(update_fields=["stream_key", "ingest_url", "playback_url"])
        return Response(BroadcastSessionSerializer(session, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="toggle_viewer_recording")
    def toggle_viewer_recording(self, request, pk=None):
        session = self.get_object()
        allow = request.data.get("allow_viewer_recording")
        if allow is None:
            return Response(
                {"detail": "allow_viewer_recording is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        session.allow_viewer_recording = bool(allow)
        session.save(update_fields=["allow_viewer_recording"])
        return Response(BroadcastSessionSerializer(session, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="start_recording")
    def start_recording(self, request, pk=None):
        session = self.get_object()
        if session.is_recording:
            return Response(
                {"detail": "Recording already in progress."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recording = StreamRecording.objects.create(broadcast_session=session, started_by=request.user)
        session.is_recording = True
        session.save(update_fields=["is_recording"])

        _send_ws_event(session.event_id, {
            "type": "recording.started",
            "broadcast_session_id": session.id,
            "recording_id": recording.id,
        })

        # TODO: trigger_mediamtx_recording(session.stream_key, enable=True)

        return Response(StreamRecordingSerializer(recording).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="stop_recording")
    def stop_recording(self, request, pk=None):
        session = self.get_object()
        recording = session.recordings.filter(status=RecordingStatus.RECORDING).first()
        if not recording:
            return Response(
                {"detail": "No recording in progress."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recording.ended_at = timezone.now()
        recording.status = RecordingStatus.PROCESSING
        recording.save(update_fields=["ended_at", "status"])

        session.is_recording = False
        session.save(update_fields=["is_recording"])

        # TODO: stop MediaMTX recording, kick off process_recording.delay(recording.id)

        return Response(StreamRecordingSerializer(recording).data)

class StreamRecordingFilter(django_filters.FilterSet):
    event_id = django_filters.NumberFilter(field_name="session__day__event_id")
    day_id = django_filters.NumberFilter(field_name="session__day_id")
    status = django_filters.CharFilter(field_name="status")
    started_after = django_filters.DateTimeFilter(field_name="started_at", lookup_expr="gte")
    started_before = django_filters.DateTimeFilter(field_name="started_at", lookup_expr="lte")

    class Meta:
        model = StreamRecording
        fields = ["event_id", "day_id", "status", "session"]


class StreamRecordingViewSet(viewsets.ModelViewSet):
    queryset = StreamRecording.objects.select_related("session__day__event")
    serializer_class = StreamRecordingSerializer
    filterset_class = StreamRecordingFilter
    search_fields = ["session__title", "status"]
    ordering_fields = ["started_at", "ended_at", "status"]
    ordering = ["-started_at"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsModeratorOrAbove()]
        
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["event"] = getattr(self.request, "event", None)
        context["day"] = getattr(self.request, "day", None)
        return context

class FeedbackViewSet(viewsets.ModelViewSet):
    serializer_class = FeedbackSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["event", "event_date", "schedule_item", "user", "is_overall_rating", "rating"]
    search_fields = ["comment", "user__first_name", "user__last_name", "user__phone_number", "user__email", "schedule_item__title"]
    ordering_fields = [
        "id", "event", "event__title", "event_date", "event_date__date",
        "schedule_item", "schedule_item__title", "user", "user__full_name",
        "is_overall_rating", "rating", "comment", "created_at", "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Feedback.objects.select_related(
            "user", "event", "event_date", "schedule_item"
        )
        user = self.request.user
        if user.role == UserRole.BASE_USER:
            return qs.filter(user=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class ChatMessageViewSet(viewsets.ModelViewSet):
    """
    Read-only + moderation endpoint. Posting new messages happens over the
    WebSocket (ChatConsumer), not here — this covers history pagination on
    initial page load and admin-side message deletion.
    """
    serializer_class = ChatMessageSerializer
    http_method_names = ["get", "delete"]

    def get_queryset(self):
        qs = ChatMessage.objects.filter(is_deleted=False).select_related("sender")
        event_id = self.request.query_params.get("event")
        if event_id:
            qs = qs.filter(event_id=event_id)
        return qs

    def get_permissions(self):
        if self.action == "destroy":
            return [IsAuthenticated()]
        return [IsAuthenticated()]

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.edited_at = timezone.now()
        instance.save(update_fields=["is_deleted", "edited_at"])