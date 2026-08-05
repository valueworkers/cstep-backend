from django.urls import path
from .consumers import EventStreamConsumer

websocket_urlpatterns = [
    path("ws/events/<int:event_id>/", EventStreamConsumer.as_asgi()),
]