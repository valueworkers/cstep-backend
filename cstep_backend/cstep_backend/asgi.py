import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cstep_backend.settings")
django.setup()  # populate the app registry BEFORE importing anything that touches models

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

django_asgi_app = get_asgi_application()

from .middleware import JWTAuthMiddlewareStack
from .routing import  websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        JWTAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})