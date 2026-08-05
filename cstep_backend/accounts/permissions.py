from rest_framework.permissions import BasePermission
from .models import UserRole


class IsModerator(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in [
            UserRole.MODERATOR, UserRole.EVENT_ADMIN, UserRole.SUPER_ADMIN
        ]


class IsEventAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in [
            UserRole.EVENT_ADMIN, UserRole.SUPER_ADMIN
        ]


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == UserRole.SUPER_ADMIN
