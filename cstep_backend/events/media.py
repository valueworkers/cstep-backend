from urllib.parse import quote
from django.conf import settings


def _scheme(enable_tls) -> str:
    enabled = str(enable_tls).lower() == "true" if isinstance(enable_tls, str) else bool(enable_tls)
    return "https" if enabled else "http"


def build_whip_ingest_url(stream_key: str) -> str:
    """Broadcaster's browser POSTs its WHIP offer here directly — Django
    never proxies media, it only hands this URL back to the client."""
    scheme = _scheme(settings.OME_WEBRTC_PROVIDER_ENABLE_TLS)
    return (
        f"{scheme}://{settings.OME_HOST}:{settings.OME_WEBRTC_PROVIDER_PORT}"
        f"/{settings.OME_APP_NAME}/{stream_key}?direction=whip"
    )


def build_whep_playback_url(stream_key: str) -> str:
    scheme = _scheme(settings.OME_WEBRTC_PUBLISHER_ENABLE_TLS)
    return (
        f"{scheme}://{settings.OME_HOST}:{settings.OME_WEBRTC_PUBLISHER_PORT}"
        f"/{settings.OME_APP_NAME}/{stream_key}?direction=whep"
    )


def build_llhls_playback_url(stream_key: str) -> str:
    """Fallback for clients that can't do WebRTC (e.g. some in-app webviews)."""
    scheme = _scheme(settings.OME_LLHLS_PUBLISHER_ENABLE_TLS)
    return (
        f"{scheme}://{settings.OME_HOST}:{settings.OME_LLHLS_PUBLISHER_PORT}"
        f"/{settings.OME_APP_NAME}/{stream_key}/llhls.m3u8"
    )


def build_rtmp_ingest_url(stream_key: str) -> str:
    """Kept for OBS/hardware encoders that prefer RTMP over WHIP."""
    return f"rtmp://{settings.OME_HOST}:{settings.OME_RTMP_PROVIDER_PORT}/{settings.OME_APP_NAME}/{stream_key}"


def build_srt_ingest_url(stream_key: str) -> str:
    target = f"srt://{settings.OME_HOST}:{settings.OME_SRT_PROVIDER_PORT}/{settings.OME_APP_NAME}/{stream_key}"
    return f"srt://{settings.OME_HOST}:{settings.OME_SRT_PROVIDER_PORT}?streamid={quote(target, safe='')}"


def build_ingest_urls(stream_key: str) -> dict:
    return {
        "webrtc_whip": build_whip_ingest_url(stream_key),
        "rtmp": build_rtmp_ingest_url(stream_key),
        "srt": build_srt_ingest_url(stream_key),
    }


def build_playback_urls(stream_key: str) -> dict:
    return {
        "webrtc_whep": build_whep_playback_url(stream_key),
        "llhls": build_llhls_playback_url(stream_key),
    }