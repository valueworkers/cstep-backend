from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .constants import NotificationChannel
from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    GET  /notifications/                  list own in-app notifications (?unread=true to filter)
    GET  /notifications/{id}/             retrieve one
    POST /notifications/{id}/read/        mark one read
    POST /notifications/read-all/         mark all read
    GET  /notifications/unread-count/     current badge count
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user, channel=NotificationChannel.IN_APP)
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
        return qs

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request):
        updated = Notification.objects.filter(
            user=request.user, channel=NotificationChannel.IN_APP, is_read=False
        ).update(is_read=True)
        return Response({"marked_read": updated})

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = Notification.objects.filter(
            user=request.user, channel=NotificationChannel.IN_APP, is_read=False
        ).count()
        return Response({"unread_count": count})