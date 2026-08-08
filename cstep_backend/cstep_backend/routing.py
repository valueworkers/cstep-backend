from analytics.routing import websocket_urlpatterns as analytics
from events.routing import websocket_urlpatterns as events
from notification.routing import websocket_urlpatterns as notification

websocket_urlpatterns = [
    *analytics,
    *events,
    *notification,
]