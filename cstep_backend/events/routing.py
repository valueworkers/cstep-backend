from django.urls import path
from .consumers import EventStreamConsumer, ChatConsumer

websocket_urlpatterns = [
    path("ws/events/<int:event_id>/chat/", ChatConsumer.as_asgi()),
    path("ws/events/<int:event_id>/", EventStreamConsumer.as_asgi()),
]