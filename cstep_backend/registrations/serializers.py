from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
from django.core.exceptions import ValidationError

from django.db import transaction
from django.db.models import F
from accounts.models import User
from .models import (
    AccommodationAssistance, Registration, RegistrationDay, RegistrationSession,
    TravelAssistance, MedicalAssistance, TranslationAssistance,AttendanceMode,RegistrationStatus
)
from events.models import EventDay,ScheduleItem,EventScheduleType

class AssistanceBaseSerializer(serializers.ModelSerializer):
    one_to_one_models = (MedicalAssistance, TranslationAssistance, AccommodationAssistance)
    event_id = serializers.IntegerField(write_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    event_name = serializers.CharField(source="registration.event.title", read_only=True)
    user_name = serializers.CharField(source="registration.user.full_name", read_only=True)
    user_phone = serializers.CharField(source="registration.user.phone_number", read_only=True)
    user_email = serializers.CharField(source="registration.user.email", read_only=True)

    def validate(self, attrs):
        request = self.context.get("request")
        model = self.Meta.model

        if not self.instance:
            event_id = attrs.pop("event_id", None)
            user_id = attrs.pop("user_id", None) or (request.user.id if request else None)

            if not event_id:
                raise serializers.ValidationError({"event_id": "This field is required for creation."})

            try:
                registration = Registration.objects.get(event_id=event_id, user_id=user_id)
            except Registration.DoesNotExist:
                raise serializers.ValidationError(
                    "No registration found for this user and event."
                )

            if model in self.one_to_one_models:
                if model.objects.filter(registration=registration).exists():
                    raise serializers.ValidationError(
                        f"{model.__name__} already requested for this registration."
                    )

            attrs["registration"] = registration
        return attrs

    def create(self, validated_data):
        instance = self.Meta.model(**validated_data)
        try:
            instance.full_clean()
        except ValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.full_clean()
        instance.save()
        return instance

class AccommodationAssistanceSerializer(AssistanceBaseSerializer):
    class Meta:
        model = AccommodationAssistance
        fields = [
            "id", "event_id", "user_id",
            "event_name", "user_name",
            "user_email", "user_phone",
            "hotel_name", "address", "room_no",
            "from_date", "to_date", "status",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

class TravelAssistanceSerializer(AssistanceBaseSerializer):
    class Meta:
        model = TravelAssistance
        fields = [
            "id", "event_id", "user_id",
            "event_name", "user_name",
            "user_email", "user_phone",
            "transport_mode", "source_location",
            "destination_location", "travel_date",
            "status"
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

class MedicalAssistanceSerializer(AssistanceBaseSerializer):
    class Meta:
        model = MedicalAssistance
        fields = [
            "id", "event_id", "user_id",
            "event_name", "user_name",
            "user_email", "user_phone",
            "medical_needs", "date", "status",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

class TranslationAssistanceSerializer(AssistanceBaseSerializer):
    class Meta:
        model = TranslationAssistance
        fields = [
            "id", "event_id", "user_id",
            "event_name", "user_name",
            "user_email", "user_phone",
            "language", "date", "status",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

class RegistrationSessionSerializer(serializers.ModelSerializer):
    session_title = serializers.CharField(source="session.title", read_only=True)
    date = serializers.DateField(source="session.day.date", read_only=True)
    start_time = serializers.TimeField(source="session.start_time", read_only=True)
    end_time = serializers.TimeField(source="session.end_time", read_only=True)
    track = serializers.CharField(source="session.track", read_only=True)

    class Meta:
        model = RegistrationSession
        fields = [
            "id", "registration", "session", "session_title",
            "date", "start_time", "end_time", "track",
            "status", "created_at",
        ]
        read_only_fields = [
            "id", "registration", "session", "session_title",
            "date", "start_time", "end_time", "track", "created_at",
        ]

class RegistrationDaySerializer(serializers.ModelSerializer):
    sessions = serializers.SerializerMethodField()

    date = serializers.DateField(source="day.date", read_only=True)
    day_number = serializers.IntegerField(source="day.day_number", read_only=True)

    class Meta:
        model = RegistrationDay
        fields = ["id", "registration", "day", "date", "day_number", "attendance_mode", "is_attended", "created_at","sessions"]
        read_only_fields = ["id", "registration", "date", "day_number", "created_at"]
    
    def get_sessions(self, obj):
        day_sessions = obj.registration.sessions.filter(session__day_id=obj.day_id)
        return RegistrationSessionSerializer(day_sessions, many=True).data
    
class RegistrationListSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    registered_sessions_count = serializers.IntegerField(source="sessions.count", read_only=True)
    registration_dates = serializers.SerializerMethodField()

    class Meta:
        model = Registration
        fields = [
            "id", "user", "user_name", "phone_number", "email",
            "event", "registration_dates", "registered_sessions_count",
            "status", "created_at", "updated_at",
        ]
        read_only_fields = fields
        
    def get_registration_dates(self, obj):
        return list(
            obj.days.order_by("day__date").values(
                "id",
                "is_attended",
                date=F("day__date"),
                mode=F("attendance_mode"),
                
            )
        )     
    
class RegistrationSessionInputSerializer(serializers.Serializer):
    day = serializers.PrimaryKeyRelatedField(
        queryset=EventDay.objects.all()
    )
    attendance_mode = serializers.ChoiceField(
        choices=AttendanceMode.choices
    )
    session_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False
    )

class RegistrationSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            is_active=True,
            is_superuser=False
        ),
        default=serializers.CurrentUserDefault()
    )

    sessions = RegistrationSessionInputSerializer(
        many=True,
        write_only=True
    )

    user_name = serializers.CharField(
        source="user.full_name",
        read_only=True
    )
    phone_number = serializers.CharField(
        source="user.phone_number",
        read_only=True
    )
    email = serializers.EmailField(
        source="user.email",
        read_only=True
    )

    days = RegistrationDaySerializer(
        many=True,
        read_only=True
    )

    travel_assistance = TravelAssistanceSerializer(
        many=True,
        read_only=True
    )
    medical_assistance = MedicalAssistanceSerializer(
        read_only=True
    )
    translation_assistance = TranslationAssistanceSerializer(
        read_only=True
    )
    accommodation_assistance = AccommodationAssistanceSerializer(
        read_only=True
    )

    class Meta:
        model = Registration
        fields = [
            "id",
            "user",
            "user_name",
            "phone_number",
            "email",
            "event",
            "sessions",
            "days",
            "travel_assistance",
            "medical_assistance",
            "translation_assistance",
            "accommodation_assistance",
            "status",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "status",
            "created_at",
            "updated_at",
        ]


    def validate(self, attrs):
        event = attrs["event"]
        sessions = attrs.get("sessions", [])

        if not sessions:
            raise serializers.ValidationError({
                "sessions": "This field is required."
            })

        used_days = set()

        for item in sessions:
            day = item["day"]
            attendance_mode = item["attendance_mode"]

            if day.event_id != event.id:
                raise serializers.ValidationError({
                    "sessions": f"Day {day.id} does not belong to this event."
                })

            if day.id in used_days:
                raise serializers.ValidationError({
                    "sessions": f"Day {day.id} is duplicated."
                })

            used_days.add(day.id)

            # Validate attendance mode for this day
            if attendance_mode not in day.allowed_attendance_modes:
                raise serializers.ValidationError({
                    "sessions": (
                        f"{attendance_mode} is not allowed for day "
                        f"{day.day_number}. Allowed modes: {day.allowed_attendance_modes}"
                    )
                })

            db_sessions = ScheduleItem.objects.filter(
                id__in=item["session_ids"],
                day=day,
            )

            if db_sessions.count() != len(item["session_ids"]):
                raise serializers.ValidationError({
                    "sessions": f"One or more sessions do not belong to day {day.id}."
                })

        return attrs

    def create(self, validated_data):
        session_data = validated_data.pop("sessions")

        with transaction.atomic():
            registration = Registration.objects.create(**validated_data)

            attendance_modes = []
            session_ids = []

            for item in session_data:
                attendance_modes.append({
                    "day_id": item["day"].id,
                    "attendance_mode": item["attendance_mode"]
                })

                session_ids.extend(item["session_ids"])

            registration.create_registration(
                attendance_modes=attendance_modes,
                session_ids=session_ids
            )

        return registration

    def update(self, instance, validated_data):
        validated_data.pop("user", None)
        session_data = validated_data.pop("sessions", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if session_data is not None:
            attendance_modes = []
            session_ids = []

            for item in session_data:
                attendance_modes.append({
                    "day_id": item["day"].id,
                    "attendance_mode": item["attendance_mode"]
                })

                session_ids.extend(item["session_ids"])

            with transaction.atomic():
                instance.update_registration(
                    attendance_modes=attendance_modes,
                    session_ids=session_ids
                )

        return instance

class BulkStatusUpdateSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    status = serializers.CharField()