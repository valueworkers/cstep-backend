from rest_framework import serializers
from accounts.models import UserRole
from .constants import ScheduleItemType,EventScheduleType,EventStatus
from registrations.models import RegistrationSession,RegistrationDay, RegistrationStatus
from .models import (
    Event,
    BroadcastSession,
    Feedback,
    StreamRecording,
    ViewerSession,
    RecordingStatus,
    EventDay,
    ScheduleItem,
    ChatMessage,
)
from .constants import EventScheduleType
from .media import build_ingest_urls, build_playback_urls
from django.core.exceptions import ValidationError as DjangoValidationError

# Schedule (EventDay / ScheduleItem)

class ScheduleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleItem
        fields = [
            "id", "day", "item_type", "title", "description",
            "start_time", "end_time", "order", "track", "room",
            "speaker_name", "allow_networking",
        ]
        read_only_fields = ["id"]
  
    def validate(self, data):
        instance = self.instance or ScheduleItem()
        for field, value in data.items():
            setattr(instance, field, value)

        try:
            instance.full_clean(exclude=["order"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)

        self._validate_single_session_for_whole_day(instance)

        return data

    def _validate_single_session_for_whole_day(self, instance):
        if instance.item_type != ScheduleItemType.SESSION:
            return

        day = instance.day
        if day.event.schedule_type != EventScheduleType.WHOLE_DAY:
            return

        existing_sessions = ScheduleItem.objects.filter(
            day=day, item_type=ScheduleItemType.SESSION
        )
        if instance.pk:
            existing_sessions = existing_sessions.exclude(pk=instance.pk)

        if existing_sessions.exists():
            raise serializers.ValidationError(
                {"item_type": "This day already has a session configured for this whole-day event."}
            )

class EventDaySerializer(serializers.ModelSerializer):
    items = ScheduleItemSerializer(many=True, read_only=True)

    class Meta:
        model = EventDay
        fields = ["id", "event", "date", "day_number", "label", "items","allowed_attendance_modes"]

class ScheduleItemReorderEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order = serializers.IntegerField()
    track = serializers.CharField(max_length=100, required=False)
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)

    def validate(self, data):
        if "start_time" in data and "end_time" in data and data["end_time"] <= data["start_time"]:
            raise serializers.ValidationError("end_time must be after start_time.")
        return data

class ScheduleItemReorderSerializer(serializers.Serializer):
    items = ScheduleItemReorderEntrySerializer(many=True)

# Dropdowns for Event, EventDay and ScheduleItem

class EventDropdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id", "title", "schedule_type","scheduled_start",
            "scheduled_end", "allowed_travel", "allowed_medical",
            "allowed_translation", "allowed_accommodation"
        ]

class EventDayDropdownSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = EventDay
        fields = ["id", "day_number", "date", "label","allowed_attendance_modes"]

    def get_label(self, obj):
        return obj.label or f"Day {obj.day_number} ({obj.date})"

class ScheduleItemDropdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleItem
        fields = ["id", "title", "start_time", "end_time", "item_type", "speaker_name"]

# Events
class EventListSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    concurrent_viewers = serializers.SerializerMethodField()
    playback_urls = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id", "title", "description", "status", "schedule_type",
            "scheduled_start", "scheduled_end",
            "stream_start_time", "playback_urls",
            "created_by_name", "concurrent_viewers",
            "created_at",
        ]

    def get_created_by_name(self, obj):
        return f"{obj.created_by.first_name} {obj.created_by.last_name}"

    def get_concurrent_viewers(self, obj):
        return obj.viewer_sessions.filter(left_at=None).count()

    def get_playback_urls(self, obj):
        return [
            build_playback_urls(stream_key)
            for stream_key in obj.broadcast_sessions.values_list("stream_key", flat=True)
        ]

class EventDetailSerializer(EventListSerializer):
    broadcast_sessions = serializers.SerializerMethodField()
    days = EventDaySerializer(many=True, read_only=True)

    class Meta(EventListSerializer.Meta):
        # "scheduled_end" intentionally not repeated here — it's already
        # inherited from EventListSerializer.Meta.fields
        fields = [field for field in EventListSerializer.Meta.fields if field != "playback_urls"] + [
            "video_muted_by_default", "pause_continue_enabled",
            "allowed_travel", "allowed_medical", "allowed_translation",
            "allowed_accommodation", "stream_end_time", "recording_url",
            "broadcast_sessions", "days", "updated_at",
        ]

    def get_broadcast_sessions(self, obj):
        request = self.context.get("request")
        return [
            self._broadcast_session_data(session, request)
            for session in obj.broadcast_sessions.all()
        ]

    def _broadcast_session_data(self, session, request):
        data = {
            "id": session.id,
            "name": session.name,
            "is_primary": session.is_primary,
            "is_active": session.is_active,
            "playback_url": session.playback_url,
            "playback_urls": build_playback_urls(session.stream_key),
            "started_at": session.started_at,
            "ended_at": session.ended_at,
        }

        if request and request.user.is_authenticated and (
            request.user == session.broadcaster
            or request.user.role in ("EVENT_ADMIN", "SUPER_ADMIN")
        ):
            data.update({
                "stream_key": session.stream_key,
                "ingest_urls": build_ingest_urls(session.stream_key),
                "started_at": session.started_at,
            })
        return data

class EventCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id",
            "title", "description", "schedule_type",
            "scheduled_start", "scheduled_end",
            "allowed_travel", "allowed_medical",
            "allowed_translation","allowed_accommodation", 
            "video_muted_by_default", "pause_continue_enabled",
        ]
        read_only_fields = ["id"]

    def validate(self, data):
        start = data.get("scheduled_start", getattr(self.instance, "scheduled_start", None))
        end = data.get("scheduled_end", getattr(self.instance, "scheduled_end", None))
        schedule_type = data.get("schedule_type", getattr(self.instance, "schedule_type", None))

        if start and end:
            if end < start:
                raise serializers.ValidationError("scheduled_end must be after scheduled_start.")
            if schedule_type == EventScheduleType.WHOLE_DAY and end.time() <= start.time():
                raise serializers.ValidationError(
                    "For whole-day events, scheduled_end time must be after scheduled_start time."
                )
        return data

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        event = super().create(validated_data)
        event.generate_days()
        return event

    def update(self, instance, validated_data):
        # If the date range or schedule_type changes, regenerate any missing
        # EventDay rows. generate_days() is idempotent — it only creates
        # dates that don't already exist, so in-progress MULTI_SESSION
        # schedules on existing days are never touched or wiped.
        date_or_type_changed = any(
            field in validated_data and validated_data[field] != getattr(instance, field)
            for field in ("scheduled_start", "scheduled_end", "schedule_type")
        )
        event = super().update(instance, validated_data)
        if date_or_type_changed:
            event.generate_days()
        return event

class StreamRecordingSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="session.day.date", read_only=True)
    session_title = serializers.CharField(source="session.title", read_only=True)

    class Meta:
        model = StreamRecording
        fields = [
            "id",
            "session",
            "date",
            "session_title",
            "started_at",
            "ended_at",
            "file",
            "file_url",
            "status",
        ]
        read_only_fields = ["id", "started_at", "date", "session_title"]

    def validate_session(self, session):
        event = self.context.get("event")
        day = self.context.get("day")
        if day is not None and session.day_id != day.id:
            raise serializers.ValidationError(
                "This session does not belong to the day in the URL."
            )
        if event is not None and session.day.event_id != event.id:
            raise serializers.ValidationError(
                "This session does not belong to the event in the URL."
            )
        if self.instance is None and StreamRecording.objects.filter(session=session).exists():
            raise serializers.ValidationError(
                "This session already has a recording."
            )
        return session

    def validate_status(self, value):
        # Adjust "stopped"/"failed" to match your RecordingStatus enum values.
        terminal_statuses = {"stopped", "failed"}
        if self.instance and self.instance.status in terminal_statuses and value != self.instance.status:
            raise serializers.ValidationError(
                "Cannot change the status of a recording that has already ended."
            )
        return value

    def validate(self, attrs):
        ended_at = attrs.get("ended_at", getattr(self.instance, "ended_at", None))
        started_at = getattr(self.instance, "started_at", None)
        if ended_at and started_at and ended_at <= started_at:
            raise serializers.ValidationError({"ended_at": "ended_at must be after started_at."})
        return attrs
    
class BroadcastSessionSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)
    broadcaster_name = serializers.SerializerMethodField()
    ingest_urls = serializers.SerializerMethodField()
    playback_urls = serializers.SerializerMethodField()

    class Meta:
        model = BroadcastSession
        fields = [
            "id", "event", "event_title", "broadcaster", "broadcaster_name",
            "name", "is_primary", "stream_key", "ingest_url", "playback_url",
            "ingest_urls", "playback_urls", "allow_viewer_recording", "is_recording",
            "is_active", "started_at", "ended_at", "created_at",
        ]
        read_only_fields = [
            "ingest_url", "playback_url",
            "stream_key", "ingest_urls", "playback_urls",
            "is_recording", "recordings", "is_active",
            "started_at", "ended_at", "created_at",
        ]

    def get_broadcaster_name(self, obj):
        return f"{obj.broadcaster.first_name} {obj.broadcaster.last_name}"

    def get_ingest_urls(self, obj):
        return build_ingest_urls(obj.stream_key)

    def get_playback_urls(self, obj):
        return build_playback_urls(obj.stream_key)

class BroadcastSessionCreateSerializer(serializers.ModelSerializer):
    """Minimal input — stream_key/ingest_url/playback_url are generated by
    BroadcastSession.save() itself, never accepted from the client."""

    class Meta:
        model = BroadcastSession
        fields = [
            "id", "event", "broadcaster", "name", "is_primary",
            "stream_key", "ingest_url", "playback_url",
        ]
        read_only_fields = ["stream_key", "ingest_url", "playback_url"]

    def validate_broadcaster(self, broadcaster):
        if broadcaster.role not in (
            UserRole.EVENT_ADMIN, UserRole.SUPER_ADMIN, UserRole.MODERATOR,
        ):
            raise serializers.ValidationError("This user is not eligible to broadcast.")
        return broadcaster

    def validate(self, attrs):
        event = attrs.get("event") or getattr(self.instance, "event", None)
        if not event:
            raise serializers.ValidationError({"event": "This field is required."})

        if event.status == EventStatus.LIVE:
            raise serializers.ValidationError(
                "Cannot add a broadcast session while the event is live. End the stream first."
            )

        name = attrs.get("name", "Camera 1")
        qs = BroadcastSession.objects.filter(event=event, name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"name": "A camera with this name already exists for this event."}
            )
        return attrs

    def create(self, validated_data):
        event = validated_data["event"]
        if not event.broadcast_sessions.exists():
            validated_data["is_primary"] = True
        return super().create(validated_data)

class CameraSelectSerializer(serializers.Serializer):
    """Validates ?camera_id= / ?camera= query params used to pick a session
    for the broadcast/watch endpoints — previously passed straight from
    request.query_params.get(...) with no type or exclusivity check."""

    camera_id = serializers.IntegerField(required=False)
    camera = serializers.CharField(required=False, max_length=100)

    def validate(self, attrs):
        if attrs.get("camera_id") and attrs.get("camera"):
            raise serializers.ValidationError("Provide either camera_id or camera, not both.")
        return attrs

    def select(self, sessions):
        camera_id = self.validated_data.get("camera_id")
        camera_name = self.validated_data.get("camera")
        if camera_id:
            return sessions.filter(id=camera_id).first()
        if camera_name:
            return sessions.filter(name=camera_name).first()
        return sessions.order_by("-is_primary", "id").first()

class GoLiveSerializer(serializers.Serializer):
    """No client input — validates event/session state before go_live proceeds."""

    def validate(self, attrs):
        event = self.context["event"]
        if event.status == EventStatus.LIVE:
            raise serializers.ValidationError("Event is already live.")
        if not event.broadcast_sessions.exists():
            raise serializers.ValidationError("No broadcast session configured. Create one first.")
        return attrs

class EndStreamSerializer(serializers.Serializer):
    def validate(self, attrs):
        event = self.context["event"]
        if event.status != EventStatus.LIVE:
            raise serializers.ValidationError("Event is not live.")
        return attrs

# ViewerSession
class ViewerSessionSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    watch_duration_minutes = serializers.SerializerMethodField()
    day_date = serializers.CharField(source="day.date", read_only=True, default=None)
    session_title = serializers.CharField(source="session.title", read_only=True, default=None)

    class Meta:
        model = ViewerSession
        fields = [
            "id", "user", "user_name", "event",
            "day", "day_date", "session", "session_title",
            "joined_at", "left_at", "is_active",
            "watch_duration_seconds", "watch_duration_minutes",
            "last_heartbeat", "ip_address", "latitude", "longitude",
            "location_accuracy", "state", "country",
        ]
        read_only_fields = fields

    def get_watch_duration_minutes(self, obj):
        return round(obj.watch_duration_seconds / 60, 1)
    
class ViewerSessionLocationSerializer(serializers.Serializer):
    """Input validation for POST /events/{id}/join/."""
    ip_address = serializers.IPAddressField()
    session_id = serializers.IntegerField(required=False, allow_null=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    location_accuracy = serializers.FloatField(required=False, allow_null=True)
    state = serializers.CharField(required=False, allow_blank=True, max_length=100)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_latitude(self, value):
        if value is not None and not (-90 <= value <= 90):
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if value is not None and not (-180 <= value <= 180):
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return value

    def validate_session_id(self, value):
        if value is None:
            return value
        event = self.context["event"]
        if not event.schedule_items.filter(pk=value).exists():
            raise serializers.ValidationError("Session not found for this event.")
        return value

    def validate(self, attrs):
        has_lat = attrs.get("latitude") is not None
        has_lng = attrs.get("longitude") is not None
        if has_lat != has_lng:
            raise serializers.ValidationError("Both latitude and longitude are required together.")
        if attrs.get("location_accuracy") is not None and not has_lat:
            raise serializers.ValidationError(
                {"location_accuracy": "Requires latitude/longitude to be set."}
            )
        return attrs
    
class ViewerJoinSerializer(serializers.Serializer):
    event_id = serializers.IntegerField()
    day_id = serializers.IntegerField(allow_null=True)
    session_id = serializers.IntegerField(allow_null=True)
    event_title = serializers.CharField()
    broadcast_sessions = BroadcastSessionSerializer(many=True)
    viewer_session_id = serializers.IntegerField()
    concurrent_viewers = serializers.IntegerField()
    video_muted_by_default = serializers.BooleanField()\

class HeartbeatSerializer(serializers.Serializer):
    """Validates session state for POST /events/{id}/heartbeat/ and formats
    the response — previously the view just returned a raw dict."""

    status = serializers.CharField(read_only=True)
    watch_duration_seconds = serializers.IntegerField(read_only=True)

    def validate(self, attrs):
        session = self.context["session"]
        if session.left_at is not None:
            raise serializers.ValidationError("Session has already ended.")
        return attrs

# Webhook (inbound from media server)
class StreamWebhookSerializer(serializers.Serializer):
    ACTIONS = ["stream.started", "stream.ended", "stream.error"]

    action = serializers.ChoiceField(choices=ACTIONS)
    stream_key = serializers.CharField()
    timestamp = serializers.DateTimeField(required=False)

    def validate_stream_key(self, value):
        try:
            self._broadcast_session = BroadcastSession.objects.select_related("event").get(
                stream_key=value
            )
        except BroadcastSession.DoesNotExist:
            raise serializers.ValidationError("Invalid stream key.")
        return value

    @property
    def broadcast_session(self):
        return self._broadcast_session

# Analytics
class EventAnalyticsSerializer(serializers.Serializer):
    event_id = serializers.IntegerField()
    event_title = serializers.CharField()
    status = serializers.CharField()
    total_joins = serializers.IntegerField()
    concurrent_viewers = serializers.IntegerField()
    peak_viewers = serializers.IntegerField()
    avg_watch_duration_minutes = serializers.FloatField()
    stream_duration_minutes = serializers.FloatField(allow_null=True)

class EventSummarySerializer(serializers.Serializer):
    total_registered_users = serializers.IntegerField(read_only=True)
    participants_attended = serializers.IntegerField(read_only=True)
    participants_accepted = serializers.IntegerField(read_only=True)
    participants_rejected = serializers.IntegerField(read_only=True)
    participants_pending = serializers.IntegerField(read_only=True)
    participants_hold = serializers.IntegerField(read_only=True)

class UpcomingEventSerializer(serializers.ModelSerializer):
    is_registered = serializers.BooleanField(read_only=True)
    summary = EventSummarySerializer(source="*", read_only=True)

    class Meta:
        model = Event
        fields = "__all__"

class FeedbackSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)
    event_day_date = serializers.DateField(source="event_date.date", read_only=True)
    schedule_item_title = serializers.CharField(source="schedule_item.title", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_phone = serializers.CharField(source="user.phone_number", read_only=True)

    class Meta:
        model = Feedback
        fields = [
            "id", "event", "event_title", "event_date", "event_day_date",
            "schedule_item", "schedule_item_title", "is_overall_rating",
            "user", "user_full_name", "user_email","user_phone",
            "rating", "comment", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def validate(self, attrs):
        request = self.context["request"]
        user = getattr(self.instance, "user", None) or request.user

        event = attrs.get("event") or getattr(self.instance, "event", None)
        event_date = attrs.get("event_date", getattr(self.instance, "event_date", None))
        schedule_item = attrs.get("schedule_item", getattr(self.instance, "schedule_item", None))

        is_overall_rating = attrs.get(
            "is_overall_rating", getattr(self.instance, "is_overall_rating", False)
        )

        if not event:
            raise serializers.ValidationError({"event": "This field is required."})

        # overall/session shape must match schedule_item presence
        if is_overall_rating and schedule_item:
            raise serializers.ValidationError(
                {"schedule_item": "Must be null when is_overall_rating is True."}
            )
        if not is_overall_rating and not schedule_item:
            raise serializers.ValidationError(
                {"schedule_item": "This field is required unless is_overall_rating is True."}
            )

        # consistency checks across the FK chain
        if schedule_item and schedule_item.day.event_id != event.id:
            raise serializers.ValidationError(
                {"schedule_item": "Schedule item does not belong to the specified event."}
            )
        if event_date and event_date.event_id != event.id:
            raise serializers.ValidationError(
                {"event_date": "Event date does not belong to the specified event."}
            )
        if schedule_item and event_date and schedule_item.day_id != event_date.id:
            raise serializers.ValidationError(
                {"schedule_item": "Schedule item does not belong to the specified event date."}
            )

        # uniqueness (mirrors the DB UniqueConstraints, raised cleanly here instead of IntegrityError)
        qs = Feedback.objects.exclude(pk=getattr(self.instance, "pk", None))
        if is_overall_rating:
            if qs.filter(event=event, user=user, is_overall_rating=True).exists():
                raise serializers.ValidationError(
                    "You have already submitted an overall rating for this event."
                )
        else:
            if qs.filter(schedule_item=schedule_item, user=user, is_overall_rating=False).exists():
                raise serializers.ValidationError(
                    "You have already rated this session."
                )

        # attendance-based eligibility
        if schedule_item:
            if not self.user_can_rate_schedule_item(user, schedule_item):
                raise serializers.ValidationError(
                    "You can only rate sessions you attended."
                )
        else:
            if not self.user_attended_event(user, event, event_date):
                raise serializers.ValidationError(
                    "You can only rate events you attended."
                )

        return attrs

    def user_can_rate_schedule_item(self, user, schedule_item):
        return RegistrationSession.objects.filter(
            registration__user=user,
            session=schedule_item,
            status=RegistrationStatus.ACCEPTED,
        ).exists()

    def user_attended_event(self, user, event, event_date=None):
        qs = RegistrationDay.objects.filter(
            registration__user=user,
            registration__event=event,
            is_attended=True,
        )
        if event_date:
            qs = qs.filter(day=event_date)
        return qs.exists()

    def user_can_rate_schedule_item(self, user, schedule_item):
        return RegistrationSession.objects.filter(
            registration__user=user,
            session=schedule_item,
            status=RegistrationStatus.ACCEPTED,
        ).exists()

    def user_attended_event(self, user, event_date):
        qs = RegistrationDay.objects.filter(
            registration__user=user,
            day=event_date,
            is_attended=True,
        )
        return qs.exists()

# Chats
class ReplyPreviewSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.full_name", read_only=True)

    class Meta:
        model = ChatMessage
        fields = ["id", "sender", "sender_name", "message", "is_deleted"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_deleted:
            data["message"] = "This message was deleted."
        return data

class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.full_name", read_only=True)
    reply_to = ReplyPreviewSerializer(read_only=True)
    reactions = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id", "event", "sender", "sender_name", "message",
            "reply_to", "reactions", "created_at", "edited_at", "is_deleted",
        ]
        read_only_fields = fields

    def get_reactions(self, obj):
        """Grouped by type: [{"reaction": "love", "count": 3, "sender_ids": [...]}, ...].
        sender_ids lets each client derive its own reaction state without a
        per-user query."""
        grouped = {}
        for r in obj.reactions.all():
            grouped.setdefault(r.reaction_type, []).append(r.sender_id)
        return [
            {"reaction": reaction_type, "count": len(sender_ids), "sender_ids": sender_ids}
            for reaction_type, sender_ids in grouped.items()
        ]