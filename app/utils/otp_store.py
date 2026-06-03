import asyncio
import logging
from typing import Optional

import redis

from app.core.config import settings


logger = logging.getLogger(__name__)


class OtpStore:
    def __init__(self):
        self._memory: dict[str, str] = {}
        self._redis: Optional[redis.Redis] = None
        if settings.redis_enabled:
            self._redis = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password or None,
                decode_responses=True,
            )

    def set(self, task_id: str, otp_code: str, expire_seconds: int = 600):
        key = self._key(task_id)
        if self._redis:
            self._redis.set(key, otp_code, ex=expire_seconds)
            return
        self._memory[key] = otp_code

    async def wait_for(self, task_id: str, timeout: int = 300, interval: int = 5) -> str:
        key = self._key(task_id)
        elapsed = 0
        while elapsed < timeout:
            code = self._redis.get(key) if self._redis else self._memory.get(key)
            if code:
                return code
            await asyncio.sleep(interval)
            elapsed += interval
        raise TimeoutError(f"等待 FB 绑定验证码超时: {task_id}")

    @staticmethod
    def _key(task_id: str) -> str:
        return f"fb_account_flow:{task_id}:otp"


otp_store = OtpStore()
