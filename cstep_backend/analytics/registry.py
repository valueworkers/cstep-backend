import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# Reuse whatever Redis your channel layer / Celery broker already points at.
# protocol=2 pinned explicitly: RESP3 (protocol=3, redis-py 8.x default) caused
# the earlier Channels disconnection issue.
_redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, protocol=2)

CONNECTION_COUNTS_KEY = "live_analytics:connection_counts"          # hash: {event_id: open_socket_count}
VISUAL_KEY_FMT = "live_analytics:visuals:{event_id}"                # hash: {visual_name: subscriber_count}


def _visual_key(event_id):
    return VISUAL_KEY_FMT.format(event_id=event_id)


# ---------- connection counts ----------

def register_connection(event_id):
    try:
        _redis.hincrby(CONNECTION_COUNTS_KEY, event_id, 1)
    except redis.RedisError:
        logger.exception("registry: failed to register connection for event %s", event_id)


def unregister_connection(event_id):
    try:
        new_count = _redis.hincrby(CONNECTION_COUNTS_KEY, event_id, -1)
        if new_count <= 0:
            _redis.hdel(CONNECTION_COUNTS_KEY, event_id)
    except redis.RedisError:
        logger.exception("registry: failed to unregister connection for event %s", event_id)


def get_active_event_ids():
    """Returns None on Redis failure so callers can fall back to 'all live
    events' rather than silently pushing to nobody."""
    try:
        return {int(eid) for eid in _redis.hkeys(CONNECTION_COUNTS_KEY)}
    except redis.RedisError:
        logger.exception("registry: failed to read active event ids")
        return None


# ---------- visual subscriptions ----------

def add_visual(event_id, visual):
    """Call when a socket subscribes to one visual key."""
    try:
        _redis.hincrby(_visual_key(event_id), visual, 1)
    except redis.RedisError:
        logger.exception("registry: failed to add visual %s for event %s", visual, event_id)


def remove_visual(event_id, visual):
    """Call when a socket unsubscribes from, or disconnects while
    subscribed to, one visual key."""
    key = _visual_key(event_id)
    try:
        new_count = _redis.hincrby(key, visual, -1)
        if new_count <= 0:
            _redis.hdel(key, visual)
    except redis.RedisError:
        logger.exception("registry: failed to remove visual %s for event %s", visual, event_id)


def remove_visuals(event_id, visuals):
    """Bulk version of remove_visual, e.g. for cleaning up on disconnect."""
    for visual in visuals:
        remove_visual(event_id, visual)


def get_requested_visuals(event_id):
    """Union of visual keys at least one open socket is subscribed to.
    Empty set if nobody's subscribed to anything (or no sockets open)."""
    try:
        raw = _redis.hgetall(_visual_key(event_id))
    except redis.RedisError:
        logger.exception("registry: failed to read requested visuals for event %s", event_id)
        return set()
    return {v for v, count in raw.items() if int(count) > 0}