"""Redis client - dipakai untuk cache & nanti queue.

Implementasi tahan banting: kalau Redis offline, app tidak crash.
"""
import json
import logging
from typing import Any, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self, url: str):
        self.url = url
        self._client: Optional[redis.Redis] = None
        self._available = False
        self._connect()

    def _connect(self) -> None:
        try:
            self._client = redis.Redis.from_url(
                self.url, decode_responses=True, socket_connect_timeout=2
            )
            self._client.ping()
            self._available = True
            logger.info("Redis connected: %s", self.url)
        except Exception as e:  # pragma: no cover
            self._available = False
            logger.warning("Redis NOT available (%s) - running without cache", e)

    @property
    def available(self) -> bool:
        return self._available

    def set_json(self, key: str, value: Any, ttl: int = 300) -> bool:
        if not self._available or not self._client:
            return False
        try:
            self._client.set(key, json.dumps(value, default=str), ex=ttl)
            return True
        except Exception as e:
            logger.warning("Redis SET failed: %s", e)
            return False

    def get_json(self, key: str) -> Any:
        if not self._available or not self._client:
            return None
        try:
            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning("Redis GET failed: %s", e)
            return None

    def delete(self, *keys: str) -> int:
        if not self._available or not self._client:
            return 0
        try:
            return self._client.delete(*keys)
        except Exception:
            return 0

    def incr(self, key: str, ttl: int = 60) -> int:
        if not self._available or not self._client:
            return 0
        try:
            val = self._client.incr(key)
            if val == 1:
                self._client.expire(key, ttl)
            return val
        except Exception:
            return 0


redis_client = RedisClient(settings.REDIS_URL)
