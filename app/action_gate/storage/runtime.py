"""Redis runtime cache.

Redis holds only state whose loss is harmless: cached configuration releases, replayed semantic
observations and short-lived leases. It is never the only record of an invocation, an audit event,
a budget balance or an executed action. Every call degrades to a miss instead of raising, so a
Redis outage slows the gate down but cannot change a decision.
"""
from datetime import datetime, timezone
import json

OBSERVATION_TTL_SECONDS = 900
RELEASE_TTL_SECONDS = 60


class NullRuntime:
    """Used when runtime caching is disabled or not configured."""

    enabled = False
    name = 'disabled'

    def get_observation(self, key):
        return None

    def put_observation(self, key, record):
        return False

    def lease(self, key, ttl_seconds=30):
        return True

    def health(self):
        return {'enabled': False}


class RedisRuntime:
    enabled = True
    name = 'redis'

    def __init__(self, client, prefix='action-gate'):
        self.client = client
        self.prefix = prefix
        self.last_error = None

    @classmethod
    def from_environment(cls, environ):
        import redis
        client = redis.Redis(
            host=environ.get('REDIS_HOST', 'redis'),
            port=int(environ.get('REDIS_PORT', '6379') or 6379),
            db=int(environ.get('REDIS_DB', '0') or 0),
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
            decode_responses=True,
        )
        return cls(client)

    # -- keys ---------------------------------------------------------------------
    def _observation_key(self, key: dict) -> str:
        return '{}:obs:{}:{}:{}:{}:{}'.format(self.prefix, key['profile_id'], key['model_id'],
                                              key['direction'], key['instruction_version'],
                                              key['projection_hash'])

    # -- operations ---------------------------------------------------------------
    def get_observation(self, key):
        try:
            raw = self.client.get(self._observation_key(key))
            return json.loads(raw) if raw else None
        except Exception as exc:
            self.last_error = type(exc).__name__
            return None

    def put_observation(self, key, record):
        try:
            self.client.set(self._observation_key(key), json.dumps(record, default=str),
                            ex=OBSERVATION_TTL_SECONDS)
            return True
        except Exception as exc:
            self.last_error = type(exc).__name__
            return False

    def lease(self, key, ttl_seconds=30):
        """Best-effort temporary coordination. A lost lease never re-permits an executed action."""
        try:
            return bool(self.client.set('{}:lease:{}'.format(self.prefix, key), '1', nx=True,
                                        ex=max(1, int(ttl_seconds))))
        except Exception as exc:
            self.last_error = type(exc).__name__
            return True

    def health(self):
        try:
            info = self.client.info(section='memory')
            return {'enabled': True, 'connected': True, 'name': self.name,
                    'usedMemoryBytes': info.get('used_memory'),
                    'maxmemoryPolicy': self.client.config_get('maxmemory-policy').get('maxmemory-policy'),
                    'persistence': {'rdb': self.client.config_get('save').get('save') or '',
                                    'aof': self.client.config_get('appendonly').get('appendonly')},
                    'checkedAt': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                    'lastError': self.last_error}
        except Exception as exc:
            return {'enabled': True, 'connected': False, 'name': self.name,
                    'error': type(exc).__name__, 'lastError': self.last_error}
