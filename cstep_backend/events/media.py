from urllib.parse import quote

from django.conf import settings


def _scheme(enable_tls) -> str:
    """
    Convert a boolean/string TLS setting into HTTP scheme.
    """
    enabled = (
        str(enable_tls).lower() == "true"
        if isinstance(enable_tls, str)
        else bool(enable_tls)
    )

    return "https" if enabled else "http"


# ============================================================
# WEBRTC / WHIP INGEST
# ============================================================

def build_whip_ingest_url(stream_key: str) -> str:
    """
    Browser/WebRTC broadcaster -> OME.

    WHIP ingest URL.
    """
    scheme = _scheme(settings.OME_WEBRTC_PROVIDER_ENABLE_TLS)

    return (
        f"{scheme}://{settings.OME_HOST}:"
        f"{settings.OME_WEBRTC_PROVIDER_PORT}/"
        f"{settings.OME_APP_NAME}/{stream_key}/master/"
        f"?direction=whip"
    )


# ============================================================
# WEBRTC / WHEP PLAYBACK
# ============================================================

def build_whep_playback_url(stream_key: str) -> str:
    """
    OME -> Browser/WebRTC player.

    WHEP playback URL.
    """
    scheme = _scheme(settings.OME_WEBRTC_PUBLISHER_ENABLE_TLS)

    return (
        f"{scheme}://{settings.OME_HOST}:"
        f"{settings.OME_WEBRTC_PUBLISHER_PORT}/"
        f"{settings.OME_APP_NAME}/{stream_key}/master/"
        f"?direction=whep"
    )


# ============================================================
# LL-HLS PLAYBACK
# ============================================================

def build_llhls_playback_url(stream_key: str) -> str:
    """
    Low-Latency HLS playback.

    Fallback for browsers/webviews that cannot use WebRTC.
    """
    scheme = _scheme(settings.OME_LLHLS_PUBLISHER_ENABLE_TLS)

    return (
        f"{scheme}://{settings.OME_HOST}:"
        f"{settings.OME_LLHLS_PUBLISHER_PORT}/"
        f"{settings.OME_APP_NAME}/{stream_key}/"
        f"master.m3u8"
    )


# ============================================================
# HLS PLAYBACK
# ============================================================

def build_hls_playback_url(stream_key: str) -> str:
    """
    Normal HLS playback.

    Example:
    https://host/app/stream/playlist.m3u8
    """
    scheme = _scheme(settings.OME_HLS_PUBLISHER_ENABLE_TLS)

    return (
        f"{scheme}://{settings.OME_HOST}:"
        f"{settings.OME_HLS_PUBLISHER_PORT}/"
        f"{settings.OME_APP_NAME}/{stream_key}/"
        f"master.m3u8"
    )


# ============================================================
# RTMP INGEST
# ============================================================

def build_rtmp_ingest_url(stream_key: str) -> str:
    """
    OBS / hardware encoder -> OME using RTMP.

    Server:
        rtmp://host:1935/app/stream_key
    """
    return (
        f"rtmp://{settings.OME_HOST}:"
        f"{settings.OME_RTMP_PROVIDER_PORT}/"
        f"{settings.OME_APP_NAME}/{stream_key}/master/"
    )


# ============================================================
# SRT INGEST
# ============================================================

def build_srt_ingest_url(stream_key: str) -> str:
    """
    Encoder -> OME using SRT.

    OME expects the streamid to contain the target URL.
    """
    target = (
        f"srt://{settings.OME_HOST}:"
        f"{settings.OME_SRT_PROVIDER_PORT}/"
        f"{settings.OME_APP_NAME}/{stream_key}"
    )

    return (
        f"srt://{settings.OME_HOST}:"
        f"{settings.OME_SRT_PROVIDER_PORT}"
        f"?streamid={quote(target, safe='')}"
    )


# ============================================================
# SRT PUBLISHER / OUTPUT
# ============================================================

def build_srt_playback_url(stream_key: str) -> str:
    """
    OME -> SRT receiver.

    Note:
    The exact SRT output connection parameters can depend on
    how the SRT publisher is exposed/configured.
    """
    return (
        f"srt://{settings.OME_HOST}:"
        f"{settings.OME_SRT_PUBLISHER_PORT}"
        f"?streamid={quote(stream_key, safe='')}"
    )


# ============================================================
# MPEG-TS INGEST
# ============================================================

def build_mpegts_ingest_url(stream_key: str) -> str:
    """
    MPEG-TS over UDP -> OME.

    Your current OME configuration maps port 4000 to:

        stream_4000

    Therefore the stream name is determined by the OME
    StreamMap configuration rather than directly by stream_key.
    """
    return (
        f"udp://{settings.OME_HOST}:"
        f"{settings.OME_MPEGTS_PROVIDER_PORT}"
    )


# ============================================================
# RTSP PULL
# ============================================================

def build_rtsp_pull_url(
    stream_key: str,
    rtsp_source_url: str,
) -> str:
    """
    RTSP source -> OME.

    RTSP is a PULL provider, so OME connects to the source.

    `rtsp_source_url` is the camera/encoder RTSP URL.
    """
    return rtsp_source_url


# ============================================================
# OVT
# ============================================================

def build_ovt_origin_url(stream_key: str) -> str:
    """
    OVT is intended for OME Origin <-> OME Edge communication.

    This should generally NOT be exposed as a public client
    playback URL.
    """
    return (
        f"ovt://{settings.OME_HOST}:"
        f"{settings.OME_OVT_PORT}/"
        f"{settings.OME_APP_NAME}/{stream_key}"
    )


# ============================================================
# ALL INGEST URLS
# ============================================================

def build_ingest_urls(stream_key: str) -> dict:
    """
    Return all client/encoder ingest options.
    """

    return {
        # Browser/WebRTC
        "webrtc_whip": build_whip_ingest_url(stream_key),

        # OBS / hardware encoder
        "rtmp": build_rtmp_ingest_url(stream_key),

        # Low-latency contribution
        "srt": build_srt_ingest_url(stream_key),

        # MPEG-TS over UDP
        "mpegts": build_mpegts_ingest_url(stream_key),

    }


# ============================================================
# ALL PLAYBACK URLS
# ============================================================

def build_playback_urls(stream_key: str) -> dict:
    """
    Return all playback options.
    """

    return {
        # Ultra-low latency
        "webrtc_whep": build_whep_playback_url(stream_key),

        # Low-latency HTTP streaming
        "llhls": build_llhls_playback_url(stream_key),

        # Standard HLS
        "hls": build_hls_playback_url(stream_key),

        # SRT output
        "srt": build_srt_playback_url(stream_key),
    }


# ============================================================
# EVERYTHING
# ============================================================

def build_stream_urls(stream_key: str) -> dict:
    """
    Return all available ingest and playback URLs.
    """

    return {
        "ingest": build_ingest_urls(stream_key),
        "playback": build_playback_urls(stream_key),
    }