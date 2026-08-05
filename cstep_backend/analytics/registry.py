import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# Reuse whatever Redis your channel layer / Celery broker already points at —
# don't introduce a second Redis instance with different defaults.
# protocol=2 pinned explicitly: RESP3 (protocol=3, redis-py 8.x default) is
# what caused the earlier Channels disconnection issue.
_redis = redis.Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    protocol=2,
)

CONNECTION_COUNTS_KEY = "live_analytics:connection_counts"  # hash: {event_id: open_socket_count}


def register_connection(event_id):
    """Call on consumer connect, after the socket is accepted into the group."""
    try:
        _redis.hincrby(CONNECTION_COUNTS_KEY, event_id, 1)
    except redis.RedisError:
        logger.exception("live_analytics registry: failed to register event %s", event_id)


def unregister_connection(event_id):
    """Call on consumer disconnect. Removes the field once count hits 0 so
    get_active_event_ids() doesn't have to filter out zero/negative entries."""
    try:
        new_count = _redis.hincrby(CONNECTION_COUNTS_KEY, event_id, -1)
        if new_count <= 0:
            _redis.hdel(CONNECTION_COUNTS_KEY, event_id)
    except redis.RedisError:
        logger.exception("live_analytics registry: failed to unregister event %s", event_id)


def get_active_event_ids():
    """Event ids with at least one open LiveAnalyticsConsumer socket right now.
    Returns None on Redis failure so callers can fall back to 'assume all
    live events are active' rather than silently pushing to nobody.

    Known gap: if a worker/Daphne process dies uncleanly, disconnect() never
    fires and a count can get stuck above zero (a phantom "active" event).
    Fine for now — a TTL on the hash field or a periodic reconciliation
    sweep would fix it if it becomes a problem.
    """
    try:
        return {int(eid) for eid in _redis.hkeys(CONNECTION_COUNTS_KEY)}
    except redis.RedisError:
        logger.exception("live_analytics registry: failed to read active event ids")
        return None