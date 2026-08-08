from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "notification"

router = DefaultRouter()
router.register("notification", views.NotificationViewSet, basename="notification")

urlpatterns = router.urls