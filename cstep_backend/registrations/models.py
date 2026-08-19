from django.db import models,transaction
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from events.constants import ScheduleItemType
from events.models import ScheduleItem,EventDay
from .constants import (
    TransportMode,
    TranslationLanguage,
    RegistrationStatus,
    ApprovalStatus,
    AttendanceMode
)

class Registration(models.Model):
    """Top-level record: one user x one event."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="registrations"
    )
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="registrations")
    status = models.CharField(
        max_length=20, choices=RegistrationStatus.choices, default=RegistrationStatus.ACCEPTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # class Meta:
    #     constraints = [
    #         models.UniqueConstraint(fields=["user", "event"], name="unique_user_event_registration"),
    #     ]

    def create_registration(self, attendance_modes, day_ids=None, session_ids=None):
        """
        Call from serializer.create() — registration is brand new,
        so this is purely additive (nothing to reconcile/remove).
        """
        with transaction.atomic():
            mode_lookup = {
                int(item["day_id"]): item["attendance_mode"]
                for item in attendance_modes
            }
            day_ids_involved = list(mode_lookup.keys())

            event_days = {
                d.id: d for d in EventDay.objects.filter(id__in=day_ids_involved)
            }

            missing_day_ids = set(day_ids_involved) - set(event_days.keys())
            if missing_day_ids:
                raise ValidationError({
                    "day": f"Day id(s) {sorted(missing_day_ids)} do not exist."
                })

            days_to_create = []
            for day_id, attendance_mode in mode_lookup.items():
                day = event_days[day_id]

                if day.event_id != self.event_id:
                    raise ValidationError({"day": f"Day {day_id} does not belong to this event."})
                if attendance_mode not in day.allowed_attendance_modes:
                    raise ValidationError({
                        "attendance_mode": (
                            f"'{attendance_mode}' not allowed for day {day_id}. "
                            f"Allowed: {day.allowed_attendance_modes}"
                        )
                    })

                days_to_create.append(
                    RegistrationDay(registration=self, day_id=day_id, attendance_mode=attendance_mode)
                )

            if days_to_create:
                RegistrationDay.objects.bulk_create(days_to_create)

            registered_day_ids = set(day_ids_involved)

            if session_ids:
                requested_session_ids = set(session_ids)
                sessions = list(
                    ScheduleItem.objects.filter(
                        id__in=requested_session_ids, item_type=ScheduleItemType.SESSION
                    ).select_related("day")
                )
                found_ids = {s.id for s in sessions}
                invalid_ids = requested_session_ids - found_ids
                if invalid_ids:
                    raise ValidationError({
                        "session_ids": f"Session id(s) {sorted(invalid_ids)} are invalid or not SESSION-type items."
                    })
            elif day_ids:
                sessions = list(
                    ScheduleItem.objects.filter(
                        day_id__in=day_ids, item_type=ScheduleItemType.SESSION
                    ).select_related("day")
                )
            else:
                sessions = []

            sessions_to_create = []
            invalid_day_sessions = []
            for session in sessions:
                if session.day_id not in registered_day_ids:
                    invalid_day_sessions.append((session.id, session.day_id))
                    continue
                sessions_to_create.append(RegistrationSession(registration=self, session=session))

            if invalid_day_sessions:
                raise ValidationError({
                    "session": [
                        f"Register for day {day_id} before registering for session {session_id}."
                        for session_id, day_id in invalid_day_sessions
                    ]
                })

            if sessions_to_create:
                RegistrationSession.objects.bulk_create(sessions_to_create, ignore_conflicts=True)

        return self

    def update_registration(self, attendance_modes, day_ids=None, session_ids=None):
        """
        Call from serializer.update() — payload is treated as the full
        desired state. Days/sessions not included are REMOVED.
        """
        with transaction.atomic():
            mode_lookup = {
                int(item["day_id"]): item["attendance_mode"]
                for item in attendance_modes
            }
            day_ids_involved = list(mode_lookup.keys())

            event_days = {
                d.id: d for d in EventDay.objects.filter(id__in=day_ids_involved)
            }

            missing_day_ids = set(day_ids_involved) - set(event_days.keys())
            if missing_day_ids:
                raise ValidationError({
                    "day": f"Day id(s) {sorted(missing_day_ids)} do not exist."
                })

            existing_days = {
                rd.day_id: rd
                for rd in RegistrationDay.objects.filter(registration=self)
            }

            days_to_create, days_to_update = [], []
            for day_id, attendance_mode in mode_lookup.items():
                day = event_days[day_id]

                if day.event_id != self.event_id:
                    raise ValidationError({"day": f"Day {day_id} does not belong to this event."})
                if attendance_mode not in day.allowed_attendance_modes:
                    raise ValidationError({
                        "attendance_mode": (
                            f"'{attendance_mode}' not allowed for day {day_id}. "
                            f"Allowed: {day.allowed_attendance_modes}"
                        )
                    })

                if day_id in existing_days:
                    rd = existing_days[day_id]
                    rd.attendance_mode = attendance_mode
                    days_to_update.append(rd)
                else:
                    days_to_create.append(
                        RegistrationDay(registration=self, day_id=day_id, attendance_mode=attendance_mode)
                    )

            if days_to_create:
                RegistrationDay.objects.bulk_create(days_to_create)
            if days_to_update:
                RegistrationDay.objects.bulk_update(days_to_update, ["attendance_mode", "updated_at"])

            # remove days that existed before but weren't included in this update
            stale_day_ids = set(existing_days.keys()) - set(day_ids_involved)
            if stale_day_ids:
                RegistrationDay.objects.filter(
                    registration=self, day_id__in=stale_day_ids
                ).delete()

            registered_day_ids = set(day_ids_involved)

            if session_ids:
                requested_session_ids = set(session_ids)
                sessions = list(
                    ScheduleItem.objects.filter(
                        id__in=requested_session_ids, item_type=ScheduleItemType.SESSION
                    ).select_related("day")
                )
                found_ids = {s.id for s in sessions}
                invalid_ids = requested_session_ids - found_ids
                if invalid_ids:
                    raise ValidationError({
                        "session_ids": f"Session id(s) {sorted(invalid_ids)} are invalid or not SESSION-type items."
                    })
            elif day_ids:
                sessions = list(
                    ScheduleItem.objects.filter(
                        day_id__in=day_ids, item_type=ScheduleItemType.SESSION
                    ).select_related("day")
                )
            else:
                sessions = []

            existing_session_ids = set(
                RegistrationSession.objects.filter(
                    registration=self, session_id__in=[s.id for s in sessions]
                ).values_list("session_id", flat=True)
            )

            sessions_to_create = []
            invalid_day_sessions = []
            for session in sessions:
                if session.day_id not in registered_day_ids:
                    invalid_day_sessions.append((session.id, session.day_id))
                    continue
                if session.id not in existing_session_ids:
                    sessions_to_create.append(RegistrationSession(registration=self, session=session))

            if invalid_day_sessions:
                raise ValidationError({
                    "session": [
                        f"Register for day {day_id} before registering for session {session_id}."
                        for session_id, day_id in invalid_day_sessions
                    ]
                })

            if sessions_to_create:
                RegistrationSession.objects.bulk_create(sessions_to_create, ignore_conflicts=True)

            # remove sessions on registered days that aren't in the requested set
            requested_session_ids_final = {s.id for s in sessions}
            RegistrationSession.objects.filter(
                registration=self,
                session__day_id__in=registered_day_ids,
            ).exclude(session_id__in=requested_session_ids_final).delete()

        return self
        
    def bulk_update_status(self, status):
        """
        Update this registration and cascade the status
        to all related registration days and sessions.
        """
        with transaction.atomic():
            now = timezone.now()

            self.status = status
            self.updated_at = now
            self.full_clean()
            self.save(update_fields=["status", "updated_at"])

            # RegistrationDay.objects.filter(
            #     registration=self
            # ).update(
            #     status=status,
            #     updated_at=now,
            # )
            RegistrationSession.objects.filter(
                registration=self
            ).update(
                status=status,
                updated_at=now,
            )

        return self
    
    def __str__(self):
        return f"{self.user} — {self.event.title}"

class RegistrationDay(models.Model):
    """
    Attendance-mode choice for a WHOLE_DAY (or MULTI_SESSION) day.
    One row per registration per EventDay.
    """
    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name="days")
    day = models.ForeignKey("events.EventDay", on_delete=models.CASCADE, related_name="registration_days")
    attendance_mode = models.CharField(max_length=20, choices=AttendanceMode.choices,default=AttendanceMode.VIRTUAL)
    is_attended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["registration", "day"], name="unique_registration_day"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.day.event_id != self.registration.event_id:
            errors["day"] = "Day does not belong to the registration's event."

        if self.attendance_mode not in self.day.allowed_attendance_modes:
            errors["attendance_mode"] = (
                f"'{self.attendance_mode}' is not allowed for this day. "
                f"Allowed: {', '.join(self.day.allowed_attendance_modes)}."
            )

        # if self.day.attendance_capacity is not None:
        #     current_count = (
        #         RegistrationDay.objects.filter(
        #             day=self.day, status=RegistrationStatus.ACCEPTED
        #         )
        #         .exclude(pk=self.pk)
        #         .count()
        #     )
        #     if current_count >= self.day.attendance_capacity:
        #         errors["day"] = f"Day '{self.day}' has reached its attendance capacity."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.registration.user} — {self.day} ({self.attendance_mode})"

class RegistrationSession(models.Model):
    """
    Session-level registration — only valid for ScheduleItemType.SESSION items,
    used directly for MULTI_SESSION events and via _resolve_day_ids_to_session_ids
    for WHOLE_DAY events.
    """
    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name="sessions")
    session = models.ForeignKey(
        "events.ScheduleItem",
        on_delete=models.CASCADE,
        related_name="registrations",
        limit_choices_to={"item_type": ScheduleItemType.SESSION},
    )
    status = models.CharField(
        max_length=20, choices=RegistrationStatus.choices, default=RegistrationStatus.ACCEPTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["registration", "session"], name="unique_registration_session"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.session.item_type != ScheduleItemType.SESSION:
            errors["session"] = "Only SESSION-type schedule items can be registered for."

        if self.session.day.event_id != self.registration.event_id:
            errors["session"] = "Session does not belong to the registration's event."

        if not RegistrationDay.objects.filter(
            registration=self.registration, day=self.session.day
        ).exists():
            errors["session"] = "Register for the day before registering for a session on it."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.registration.user} — {self.session.title}"

class AccommodationAssistance(models.Model):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.CASCADE,
        related_name="accommodation_assistance",
    )
    hotel_name = models.CharField(max_length=255)
    address = models.TextField(null=True, blank=True)
    room_no = models.CharField(max_length=50, blank=True, default="")
    from_date = models.DateField()
    to_date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        errors = {}

        if not self.registration.event.allowed_travel:
            errors["registration"] = "Travel assistance is not allowed for this event."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Travel @ {self.hotel_name} [{self.room_no}] - {self.registration}"

class TravelAssistance(models.Model):
    registration = models.ForeignKey(
        Registration,
        on_delete=models.CASCADE,
        related_name="travel_assistance",
    )
    transport_mode = models.CharField(max_length=20, choices=TransportMode.choices)

    source_location = models.CharField(max_length=255, blank=True, default="")
    destination_location = models.CharField(max_length=255, blank=True, default="")
    travel_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
    
    def clean(self):
        super().clean()
        errors = {}

        if not self.registration.event.allowed_medical:
            errors["registration"] = "Travel assistance is not allowed for this event."

        if errors:
            raise ValidationError(errors)
        
    def __str__(self):
        return f"Travel ({self.transport_mode}) - {self.registration}"

class MedicalAssistance(models.Model):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.CASCADE,
        related_name="medical_assistance",
    )
    medical_needs = models.TextField(
        help_text="e.g. wheelchair accessibility, medications, emergency contact"
    )
    date = models.DateField()
    status = models.CharField(max_length=10, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
    
    def clean(self):
        super().clean()
        errors = {}

        if not self.registration.event.allowed_translation:
            errors["registration"] = "Medical assistance is not allowed for this event."

        if errors:
            raise ValidationError(errors)
        
    def __str__(self):
        return f"Medical - {self.registration}"

class TranslationAssistance(models.Model):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.CASCADE,
        related_name="translation_assistance",
    )
    language = models.CharField(max_length=20, choices=TranslationLanguage.choices)
    date = models.DateField()
    status = models.CharField(max_length=10, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        errors = {}

        if not self.registration.event.allowed_accommodation:
            errors["registration"] = "Translation assistance is not allowed for this event."

        if errors:
            raise ValidationError(errors)
        
    def __str__(self):
        return f"Translation ({self.language}) - {self.registration}"