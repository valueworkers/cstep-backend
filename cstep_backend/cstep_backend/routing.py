from analytics.routing import websocket_urlpatterns as analytics
from events.routing import websocket_urlpatterns as events

websocket_urlpatterns = [
    *analytics,
    *events,
]