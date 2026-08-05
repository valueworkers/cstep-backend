from rest_framework.routers import DefaultRouter
from .views import (
    RegistrationViewSet,
    RegistrationDayViewSet,
    RegistrationSessionViewSet,
    MedicalAssistanceViewSet,
    TranslationAssistanceViewSet,
    TravelAssistanceViewSet,
    AccommodationAssistanceViewSet
    )

router = DefaultRouter()
router.register("registration", RegistrationViewSet, basename="registration")
router.register("registration-day", RegistrationDayViewSet, basename="registration-day")
router.register("registration-session", RegistrationSessionViewSet, basename="registration-session")

router.register("travel-assistance", TravelAssistanceViewSet)
router.register("medical-assistance", MedicalAssistanceViewSet)
router.register("translation-assistance", TranslationAssistanceViewSet)
router.register("accommodation-assistance", AccommodationAssistanceViewSet)
urlpatterns = router.urls
