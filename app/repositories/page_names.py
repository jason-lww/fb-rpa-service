from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text

from app.db.session import get_engine
from app.repositories._util import format_dt, page_name_id_for


def list_page_names() -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT name_id, page_name, status, allocated_at, created_at, updated_at
                FROM page_names
                ORDER BY created_at ASC, page_name ASC
                """
            )
        ).fetchall()
    return [
        {
            "nameId": r.name_id,
            "pageName": r.page_name,
            "status": "ALLOCATED" if r.status == "ALLOCATED" else "NAME_POOL",
            "allocatedAt": format_dt(r.allocated_at),
            "createdAt": format_dt(r.created_at),
            "updatedAt": format_dt(r.updated_at),
        }
        for r in rows
    ]


def create_page_names(names: list[str]) -> None:
    with get_engine().begin() as conn:
        for name in names:
            conn.execute(
                text(
                    """
                    INSERT IGNORE INTO page_names (name_id, page_name, status, updated_at)
                    VALUES (:name_id, :page_name, 'NAME_POOL', NOW())
                    """
                ),
                {"name_id": page_name_id_for(name), "page_name": name},
            )


def get_next_page_name() -> Optional[dict[str, Any]]:
    """随机取一个 NAME_POOL 名字并置为 ALLOCATED（行锁避免并发重复分配）。

    注：MySQL 5.7 不支持 SKIP LOCKED，使用普通 FOR UPDATE。
    """
    with get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT name_id, page_name FROM page_names
                WHERE status = 'NAME_POOL'
                ORDER BY RAND() LIMIT 1
                FOR UPDATE
                """
            )
        ).first()
        if not row:
            return None
        conn.execute(
            text(
                """
                UPDATE page_names
                SET status = 'ALLOCATED', allocated_at = NOW(), updated_at = NOW()
                WHERE name_id = :name_id
                """
            ),
            {"name_id": row.name_id},
        )
        return {"nameId": row.name_id, "merchantId": row.name_id, "pageName": row.page_name}


def release_page_name(data: dict[str, Any]) -> None:
    name_id = data.get("nameId") or data.get("merchantId") or ""
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE page_names
                SET status = 'NAME_POOL', allocated_at = NULL, updated_at = NOW()
                WHERE name_id = :name_id AND page_name = :page_name AND status = 'ALLOCATED'
                """
            ),
            {"name_id": name_id, "page_name": data.get("pageName") or ""},
        )


def consume_page_name(data: dict[str, Any]) -> None:
    name_id = data.get("nameId") or data.get("merchantId") or ""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM page_names WHERE name_id = :name_id"), {"name_id": name_id})


def delete_by_page_name(page_name: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM page_names WHERE page_name = :page_name"), {"page_name": page_name})
