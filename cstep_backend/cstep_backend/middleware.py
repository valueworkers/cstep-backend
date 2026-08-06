from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
 
 
@database_sync_to_async
def get_user_from_token(token: str):
    """
    Resolve a JWT token to a User.
    Uses djangorestframework-simplejwt — swap for your JWT library if different.
    """
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from django.contrib.auth import get_user_model
        User = get_user_model()
        decoded = AccessToken(token)
        return User.objects.get(id=decoded["user_id"])
    except Exception:
        return AnonymousUser()
 
 
class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()

        query_params = parse_qs(query_string)
        token = query_params.get("token", [None])[0]

        if token:
            try:
                scope["user"] = await get_user_from_token(token)
            except Exception:
                scope["user"] = AnonymousUser()
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
 
 