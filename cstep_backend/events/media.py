"""
Pure helpers for building MediaMTX URLs.
No model imports here, so models.py / serializers.py / utils.py can import this
without creating a circular dependency.
"""

from django.conf import settings


def _rtmp_base_url() -> str:
    return settings.MEDIA_SERVER_RTMP_BASE_URL.rstrip("/")


def _rtsp_base_url() -> str:
    return settings.MEDIA_SERVER_RTSP_BASE_URL.rstrip("/")


def _hls_base_url() -> str:
    return settings.MEDIA_SERVER_HLS_BASE_URL.rstrip("/")


def _webrtc_base_url() -> str:
    return settings.MEDIA_SERVER_WEBRTC_BASE_URL.rstrip("/")


def build_whip_ingest_url(stream_key: str) -> str:
    return f"{_webrtc_base_url()}/{stream_key}/whip"


def build_whep_playback_url(stream_key: str) -> str:
    return f"{_webrtc_base_url()}/{stream_key}/whep"


def build_rtmp_ingest_url(stream_key: str) -> str:
    return f"{_rtmp_base_url()}/{stream_key}"


def build_rtsp_url(stream_key: str) -> str:
    return f"{_rtsp_base_url()}/{stream_key}"


def build_hls_playback_url(stream_key: str) -> str:
    return f"{_hls_base_url()}/{stream_key}/index.m3u8"


def build_ingest_urls(stream_key: str) -> dict:
    return {
        "rtmp": build_rtmp_ingest_url(stream_key),
        "rtsp": build_rtsp_url(stream_key),
        "webrtc": build_whip_ingest_url(stream_key),
    }


def build_playback_urls(stream_key: str) -> dict:
    return {
        "rtsp": build_rtsp_url(stream_key),
        "hls": build_hls_playback_url(stream_key),
        "webrtc": build_whep_playback_url(stream_key),
    }
