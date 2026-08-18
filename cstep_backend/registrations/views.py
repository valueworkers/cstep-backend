from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Prefetch, Q

from .permissions import IsModeratorOrAbove
from accounts.models import UserRole, User
from .constants import ApprovalStatus
from .models import (
    Registration,RegistrationDay, RegistrationStatus, RegistrationSession,
    TravelAssistance, MedicalAssistance, TranslationAssistance, AccommodationAssistance
)
from .serializers import (
    RegistrationListSerializer,
    RegistrationSerializer,
    RegistrationDaySerializer,
    BulkStatusUpdateSerializer,
    RegistrationSessionSerializer,
    TravelAssistanceSerializer,
    MedicalAssistanceSerializer,
    TranslationAssistanceSerializer,
    AccommodationAssistanceSerializer,
)

class RegistrationViewSet(viewsets.ModelViewSet):
    queryset = (
        Registration.objects
        .select_related("user", "event")
        .prefetch_related(
            "days__day",
            "sessions__session__day",
        )
    )

    filterset_fields = {
        "status": ["exact", "in"],
        'event_id':['exact'],
        "event__title": ["exact", "icontains"],
        "user": ["exact"],
        "created_at": ["date", "gte", "lte"],
    }

    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "event__title",
    ]

    ordering_fields = [
        "created_at",
        "updated_at",
        "status",
        "event__title",
        "user__email",
    ]
    ordering = ["-created_at"]

    # ---------------------------------

    def get_serializer_class(self):
        if self.action == "bulk_update_status":
            return BulkStatusUpdateSerializer

        if self.action == "list":
            return RegistrationListSerializer

        return RegistrationSerializer

    def get_permissions(self):
        if self.action in ["create", "my_registrations", "remove_session"]:
            return [IsAuthenticated()]
        return [IsModeratorOrAbove()]

    def get_queryset(self):
        queryset = Registration.objects.select_related(
            "user", "event", "medical_assistance",
            "translation_assistance", "accommodation_assistance",
        )

        days_qs = RegistrationDay.objects.select_related("day")

        day_id = self.request.query_params.get("day_id")
        attendance_mode = self.request.query_params.get("attendance_mode")

        days_filter = Q()
        if day_id:
            days_filter &= Q(day_id=day_id)
        if attendance_mode:
            days_filter &= Q(attendance_mode=attendance_mode)

        if days_filter:
            # filter the prefetched days themselves
            days_qs = days_qs.filter(days_filter)

            # also filter the outer queryset so registrations
            # with no matching day are excluded entirely
            outer_q = Q()
            if day_id:
                outer_q &= Q(days__day_id=day_id)
            if attendance_mode:
                outer_q &= Q(days__attendance_mode=attendance_mode)
            queryset = queryset.filter(outer_q)

        queryset = queryset.prefetch_related(
            "travel_assistance",
            Prefetch("days", queryset=days_qs),
            "sessions__session__day",
        ).distinct()

        if self.action == "list":
            return queryset.select_related("user", "event")

        if self.action == "my_registrations":
            return queryset.filter(user=self.request.user)

        return queryset
    def _get_owned_registration_or_403(self, request, pk):
        registration = get_object_or_404(Registration, pk=pk)
        is_staff_role = request.user.role in {UserRole.MODERATOR, UserRole.EVENT_ADMIN, UserRole.SUPER_ADMIN}
        if registration.user_id != request.user.id and not is_staff_role:
            raise PermissionDenied("You do not have permission to modify this registration.")
        return registration

    # ------------------------------------------------------------------
    # Self-service
    # ------------------------------------------------------------------

    @action(detail=False, methods=["get"], url_path="my")
    def my_registrations(self, request):
        registrations = self.get_queryset().filter(user=request.user)
        serializer = RegistrationSerializer(
            registrations,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Registration-level accept/reject/hold — cascades to days + sessions
    # ------------------------------------------------------------------

    def _set_status(self, request, new_status):
        registration = self.get_object()
        registration.bulk_update_status(new_status)
        return Response(RegistrationSerializer(registration, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._set_status(request, RegistrationStatus.ACCEPTED)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._set_status(request, RegistrationStatus.REJECTED)

    @action(detail=True, methods=["post"], url_path="hold")
    def hold(self, request, pk=None):
        return self._set_status(request, RegistrationStatus.HOLD)

    @action(detail=False, methods=["patch"], url_path="bulk-status", permission_classes=[IsModeratorOrAbove])
    def bulk_update_status(self, request):
        serializer = BulkStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        new_status = serializer.validated_data["status"]

        with transaction.atomic():
            updated = (
                self.get_queryset()
                .filter(id__in=ids)
                .update(status=new_status, updated_at=timezone.now())
            )
            # days_updated = RegistrationDay.objects.filter(
            #     registration_id__in=ids
            # ).update(status=new_status, updated_at=timezone.now())
            sessions_updated = RegistrationSession.objects.filter(
                registration_id__in=ids
            ).update(status=new_status, updated_at=timezone.now())

        return Response({
            "message": f"{updated} registrations updated,"
                       f"{sessions_updated} sessions updated."
        })

class RegistrationDayViewSet(viewsets.ModelViewSet):
    """
    Day-level attendance registrations — one row per registration per EventDay.
    """

    queryset = RegistrationDay.objects.select_related(
        "registration__user", "registration__event", "day"
    )
    serializer_class = RegistrationDaySerializer

    filterset_fields = {
        "attendance_mode":   ["exact"],
        "registration":      ["exact"],
        "registration__event": ["exact"],
        "day":               ["exact"],
    }
    search_fields = [
        "registration__user__email",
        "registration__user__first_name",
        "registration__user__last_name",
    ]
    ordering_fields = ["created_at", "updated_at", "day__date"]
    ordering = ["day__date"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsModeratorOrAbove()]
        return [IsAuthenticated()]

class RegistrationSessionViewSet(viewsets.ModelViewSet):
    """
    Session-level registrations (RegistrationSession rows, created either
    from a MULTI_SESSION pick or a WHOLE_DAY expansion).

    list/detail/update/destroy         — Moderator+
    accept/reject/hold                 — Moderator/EventAdmin:
      POST   /registration-sessions/{id}/approve/
      POST   /registration-sessions/{id}/reject/
      POST   /registration-sessions/{id}/hold/
      PATCH  /registration-sessions/bulk-status/
    """

    queryset = RegistrationSession.objects.select_related(
        "registration__user", "registration__event", "session__day"
    )
    serializer_class = RegistrationSessionSerializer

    filterset_fields = {
        "status":            ["exact", "in"],
        "registration":      ["exact"],
        "registration__event": ["exact"],
        "session":           ["exact"],
        "session__day":      ["exact"],
    }
    search_fields = [
        "registration__user__email",
        "registration__user__first_name",
        "registration__user__last_name",
        "session__title",
    ]
    ordering_fields = ["created_at", "status", "session__day__date", "session__start_time"]
    ordering = ["session__day__date", "session__start_time"]

    def get_permissions(self):
        return [IsModeratorOrAbove()]

    def get_serializer_class(self):
        if self.action == "bulk_update_status":
            return BulkStatusUpdateSerializer
        return RegistrationSessionSerializer

    def _set_status(self, new_status):
        rs = self.get_object()
        rs.status = new_status
        rs.save(update_fields=["status", "updated_at"])
        return Response(RegistrationSessionSerializer(rs).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._set_status(RegistrationStatus.ACCEPTED)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._set_status(RegistrationStatus.REJECTED)

    @action(detail=True, methods=["post"], url_path="hold")
    def hold(self, request, pk=None):
        return self._set_status(RegistrationStatus.HOLD)

    @action(detail=False, methods=["patch"], url_path="bulk-status")
    def bulk_update_status(self, request):
        serializer = BulkStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = RegistrationSession.objects.filter(
            id__in=serializer.validated_data["ids"]
        ).update(status=serializer.validated_data["status"], updated_at=timezone.now())
        return Response({"message": f"{updated} records updated.", "updated_count": updated})

class TravelAssistanceViewSet(viewsets.ModelViewSet):
    serializer_class = TravelAssistanceSerializer
    queryset = (
        TravelAssistance.objects
        .select_related("registration__user", "registration__event")
    )

    filterset_fields = {
        "status":                       ["exact", "in"],
        "transport_mode":               ["exact", "in"],
        "travel_date":                  ["exact", "gte", "lte"],
        "registration":                 ["exact"],
        "registration__event":          ["exact"],
        "registration__status":         ["exact"],
    }

    search_fields = [
        "source_location",
        "destination_location",
        "registration__user__email",
        "registration__user__first_name",
        "registration__user__last_name",
        "registration__event__title",
    ]

    ordering_fields = [
        "travel_date",
        "status",
        "transport_mode",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action in ["create"]:
            return [IsAuthenticated()]
        return [IsModeratorOrAbove()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == UserRole.BASE_USER and self.action == "list":
            raise PermissionDenied("You do not have permission to access this API.")
        return queryset

    @action(detail=False, methods=["patch"], url_path="bulk-status", permission_classes=[IsModeratorOrAbove])
    def bulk_update_status(self, request):
        serializer = BulkStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = (
            self.get_queryset()
            .filter(id__in=serializer.validated_data["ids"])
            .update(status=serializer.validated_data["status"], updated_at=timezone.now())
        )
        return Response({"message": f"{updated} records updated.", "updated_count": updated})

class MedicalAssistanceViewSet(viewsets.ModelViewSet):
    serializer_class = MedicalAssistanceSerializer
    queryset = (
        MedicalAssistance.objects
        .select_related("registration__user", "registration__event")
    )

    filterset_fields = {
        "status":                   ["exact", "in"],
        "date":                     ["exact", "gte", "lte"],
        "registration":             ["exact"],
        "registration__event":      ["exact"],
        "registration__status":     ["exact"],
    }

    search_fields = [
        "medical_needs",
        "registration__user__email",
        "registration__user__first_name",
        "registration__user__last_name",
        "registration__event__title",
    ]

    ordering_fields = [
        "date",
        "status",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action in ["bulk_update_status"]:
            return [IsModeratorOrAbove()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == UserRole.BASE_USER and self.action == "list":
            raise PermissionDenied("You do not have permission to access this API.")
        return queryset

    @action(detail=False, methods=["patch"], url_path="bulk-status", permission_classes=[IsModeratorOrAbove])
    def bulk_update_status(self, request):
        serializer = BulkStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = (
            self.get_queryset()
            .filter(id__in=serializer.validated_data["ids"])
            .update(status=serializer.validated_data["status"], updated_at=timezone.now())
        )
        return Response({"message": f"{updated} records updated.", "updated_count": updated})

class TranslationAssistanceViewSet(viewsets.ModelViewSet):
    serializer_class = TranslationAssistanceSerializer
    queryset = (
        TranslationAssistance.objects
        .select_related("registration__user", "registration__event")
    )

    filterset_fields = {
        "status":                   ["exact", "in"],
        "language":                 ["exact", "in"],
        "date":                     ["exact", "gte", "lte"],
        "registration":             ["exact"],
        "registration__event":      ["exact"],
        "registration__status":     ["exact"],
    }

    search_fields = [
        "language",
        "registration__user__email",
        "registration__user__first_name",
        "registration__user__last_name",
        "registration__event__title",
    ]

    ordering_fields = [
        "date",
        "language",
        "status",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action in ["bulk_update_status"]:
            return [IsModeratorOrAbove()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == UserRole.BASE_USER and self.action == "list":
            raise PermissionDenied("You do not have permission to access this API.")
        return queryset

    @action(detail=False, methods=["patch"], url_path="bulk-status", permission_classes=[IsModeratorOrAbove])
    def bulk_update_status(self, request):
        serializer = BulkStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = (
            self.get_queryset()
            .filter(id__in=serializer.validated_data["ids"])
            .update(status=serializer.validated_data["status"], updated_at=timezone.now())
        )
        return Response({"message": f"{updated} records updated.", "updated_count": updated})

class AccommodationAssistanceViewSet(viewsets.ModelViewSet):
    serializer_class = AccommodationAssistanceSerializer
    queryset = (
        AccommodationAssistance.objects
        .select_related("registration__user", "registration__event")
    )

    filterset_fields = {
        "status":                   ["exact", "in"],
        "from_date":                ["exact", "gte", "lte"],
        "to_date":                  ["exact", "gte", "lte"],
        "registration":             ["exact"],
        "registration__event":      ["exact"],
        "registration__status":     ["exact"],
    }

    search_fields = [
        "hotel_name",
        "address",
        "room_no",
        "registration__user__email",
        "registration__user__first_name",
        "registration__user__last_name",
        "registration__event__title",
    ]

    ordering_fields = [
        "from_date",
        "to_date",
        "status",
        "hotel_name",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action in ["bulk_update_status"]:
            return [IsModeratorOrAbove()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == UserRole.BASE_USER and self.action == "list":
            raise PermissionDenied("You do not have permission to access this API.")
        return queryset

    @action(detail=False, methods=["patch"], url_path="bulk-status", permission_classes=[IsModeratorOrAbove])
    def bulk_update_status(self, request):
        serializer = BulkStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = (
            self.get_queryset()
            .filter(id__in=serializer.validated_data["ids"])
            .update(status=serializer.validated_data["status"], updated_at=timezone.now())
        )
        return Response({"message": f"{updated} records updated.", "updated_count": updated})