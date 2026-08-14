from datetime import timedelta
import secrets
from django.db import models,transaction
from django.db.models import Q
from django.contrib.postgres.fields import ArrayField
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from .media import build_whip_ingest_url, build_whep_playback_url
from .constants import EventScheduleType, EventStatus, RecordingStatus,ScheduleItemType,default_attendance_modes
from registrations.constants import AttendanceMode

class Event(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DRAFT)
    schedule_type = models.CharField(
            max_length=20, choices=EventScheduleType.choices, default=EventScheduleType.WHOLE_DAY
        )
    video_muted_by_default = models.BooleanField(default=True)
    pause_continue_enabled = models.BooleanField(default=True)

    allowed_travel = models.BooleanField(default=True)
    allowed_medical = models.BooleanField(default=True)
    allowed_translation = models.BooleanField(default=True)
    allowed_accommodation = models.BooleanField(default=True)
    
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)

    stream_start_time = models.DateTimeField(null=True, blank=True)
    stream_end_time = models.DateTimeField(null=True, blank=True)

    # Denormalized copy of the primary camera playback URL, set on go_live.
    # Kept here so EventListSerializer can show it without joining broadcast_sessions.
    playback_url = models.URLField(blank=True)
    recording_url = models.URLField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_events"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["status", "scheduled_start"]),
            models.Index(fields=["created_by", "-created_at"]),
        ]

    def __str__(self):
        return self.title

    @property
    def primary_broadcast_session(self):
        return self.broadcast_sessions.order_by("-is_primary", "id").first()

    @property
    def broadcast_session(self):
        """
        Backward-compatible alias for code that previously expected one
        broadcast session per event.
        """
        return self.primary_broadcast_session

    def generate_days(self):
        """
        Idempotent: safe to call again if dates change — only creates
        missing EventDay rows, never duplicates or deletes existing ones.
        Call this after scheduled_start/scheduled_end/schedule_type are set.
        """
        if not self.scheduled_start or not self.scheduled_end:
            return

        start_date = self.scheduled_start.date()
        end_date = self.scheduled_end.date()
        daily_start_time = self.scheduled_start.time()
        daily_end_time = self.scheduled_end.time()

        existing_dates = set(self.days.values_list("date", flat=True))
        day_number = self.days.count() + 1
        current = start_date

        with transaction.atomic():
            while current <= end_date:
                if current not in existing_dates:
                    day = EventDay.objects.create(
                        event=self, date=current, day_number=day_number
                    )
                    if self.schedule_type == EventScheduleType.WHOLE_DAY:
                        ScheduleItem.objects.create(
                            day=day,
                            item_type=ScheduleItemType.SESSION,
                            title=f"{self.title} — Day {day_number}",
                            start_time=daily_start_time,
                            end_time=daily_end_time,
                            order=0,
                            track="main",
                        )
                    # MULTI_SESSION: day created empty, admin builds schedule via
                    # the timeline UI / ScheduleItem endpoints afterward
                    day_number += 1
                current += timedelta(days=1)

class EventDay(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="days")
    date = models.DateField()
    day_number = models.PositiveIntegerField(null=True,blank=True)
    label = models.CharField(max_length=100, blank=True)  # "Day 1 - Registration & Keynote"
    allowed_attendance_modes = ArrayField(
        models.CharField(
            max_length=20,
            choices=AttendanceMode.choices,
        ),
        default=default_attendance_modes,
        blank=True,
        help_text="Attendance modes users can choose for this event.",
    )
    class Meta:
        ordering = ["day_number"]
        constraints = [
            models.UniqueConstraint(fields=["event", "date"], name="unique_event_date"),
        ]
        indexes = [
            models.Index(fields=["event", "day_number"]),
        ]

    def __str__(self):
        return f"{self.event.title} — Day {self.day_number} ({self.date})"
    
    def clean(self):
        # date uniqueness per event, excluding self
        qs = EventDay.objects.filter(event=self.event, date=self.date).exclude(pk=self.pk)
        if qs.exists():
            raise ValidationError({"date": "This event already has a day on this date."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def resequence(cls, event_id):
        """Reassign day_number sequentially (1, 2, 3...) by date order."""
        days = list(cls.objects.filter(event_id=event_id).order_by("date"))
        for i, day in enumerate(days, start=1):
            if day.day_number != i:
                cls.objects.filter(pk=day.pk).update(day_number=i)

class ScheduleItem(models.Model):
    """
    A single block on the timeline: either a session or a break.
    Unified model so drag-and-drop reordering / time-shifting works
    identically for both, and so a break can sit between two sessions
    in the same ordered list.
    """
    day = models.ForeignKey(EventDay, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=30, choices=ScheduleItemType.choices)

    title = models.CharField(max_length=255)          # "Session 1: Keynote" / "Breakfast Break"
    description = models.TextField(blank=True)

    start_time = models.TimeField()
    end_time = models.TimeField()

    order = models.PositiveIntegerField(default=0)     # persisted drag-drop order within a track
    track = models.CharField(max_length=100, blank=True, default="main")  # parallel tracks/rooms
    room = models.CharField(max_length=100, blank=True)

    # Session-only fields — blank for breaks
    speaker_name = models.CharField(max_length=255, blank=True)

    # Networking-break-only field
    allow_networking = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["day", "track", "order", "start_time"]
        indexes = [
            models.Index(fields=["day", "track", "order"]),
            models.Index(fields=["item_type"]),
        ]

    @classmethod
    def resequence(cls, day):
        """
        Re-number `order` for all schedule items on the given day,
        ordered by start_time and id.
        """
        items = cls.objects.filter(day=day).order_by("start_time", "id")

        updates = []
        for index, item in enumerate(items, start=1):
            if item.order != index:
                item.order = index
                updates.append(item)

        if updates:
            cls.objects.bulk_update(updates, ["order"])

    @classmethod
    def overlapping(cls, day, track, start_time, end_time, exclude_pk=None):
        """The one and only overlap query. Everyone else calls this."""
        qs = cls.objects.filter(
            day=day, track=track,
            start_time__lt=end_time, end_time__gt=start_time,
        )
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        return qs
    
    def clean(self):
        super().clean()
        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "End time must be after start time."})

        conflicts = self.overlapping(self.day, self.track, self.start_time, self.end_time, exclude_pk=self.pk)

        errors = {}
        for item in conflicts:
            # new start falls inside an existing item's range
            if item.start_time <= self.start_time < item.end_time:
                errors.setdefault("start_time", (
                    f"Start time overlaps with '{item.title}' "
                    f"({item.start_time}–{item.end_time})."
                ))
            # new end falls inside an existing item's range
            if item.start_time < self.end_time <= item.end_time:
                errors.setdefault("end_time", (
                    f"End time overlaps with '{item.title}' "
                    f"({item.start_time}–{item.end_time})."
                ))
            # new item fully swallows an existing one — neither edge lands inside it,
            # but it's still a conflict, so fall back to start_time
            if self.start_time <= item.start_time and self.end_time >= item.end_time:
                errors.setdefault("start_time", (
                    f"This time range fully overlaps '{item.title}' "
                    f"({item.start_time}–{item.end_time})."
                ))

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        title = f"{self.title[:20]}..." if len(self.title) > 20 else self.title
        return f"{title:} — Day {self.day.day_number} ({self.day.date})|{self.start_time} - {self.end_time})"

class BroadcastSession(models.Model):
    """
    One per live event. WHIP ingest / WHEP playback URLs are generated
    automatically on first save — never accept these from a client.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="broadcast_sessions")
    broadcaster = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="broadcast_sessions"
    )

    name = models.CharField(max_length=100, default="Camera 1")
    is_primary = models.BooleanField(default=False)
    stream_key = models.CharField(max_length=64, unique=True, db_index=True, editable=False)
    ingest_url = models.URLField(editable=True)    # WHIP — broadcaster publishes here
    playback_url = models.URLField(editable=True)  # WHEP — viewers subscribe here

    is_active = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    allow_viewer_recording = models.BooleanField(default=False)  # toggled by moderator/admin
    is_recording = models.BooleanField(default=False)            # server-side recording in progress

    ended_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["event"],
                condition=models.Q(is_primary=True),
                name="unique_primary_broadcast_session_per_event",
            )
        ]
        indexes = [
            models.Index(fields=["event", "is_active"]),
        ]

    @staticmethod
    def generate_stream_key() -> str:
        return secrets.token_urlsafe(8)  # 11 chars, ~62^11 combinations 18.4 quintillion

    def save(self, *args, **kwargs):
        if self.is_primary and self.event_id:
            BroadcastSession.objects.filter(event_id=self.event_id, is_primary=True).exclude(pk=self.pk).update(
                is_primary=False
            )
        if not self.stream_key:
            self.stream_key = self.generate_stream_key()
        if not self.ingest_url:
            self.ingest_url = build_whip_ingest_url(self.stream_key)
        if not self.playback_url:
            self.playback_url = build_whep_playback_url(self.stream_key)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} for {self.event.title}"

class ViewerSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="viewer_sessions"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="viewer_sessions")
    day = models.ForeignKey(
        EventDay, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="viewer_sessions"
    )
    session = models.ForeignKey(
        ScheduleItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="viewer_sessions"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_accuracy = models.FloatField(null=True, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100,blank=True)
    user_agent = models.TextField(blank=True)

    last_heartbeat = models.DateTimeField(null=True, blank=True)
    watch_duration_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-joined_at"]
        indexes = [
            models.Index(fields=["event", "left_at"]),
            models.Index(fields=["user", "event"]),
            models.Index(fields=["event", "-joined_at"]),
            models.Index(fields=["session", "left_at"]),
            models.Index(fields=["day", "left_at"]),           # NEW — day-wise active-viewer queries
            models.Index(fields=["event", "day", "left_at"]),  # NEW — combined filter
        ]

    def clean(self):
        super().clean()
        if self.session_id and self.day_id and self.session.day_id != self.day_id:
            raise ValidationError({"day": "day must match session.day when session is set."})

    def save(self, *args, **kwargs):
        if self.session_id and not self.day_id:
            self.day_id = (
                ScheduleItem.objects.filter(pk=self.session_id).values_list("day_id", flat=True).first()
            )
        super().save(*args, **kwargs)
        
    @property
    def is_active(self):
        return self.left_at is None

    def __str__(self):
        return f"{self.user} watching {self.event.title}"

class StreamRecording(models.Model):
    provider_record_id = models.CharField(max_length=64, blank=True)
    broadcast_session = models.ForeignKey(
        BroadcastSession, on_delete=models.CASCADE, related_name="recordings"
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="started_recordings"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    file_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=RecordingStatus.choices, default=RecordingStatus.RECORDING)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["broadcast_session", "status"]),
        ]

    def __str__(self):
        return f"Recording of {self.broadcast_session} [{self.status}]"

class Feedback(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="ratings")
    event_date = models.ForeignKey(
        EventDay, on_delete=models.CASCADE, related_name="ratings", null=True, blank=True
    )
    schedule_item = models.ForeignKey(
        ScheduleItem,
        on_delete=models.CASCADE,
        related_name="ratings",
        null=True,
        blank=True,
        help_text="Null when is_overall_rating is True.",
    )
    is_overall_rating = models.BooleanField(default=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_ratings"
    )
    rating = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        validators=[MinValueValidator(0.5), MaxValueValidator(5.0)],
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["schedule_item", "user"],
                condition=Q(is_overall_rating=False),
                name="one_rating_per_user_per_session",
            ),
            models.UniqueConstraint(
                fields=["event", "user"],
                condition=Q(is_overall_rating=True),
                name="one_overall_rating_per_user_per_event",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_overall_rating=True, schedule_item__isnull=True)
                    | Q(is_overall_rating=False, schedule_item__isnull=False)
                ),
                name="schedule_item_null_iff_overall",
            ),
        ]
        indexes = [
            models.Index(fields=["schedule_item"]),
            models.Index(fields=["event", "is_overall_rating"]),
            models.Index(fields=["user", "event"]),
            models.Index(fields=["event", "-created_at"]),
        ]

    def __str__(self):
        target = "Overall" if self.is_overall_rating else str(self.schedule_item)
        return f"{self.user} — {target} — {self.rating}"

class ChatMessage(models.Model):
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )

    message = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    edited_at = models.DateTimeField(null=True, blank=True)

    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]