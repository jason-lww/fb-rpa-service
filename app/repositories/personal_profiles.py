from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db.session import get_engine
from app.repositories._util import format_dt


def list_personal_profiles() -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT profile_id, profile_name, created_at, updated_at
                FROM personal_profiles
                ORDER BY created_at ASC, profile_name ASC
                """
            )
        ).fetchall()
    return [
        {
            "profileId": r.profile_id,
            "profileName": r.profile_name,
            "createdAt": format_dt(r.created_at),
            "updatedAt": format_dt(r.updated_at),
        }
        for r in rows
    ]


def create_personal_profile(profile_id: str, profile_name: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO personal_profiles (profile_id, profile_name, updated_at)
                VALUES (:profile_id, :profile_name, NOW())
                ON DUPLICATE KEY UPDATE profile_name = VALUES(profile_name), updated_at = NOW()
                """
            ),
            {"profile_id": profile_id, "profile_name": profile_name},
        )


def update_personal_profile(profile_id: str, profile_name: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE personal_profiles SET profile_name = :profile_name, updated_at = NOW()
                WHERE profile_id = :profile_id
                """
            ),
            {"profile_name": profile_name, "profile_id": profile_id},
        )


def count_linked_merchants(profile_id: str) -> int:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) AS count FROM merchants WHERE personal_profile_id = :profile_id"),
            {"profile_id": profile_id},
        ).first()
    return int(row.count if row else 0)


def delete_personal_profile(profile_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM personal_profiles WHERE profile_id = :profile_id"), {"profile_id": profile_id}
        )
