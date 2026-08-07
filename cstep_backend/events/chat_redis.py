# Ephemeral reaction counters. Not persisted to Postgres — lives entirely in
# Redis as a hash per event: event:{id}:chat:reactions -> {like: N, love: N, clap: N}
#
# Assumes settings.REDIS_URL is defined (adjust if you use a different var,
# e.g. settings.CHANNEL_REDIS_URL or a django-redis cache alias).

import redis
from django.conf import settings

from .constants import ChatReactionType

_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _reaction_key(event_id):
    return f"event:{event_id}:chat:reactions"


def increment_reaction(event_id, reaction_type):
    client = get_redis_client()
    return client.hincrby(_reaction_key(event_id), reaction_type, 1)


def get_reaction_counts(event_id):
    client = get_redis_client()
    raw = client.hgetall(_reaction_key(event_id))
    counts = {choice.value: 0 for choice in ChatReactionType}
    counts.update({k: int(v) for k, v in raw.items()})
    return counts


def reset_reaction_counts(event_id):
    """
    Call this explicitly if/when you want a clean slate — e.g. from a
    management command or when an event's status flips to LIVE. Not
    wired up automatically, since "reset on what trigger" is a product
    decision, not a technical one.
    """
    client = get_redis_client()
    client.delete(_reaction_key(event_id))