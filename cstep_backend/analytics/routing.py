from django.urls import path
from analytics.consumers import LiveAnalyticsConsumer

websocket_urlpatterns = [
    path("ws/analytics/<int:event_id>/", LiveAnalyticsConsumer.as_asgi()),
]