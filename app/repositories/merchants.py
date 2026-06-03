from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db.session import get_engine
from app.repositories._util import format_dt, merchant_id_for, parse_iso

UNAVAILABLE_STATUS_TYPES = {"merchant_homepage", "feature_rate_limit"}


class FbPageDuplicateError(Exception):
    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


def _row_to_merchant(row: Any) -> dict[str, Any]:
    page_created_at = format_dt(row.page_created_at)
    latest_status_type = row.latest_status_type or ""
    return {
        "merchantId": row.merchant_id,
        "merchantName": row.merchant_name,
        "fbPageId": row.fb_page_id or "",
        "personalProfileId": row.personal_profile_id or "",
        "personalProfileName": row.personal_profile_name or "",
        "creationStatus": "created" if page_created_at else "pending",
        "createdPageUrl": row.created_page_url or "",
        "pageCreatedAt": page_created_at,
        "bindingAvailability": "unavailable" if latest_status_type in UNAVAILABLE_STATUS_TYPES else "available",
        "boundWaCount": int(row.manual_bound_wa_count or 0),
        "latestAlertMessage": row.latest_status_message or "",
        "latestStatusUpdatedAt": format_dt(row.latest_status_updated_at),
    }


def list_merchants() -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT merchant_id, merchant_name, fb_page_id, personal_profile_id, personal_profile_name,
                       manual_bound_wa_count, created_page_url, page_created_at,
                       latest_status_type, latest_status_message, latest_status_updated_at,
                       created_at, updated_at
                FROM merchants
                ORDER BY created_at ASC, merchant_name ASC
                """
            )
        ).fetchall()
    return [_row_to_merchant(r) for r in rows]


def create_merchant_from_created_page(data: dict[str, Any]) -> None:
    merchant_id = (data.get("merchantId") or "").strip() or merchant_id_for(data["pageName"])
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO merchants (
                  merchant_id, merchant_name, fb_page_id, personal_profile_id, personal_profile_name,
                  manual_bound_wa_count, created_page_url, page_created_at, page_pool_status, updated_at
                ) VALUES (
                  :merchant_id, :merchant_name, :fb_page_id, :personal_profile_id, :personal_profile_name,
                  0, :created_page_url, :page_created_at, 'FB_PAGE', NOW()
                )
                ON DUPLICATE KEY UPDATE
                  fb_page_id = VALUES(fb_page_id),
                  personal_profile_id = VALUES(personal_profile_id),
                  personal_profile_name = VALUES(personal_profile_name),
                  created_page_url = VALUES(created_page_url),
                  page_created_at = VALUES(page_created_at),
                  page_pool_status = 'FB_PAGE',
                  updated_at = NOW()
                """
            ),
            {
                "merchant_id": merchant_id,
                "merchant_name": data["pageName"],
                "fb_page_id": data.get("fbPageId") or "",
                "personal_profile_id": data.get("personalProfileId") or "",
                "personal_profile_name": data.get("personalProfileName") or "",
                "created_page_url": data.get("pageUrl") or "",
                "page_created_at": parse_iso(data.get("createdAt")),
            },
        )


def update_bound_wa_count(merchant_id: str, bound_wa_count: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE merchants
                SET manual_bound_wa_count = :count, page_pool_status = 'FB_PAGE', updated_at = NOW()
                WHERE merchant_id = :merchant_id
                """
            ),
            {"count": bound_wa_count, "merchant_id": merchant_id},
        )


def create_merchant(data: dict[str, Any]) -> None:
    with get_engine().begin() as conn:
        existing = conn.execute(
            text(
                """
                SELECT merchant_name, fb_page_id FROM merchants
                WHERE merchant_name = :name OR (:fb_page_id <> '' AND fb_page_id = :fb_page_id)
                """
            ),
            {"name": data["merchantName"], "fb_page_id": data.get("fbPageId") or ""},
        ).fetchall()
        for row in existing:
            if row.merchant_name == data["merchantName"]:
                raise FbPageDuplicateError("FB 公共主页管理中已存在同名主页，请勿重复创建", "merchantName")
            if (data.get("fbPageId") or "") != "" and (row.fb_page_id or "") == data.get("fbPageId"):
                raise FbPageDuplicateError("FB 公共主页管理中已存在相同主页 ID，请勿重复创建", "fbPageId")

        conn.execute(
            text(
                """
                INSERT INTO merchants (
                  merchant_id, merchant_name, fb_page_id, personal_profile_id, personal_profile_name,
                  manual_bound_wa_count, page_pool_status, updated_at
                ) VALUES (
                  :merchant_id, :merchant_name, :fb_page_id, :personal_profile_id, :personal_profile_name,
                  :bound, 'FB_PAGE', NOW()
                )
                ON DUPLICATE KEY UPDATE
                  merchant_name = VALUES(merchant_name),
                  fb_page_id = VALUES(fb_page_id),
                  personal_profile_id = VALUES(personal_profile_id),
                  personal_profile_name = VALUES(personal_profile_name),
                  manual_bound_wa_count = VALUES(manual_bound_wa_count),
                  page_pool_status = 'FB_PAGE',
                  updated_at = NOW()
                """
            ),
            {
                "merchant_id": data["merchantId"],
                "merchant_name": data["merchantName"],
                "fb_page_id": data.get("fbPageId") or "",
                "personal_profile_id": data.get("personalProfileId") or "",
                "personal_profile_name": data.get("personalProfileName") or "",
                "bound": int(data.get("boundWaCount") or 0),
            },
        )


def update_merchant(data: dict[str, Any]) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE merchants
                SET merchant_name = :merchant_name,
                    fb_page_id = :fb_page_id,
                    personal_profile_id = :personal_profile_id,
                    personal_profile_name = :personal_profile_name,
                    manual_bound_wa_count = :bound,
                    page_pool_status = 'FB_PAGE',
                    updated_at = NOW()
                WHERE merchant_id = :merchant_id
                """
            ),
            {
                "merchant_name": data["merchantName"],
                "fb_page_id": data.get("fbPageId") or "",
                "personal_profile_id": data.get("personalProfileId") or "",
                "personal_profile_name": data.get("personalProfileName") or "",
                "bound": int(data.get("boundWaCount") or 0),
                "merchant_id": data["merchantId"],
            },
        )
