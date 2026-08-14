import base64
import hashlib
import hmac
import logging
from urllib.parse import urlparse

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import BroadcastSession
from .serializers import AdmissionWebhookSerializer
from .utils import _handle_stream_started, _handle_stream_ended

logger = logging.getLogger(__name__)


def _verify_ome_signature(request) -> bool:
    if settings.DEBUG:
        return True
    secret = settings.OME_ADMISSION_WEBHOOK_SECRET
    if not secret:
        logger.warning("OME_ADMISSION_WEBHOOK_SECRET not configured — rejecting webhook.")
        return False

    signature = request.META.get("HTTP_X_OME_SIGNATURE", "")
    if not signature:
        return False

    digest = hmac.new(secret.encode(), request.body, hashlib.sha1).digest()
    expected = base64.urlsafe_b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def ome_admission_webhook(request):
    """
    POST /webhooks/ome/admission/

    Configure in OME's Server.xml:
      <AdmissionWebhooks>
        <ControlServerUrl>https://your-domain/webhooks/ome/admission/</ControlServerUrl>
        <SecretKey>...</SecretKey>
        <Timeout>3000</Timeout>
        <Enables><Providers>webrtc,rtmp,srt</Providers><Publishers>webrtc,llhls</Publishers></Enables>
      </AdmissionWebhooks>
    """
    if not _verify_ome_signature(request):
        return Response({"allowed": False}, status=401)

    serializer = AdmissionWebhookSerializer(data=request.data)
    if not serializer.is_valid():
        logger.error("Invalid OME admission payload: %s", serializer.errors)
        # Fail closed on malformed payloads rather than 400ing OME.
        return Response({"allowed": False})

    direction = serializer.validated_data["direction"]   # incoming | outgoing
    status_ = serializer.validated_data["status"]         # opening | closing
    stream_key = serializer.stream_key                    # parsed from url path

    if direction == "outgoing":
        # Viewer WHEP connect/disconnect. Keep this branch cheap — it fires
        # on every viewer join/leave. Real viewer accounting already
        # happens through the join/leave/heartbeat REST endpoints, so we
        # just admit here rather than duplicating that bookkeeping.
        return Response({"allowed": True})

    # direction == "incoming": broadcaster publish/unpublish.
    session = BroadcastSession.objects.select_related("event").filter(stream_key=stream_key).first()
    if not session:
        logger.warning("Admission webhook for unknown stream_key=%s", stream_key)
        return Response({"allowed": False})

    if status_ == "opening":
        _handle_stream_started(session, session.event, {"timestamp": None})
    elif status_ == "closing":
        _handle_stream_ended(session, session.event)

    return Response({"allowed": True})