from djangochannelsrestframework.permissions import BasePermission

MODERATOR_ROLES = ("MODERATOR", "EVENT_ADMIN", "SUPER_ADMIN")

CLOSE_NO_USER = 4001
CLOSE_UNAUTHORIZED = 4003
CLOSE_EVENT_NOT_FOUND = 4004


class IsModeratorOrAbove(BasePermission):
    def has_permission(self, scope, consumer, action, **kwargs):
        user = scope.get("user")
        return getattr(user, "role", None) in MODERATOR_ROLES
