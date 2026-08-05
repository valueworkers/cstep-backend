from rest_framework import serializers
from registrations.models import Registration, RegistrationDay
from accounts.models import User


class EventScopeQuerySerializer(serializers.Serializer):
    event_id = serializers.IntegerField(required=False)

class TrendQuerySerializer(EventScopeQuerySerializer):
    granularity = serializers.ChoiceField(choices=["daily", "weekly", "monthly"], default="daily")
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

class ParticipationTrendQuerySerializer(EventScopeQuerySerializer):
    mode = serializers.ChoiceField(choices=["physical", "virtual", "all"], default="all")
    interval_minutes = serializers.IntegerField(required=False, default=15, min_value=1, max_value=120)
    date = serializers.DateField(required=False)

class DemographicsQuerySerializer(EventScopeQuerySerializer):
    top_n_cities = serializers.IntegerField(required=False, min_value=1, max_value=100)

class UserListSerializer(serializers.ModelSerializer):  
    class Meta:
        model = User
        fields = [
            "salutation",
            "first_name",
            "middle_name",
            "last_name",
            "phone_number",
            "email",
            "gender",
            "role",
            "city",
            "state",
            "country",
            "designation",
            "org_type",
            "org_name",
            "created_at",
            "updated_at"
        ]

class RegistrationDayListSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source='day.date', read_only=True)

    class Meta:
        model = RegistrationDay
        fields = ['id', 'date', 'attendance_mode']

class RegistrationListSerializer(serializers.ModelSerializer):
    user = UserListSerializer(read_only=True)
    event_name = serializers.CharField(source='event.title', read_only=True)
    days = RegistrationDayListSerializer(many=True, read_only=True)

    class Meta:
        model = Registration
        fields = [
            'id',
            'user',
            'event_name',
            'status',
            'days',
            'created_at',
        ]
from rest_framework import serializers


class DynamicFieldsSerializer(serializers.Serializer):
    """
    Pass `fields` (iterable of field names) to keep only those declared
    fields, dropping the rest. Needed because plain Serializer.get_attribute()
    does instance[attr] for a Mapping and raises KeyError on missing keys
    (it only swallows AttributeError/ObjectDoesNotExist) — so a `raw` dict
    that only populates a subset of keys would otherwise blow up on the rest.
    """
    def __init__(self, *args, fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        if fields is not None:
            allowed = set(fields)
            for field_name in set(self.fields) - allowed:
                self.fields.pop(field_name)


class StatewiseLoginSerializer(serializers.Serializer):
    state = serializers.CharField()
    count = serializers.IntegerField()


class CountrywiseLoginSerializer(serializers.Serializer):
    country = serializers.CharField()
    count = serializers.IntegerField()


class DaywiseLoginSerializer(serializers.Serializer):
    day_id = serializers.IntegerField()
    day__day_number = serializers.IntegerField(source="day__day_number")
    day__date = serializers.DateField(source="day__date")
    count = serializers.IntegerField()


class NoShowSerializer(serializers.Serializer):
    day_id = serializers.IntegerField()
    day_number = serializers.IntegerField()
    registered = serializers.IntegerField()
    attended = serializers.IntegerField()
    no_show = serializers.IntegerField()


class SessionWiseMaxVirtualSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(allow_null=True)
    session_name = serializers.CharField()
    max_participants = serializers.IntegerField()


class SessionFeedbackSerializer(serializers.Serializer):
    schedule_item_id = serializers.IntegerField()
    schedule_item__title = serializers.CharField()
    avg_rating = serializers.FloatField(allow_null=True)   # Decimal in (from Avg()), float out
    count = serializers.IntegerField()


class DayFeedbackSerializer(serializers.Serializer):
    event_date_id = serializers.IntegerField()
    event_date__day_number = serializers.IntegerField()
    avg_rating = serializers.FloatField(allow_null=True)
    count = serializers.IntegerField()


class ChatCountSerializer(serializers.Serializer):
    total = serializers.IntegerField()


class ParticipationRatePointSerializer(serializers.Serializer):
    time = serializers.CharField()
    count = serializers.IntegerField()


class ParticipationRateRowSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(allow_null=True)
    session_name = serializers.CharField()
    session_duration_min = serializers.IntegerField()
    points = ParticipationRatePointSerializer(many=True)
    max_concurrent = serializers.IntegerField()


class ParticipationRateTableSerializer(serializers.Serializer):
    rows = ParticipationRateRowSerializer(many=True)


class ParticipationTimeRowSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(allow_null=True)
    session_name = serializers.CharField()
    session_duration_min = serializers.IntegerField()
    unique_participants = serializers.IntegerField()
    buckets = serializers.DictField(child=serializers.IntegerField())


class ParticipationTimeTableSerializer(serializers.Serializer):
    rows = ParticipationTimeRowSerializer(many=True)
