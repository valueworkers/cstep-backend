from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsEventAdminOrAbove(BasePermission):
    """EVENT_ADMIN or SUPER_ADMIN only."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            "EVENT_ADMIN", "SUPER_ADMIN"
        )


class IsModeratorOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            "MODERATOR", "EVENT_ADMIN", "SUPER_ADMIN"
        )


class IsAuthenticatedViewer(BasePermission):
    """Any authenticated user can view live events."""
    def has_permission(self, request, view):
        return request.user.is_authenticated


class IsBroadcasterOrAdmin(BasePermission):
    """Object-level: only the assigned broadcaster or an admin."""
    def has_object_permission(self, request, view, obj):
        if request.user.role in ("EVENT_ADMIN", "SUPER_ADMIN"):
            return True
        if hasattr(obj, "broadcast_sessions"):
            return obj.broadcast_sessions.filter(broadcaster=request.user).exists()
        return obj.broadcaster == request.user


class IsEventCreatorOrAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user.role in ("EVENT_ADMIN", "SUPER_ADMIN"):
            return True
        return obj.created_by == request.user
