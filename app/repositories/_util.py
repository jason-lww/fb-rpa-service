from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional


def merchant_id_for(name: str) -> str:
    return "merchant-" + hashlib.md5(name.encode("utf-8")).hexdigest()[:16]


def page_name_id_for(name: str) -> str:
    return "name-" + name.encode("utf-8").hex()[:32]


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """ISO8601 字符串 → naive UTC datetime（用于写入 MySQL DATETIME）。"""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def format_dt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
