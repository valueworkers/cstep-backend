from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics,status
from registrations.models import Registration
from .serializers import *
from events.permissions import IsModeratorOrAbove
from . import services

class RegistrationTrendView(APIView):
    """GET /analytics/registrations/trend/?event_id=&granularity=daily|weekly|monthly&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD"""
    permission_classes = [IsModeratorOrAbove]

    def get(self, request):
        params = TrendQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        v = params.validated_data
        return Response({
            "granularity": v["granularity"],
            "results": services.registration_trend(
                event_id=v.get("event_id"),
                granularity=v["granularity"],
                date_from=v.get("date_from"),
                date_to=v.get("date_to"),
            ),
        })

class ParticipationTrendView(APIView):
    """GET /analytics/streaming/participation-trend/?event_id=&mode=physical|virtual|all&interval_minutes=15&date=YYYY-MM-DD"""
    permission_classes = [IsModeratorOrAbove]

    def get(self, request):
        params = ParticipationTrendQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        v = params.validated_data
        return Response({
            "mode": v["mode"],
            "results": services.participation_trend(
                event_id=v.get("event_id"),
                mode=v["mode"],
                interval_minutes=v["interval_minutes"],
                day=v.get("date"),
            ),
        })

class RegistrationCountsView(APIView):
    """GET /analytics/registrations/counts/?event_id= -> Registrations summary cards"""
    permission_classes = [IsModeratorOrAbove]

    def get(self, request):
        params = EventScopeQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        return Response(services.registration_counts(event_id=params.validated_data.get("event_id")))

class RegistrationInsightsQuerySerializer(EventScopeQuerySerializer):
    date = serializers.DateField(required=False)

class RegistrationInsightsView(APIView):
    """GET /analytics/registrations/insights/?event_id=&date=YYYY-MM-DD
    -> status/mode/per-date-mode/time/date tables. `date` scopes the
    day-based tables to a single day; Registration Status is unaffected."""
    permission_classes = [IsModeratorOrAbove]

    def get(self, request):
        params = RegistrationInsightsQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        v = params.validated_data
        return Response(services.registration_insights(event_id=v.get("event_id"), date=v.get("date")))

class RegistrationDemographicsView(APIView):
    """GET /analytics/regitrations/demographics/?event_id=&top_n_cities=10
    -> registrant breakdown by gender, org_type, state, city"""
    permission_classes = [IsModeratorOrAbove]

    def get(self, request):
        params = DemographicsQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        v = params.validated_data
        return Response(
            services.registration_demographics(event_id=v.get("event_id"), top_n_cities=v.get("top_n_cities"))
        )

class StreamingSummaryView(APIView):
    """GET /analytics/streaming/summary/?event_id= -> Streaming Details table + quick cards"""
    permission_classes = [IsModeratorOrAbove]

    def get(self, request):
        params = EventScopeQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        return Response(services.streaming_summary(event_id=params.validated_data.get("event_id")))

class UserListAPIView(generics.ListAPIView):
    queryset = (
        Registration.objects
        .select_related('user', 'event')
        .prefetch_related('days__day')
        .distinct()
    )
    serializer_class = RegistrationListSerializer

    filterset_fields = {
        'event_id': ['exact'],
        'days__day__date': ['exact'],
        'days__attendance_mode': ['exact'],
    }

    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'user__phone_number']
    ordering_fields = [
        "user__salutation",
        "user__first_name",
        "user__middle_name",
        "user__last_name",
        "user__phone_number",
        "user__email",
        "user__gender",
        "user__role",
        "user__city",
        "user__state",
        "user__designation",
        "user__org_type",
        "user__org_name",
        "event__title",
        "status",
        "created_at",
    
    ]
    ordering = ['-created_at']

class FeedbackAnalyticsView(APIView):
    """
    GET /analytics/feedback/?event=<id>              -> full event summary (by_day + by_session)
    GET /analytics/feedback/?event=<id>&day=<id>      -> day-level counts
    GET /analytics/feedback/?event=<id>&session=<id>  -> session-level counts
    """
    permission_classes = [IsModeratorOrAbove]

    def get(self, request):
        event_id = request.query_params.get("event")
        if not event_id:
            return Response({"detail": "event query param required"}, status=status.HTTP_400_BAD_REQUEST)

        day_id = request.query_params.get("day")
        session_id = request.query_params.get("session")

        if session_id:
            data = services.get_feedback_analytics(event_id, schedule_item_id=session_id)
        elif day_id:
            data = services.get_feedback_analytics(event_id, event_day_id=day_id)
        else:
            data = services.get_event_feedback_summary(event_id)

        return Response(data)