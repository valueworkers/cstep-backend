from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import AuthViewSet, UserViewSet,BulkUserCreateView

router = DefaultRouter()

router.register("", AuthViewSet, basename="auth")
router.register("users", UserViewSet, basename="users")


urlpatterns = [
    *router.urls,
    path("me/", UserViewSet.as_view({"get": "me", "patch": "me"}), name="auth-me"),
    path("users-bulk-upload/", BulkUserCreateView.as_view(), name="user-bulk-upload"),
]
