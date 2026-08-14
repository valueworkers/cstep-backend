import base64
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _api_base_url() -> str:
    scheme = "https" if settings.OME_API_ENABLE_TLS else "http"
    return f"{scheme}://{settings.OME_HOST}:{settings.OME_API_PORT}/v1"


def _auth_header() -> dict:
    token = base64.b64encode(settings.OME_API_ACCESS_TOKEN.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def get_streams() -> list:
    url = f"{_api_base_url()}/vhosts/{settings.OME_VHOST_NAME}/apps/{settings.OME_APP_NAME}/streams"
    resp = requests.get(url, headers=_auth_header(), timeout=3)
    resp.raise_for_status()
    return resp.json()["response"]


def start_recording(stream_key: str, record_id: str) -> dict:
    url = f"{_api_base_url()}/vhosts/{settings.OME_VHOST_NAME}/apps/{settings.OME_APP_NAME}:startRecord"
    body = {"id": record_id, "stream": {"name": stream_key}}
    resp = requests.post(url, json=body, headers=_auth_header(), timeout=5)
    resp.raise_for_status()
    return resp.json()["response"]


def stop_recording(record_id: str) -> dict:
    url = f"{_api_base_url()}/vhosts/{settings.OME_VHOST_NAME}/apps/{settings.OME_APP_NAME}:stopRecord"
    resp = requests.post(url, json={"id": record_id}, headers=_auth_header(), timeout=5)
    resp.raise_for_status()
    return resp.json()["response"]


def disconnect_stream(stream_key: str) -> None:
    """Force-kick a publisher, e.g. an admin ending a stream that's
    misbehaving."""
    url = (
        f"{_api_base_url()}/vhosts/{settings.OME_VHOST_NAME}"
        f"/apps/{settings.OME_APP_NAME}/streams/{stream_key}"
    )
    resp = requests.delete(url, headers=_auth_header(), timeout=5)
    resp.raise_for_status()