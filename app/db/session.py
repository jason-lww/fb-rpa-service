from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None


def db_enabled() -> bool:
    return bool(settings.database_url)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("未配置 DATABASE_URL，无法连接 MySQL")
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )
    return _engine
