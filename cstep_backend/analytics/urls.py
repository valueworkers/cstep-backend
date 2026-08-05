from django.urls import path
from . import views

urlpatterns = [
    path("registrations/trend/", views.RegistrationTrendView.as_view(), name="analytics-registration-trend"),
    path("registrations/counts/", views.RegistrationCountsView.as_view(), name="analytics-registration-counts"),
    path("registrations/insights/", views.RegistrationInsightsView.as_view(), name="analytics-registration-insights"),
    path("registrations/demographics/", views.RegistrationDemographicsView.as_view(), name="analytics-registration-demographics"),
    path("registrations/users/", views.UserListAPIView.as_view(), name="analytics-registrations-users"),
    path("streaming/summary/", views.StreamingSummaryView.as_view(), name="analytics-streaming-summary"),
    path("streaming/participation-trend/", views.ParticipationTrendView.as_view(), name="analytics-participation-trend"),
    path("events/feedback/", views.FeedbackAnalyticsView.as_view(), name="analytics-events-feedback"),

]