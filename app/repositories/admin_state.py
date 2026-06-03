from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text

from app.db.session import get_engine
from app.repositories._util import format_dt, merchant_id_for, parse_iso

UNAVAILABLE_ALERT_TYPES = {"merchant_homepage", "feature_rate_limit"}


def empty_admin_state() -> dict[str, Any]:
    return {
        "batches": [],
        "records": [],
        "operationLog": [],
        "summary": "",
        "currentOperation": "",
        "updatedAt": "",
    }


def save_snapshot(snapshot: dict[str, Any], updated_at_iso: str) -> None:
    batch_id = _normalize_batch_id(snapshot.get("batchId"), updated_at_iso)
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), str) else ""
    current_operation = (
        snapshot.get("currentOperation") if isinstance(snapshot.get("currentOperation"), str) else ""
    )
    records = _normalize_array(snapshot.get("records"))
    operation_log = _normalize_array(snapshot.get("operationLog"))
    updated_at = parse_iso(updated_at_iso) or datetime.utcnow()

    with get_engine().begin() as conn:
        existing = conn.execute(
            text(
                """
                SELECT id, status FROM admin_binding_records
                WHERE batch_id = :batch_id AND status IN ('success', 'unbound')
                """
            ),
            {"batch_id": batch_id},
        ).fetchall()
        existing_success = {r.id for r in existing if r.status == "success"}
        existing_unbound = {r.id for r in existing if r.status == "unbound"}

        success_increments = _success_increments(records, batch_id, existing_success)
        unbind_decrements = _unbind_decrements(records, batch_id, existing_unbound)

        conn.execute(
            text(
                """
                INSERT INTO admin_batches (batch_id, summary, current_operation, started_at, updated_at)
                VALUES (:batch_id, :summary, :current_operation, :updated_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                  summary = VALUES(summary),
                  current_operation = VALUES(current_operation),
                  updated_at = VALUES(updated_at)
                """
            ),
            {
                "batch_id": batch_id,
                "summary": summary,
                "current_operation": current_operation,
                "updated_at": updated_at,
            },
        )

        conn.execute(text("DELETE FROM admin_binding_records WHERE batch_id = :b"), {"b": batch_id})
        conn.execute(text("DELETE FROM admin_operation_logs WHERE batch_id = :b"), {"b": batch_id})

        for index, record in enumerate(records):
            payload = {**record, "batchId": batch_id}
            conn.execute(
                text(
                    """
                    INSERT INTO admin_binding_records (id, batch_id, phone, payload, updated_at)
                    VALUES (:id, :batch_id, :phone, :payload, :updated_at)
                    """
                ),
                {
                    "id": _normalize_record_id(record, batch_id, index),
                    "batch_id": batch_id,
                    "phone": record.get("phone") if isinstance(record.get("phone"), str) else "",
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "updated_at": updated_at,
                },
            )

        for index, entry in enumerate(operation_log):
            payload = {**entry, "batchId": batch_id}
            conn.execute(
                text(
                    """
                    INSERT INTO admin_operation_logs (id, batch_id, phone, time, payload)
                    VALUES (:id, :batch_id, :phone, :time, :payload)
                    """
                ),
                {
                    "id": _normalize_log_id(entry, batch_id, index),
                    "batch_id": batch_id,
                    "phone": entry.get("phone") if isinstance(entry.get("phone"), str) else None,
                    "time": parse_iso(_normalize_log_time(entry, updated_at_iso)) or updated_at,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )

        for merchant_name, increment in success_increments.items():
            conn.execute(
                text(
                    """
                    INSERT INTO merchants (merchant_id, merchant_name, manual_bound_wa_count, page_pool_status, updated_at)
                    VALUES (:merchant_id, :merchant_name, :inc, 'FB_PAGE', :updated_at)
                    ON DUPLICATE KEY UPDATE
                      manual_bound_wa_count = manual_bound_wa_count + VALUES(manual_bound_wa_count),
                      page_pool_status = 'FB_PAGE',
                      updated_at = VALUES(updated_at)
                    """
                ),
                {
                    "merchant_id": merchant_id_for(merchant_name),
                    "merchant_name": merchant_name,
                    "inc": increment,
                    "updated_at": updated_at,
                },
            )

        for merchant_name, decrement in unbind_decrements.items():
            conn.execute(
                text(
                    """
                    UPDATE merchants
                    SET manual_bound_wa_count = GREATEST(manual_bound_wa_count - :dec, 0),
                        page_pool_status = 'FB_PAGE',
                        updated_at = :updated_at
                    WHERE merchant_name = :merchant_name
                    """
                ),
                {"dec": decrement, "merchant_name": merchant_name, "updated_at": updated_at},
            )

        for status in _latest_merchant_status_updates(records, updated_at_iso):
            conn.execute(
                text(
                    """
                    UPDATE merchants
                    SET latest_status_type = :type, latest_status_message = :message,
                        latest_status_updated_at = :occurred, updated_at = :occurred
                    WHERE merchant_name = :merchant_name
                    """
                ),
                {
                    "type": status["type"],
                    "message": status["message"],
                    "occurred": parse_iso(status["occurredAt"]) or updated_at,
                    "merchant_name": status["merchantName"],
                },
            )


def read_state() -> dict[str, Any]:
    with get_engine().connect() as conn:
        batch_rows = conn.execute(
            text(
                """
                SELECT batch_id, summary, current_operation, started_at, updated_at
                FROM admin_batches ORDER BY started_at ASC, batch_id ASC
                """
            )
        ).fetchall()
        if not batch_rows:
            return empty_admin_state()
        record_rows = conn.execute(
            text(
                "SELECT batch_id, payload FROM admin_binding_records ORDER BY updated_at ASC, batch_id ASC, id ASC"
            )
        ).fetchall()
        log_rows = conn.execute(
            text("SELECT batch_id, payload FROM admin_operation_logs ORDER BY time ASC, batch_id ASC, id ASC")
        ).fetchall()

    records_by_batch = _group_payloads(record_rows)
    logs_by_batch = _group_payloads(log_rows)
    batches = [
        {
            "batchId": row.batch_id,
            "records": records_by_batch.get(row.batch_id, []),
            "operationLog": logs_by_batch.get(row.batch_id, []),
            "summary": row.summary or "",
            "currentOperation": row.current_operation or "",
            "startedAt": format_dt(row.started_at),
            "updatedAt": format_dt(row.updated_at),
        }
        for row in batch_rows
    ]
    latest = batches[-1]
    return {
        "batches": batches,
        "records": [r for b in batches for r in b["records"]],
        "operationLog": [e for b in batches for e in b["operationLog"]],
        "summary": latest["summary"],
        "currentOperation": latest["currentOperation"],
        "updatedAt": latest["updatedAt"],
    }


# ---------- helpers (移植自 adminStateRepository.ts) ----------
def _group_payloads(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        payload = row.payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        groups.setdefault(row.batch_id, []).append({**payload, "batchId": row.batch_id})
    return groups


def _normalize_array(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


def _success_increments(records: list[dict[str, Any]], batch_id: str, existing: set[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for index, record in enumerate(records):
        if _gstr(record, "status") != "success" or _gstr(record, "operation") == "unbind":
            continue
        if _normalize_record_id(record, batch_id, index) in existing:
            continue
        name = _gstr(record, "businessPageName")
        if not name:
            continue
        out[name] = out.get(name, 0) + 1
    return out


def _unbind_decrements(records: list[dict[str, Any]], batch_id: str, existing: set[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for index, record in enumerate(records):
        if _gstr(record, "status") != "unbound":
            continue
        if _normalize_record_id(record, batch_id, index) in existing:
            continue
        name = _gstr(record, "businessPageName")
        if not name:
            continue
        out[name] = out.get(name, 0) + 1
    return out


def _latest_merchant_status_updates(records: list[dict[str, Any]], fallback_iso: str) -> list[dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for record in records:
        status = _extract_merchant_status_update(record, fallback_iso)
        if not status:
            continue
        existing = latest.get(status["merchantName"])
        if not existing or _parse_ms(existing["occurredAt"]) <= _parse_ms(status["occurredAt"]):
            latest[status["merchantName"]] = status
    return list(latest.values())


def _extract_merchant_status_update(record: dict[str, Any], fallback_iso: str) -> Optional[dict[str, str]]:
    merchant_name = _gstr(record, "businessPageName")
    alert_type = _gstr(record, "alertType")
    type_ = _gstr(record, "errorType") or (alert_type if alert_type in UNAVAILABLE_ALERT_TYPES else "")
    message = _gstr(record, "errorMessage") or _gstr(record, "merchantAlertMessage") or _gstr(record, "lastError")
    if not merchant_name or not type_ or not message:
        return None
    occurred = _gstr(record, "errorOccurredAt") or _latest_record_time(record) or fallback_iso
    return {"merchantName": merchant_name, "type": type_, "message": message, "occurredAt": occurred}


def _latest_record_time(record: dict[str, Any]) -> str:
    for key in ("boundAt", "firstSuccessAt", "codeReceivedAt", "bindRequestedAt", "firstTaskAt"):
        value = _gstr(record, key)
        if value:
            return value
    return ""


def _gstr(value: dict[str, Any], key: str) -> str:
    candidate = value.get(key)
    return candidate.strip() if isinstance(candidate, str) else ""


def _parse_ms(iso: str) -> float:
    dt = parse_iso(iso)
    return dt.timestamp() if dt else 0.0


def _normalize_batch_id(value: Any, fallback_iso: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return re.sub(r"\D", "", fallback_iso)[:14]


def _normalize_record_id(record: dict[str, Any], batch_id: str, index: int) -> str:
    rid = record.get("id")
    return rid.strip() if isinstance(rid, str) and rid.strip() else f"{batch_id}-record-{index}"


def _normalize_log_id(entry: dict[str, Any], batch_id: str, index: int) -> str:
    lid = entry.get("id")
    return lid.strip() if isinstance(lid, str) and lid.strip() else f"{batch_id}-log-{index}"


def _normalize_log_time(entry: dict[str, Any], fallback_iso: str) -> str:
    time_value = entry.get("time")
    return time_value if isinstance(time_value, str) and time_value else fallback_iso
