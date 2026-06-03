from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from app.shared.models import BindingRecord, NormalizedPhone, VerificationCodeResult

MAX_ATTEMPTS = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_binding_queue(phones: list[NormalizedPhone], batch_id: str = "") -> list[BindingRecord]:
    return [
        BindingRecord(
            phone=p.phone,
            country_code=p.country_code,
            original=p.original,
            id=f"{p.country_code}-{p.phone}-{index}",
            batch_id=batch_id,
            operation="bind",
            status="pending",
        )
        for index, p in enumerate(phones)
    ]


def create_unbind_queue(
    phones: list[NormalizedPhone], business_page_name: str, batch_id: str = ""
) -> list[BindingRecord]:
    return [
        BindingRecord(
            phone=p.phone,
            country_code=p.country_code,
            original=p.original,
            id=f"unbind-{p.country_code}-{p.phone}-{index}",
            batch_id=batch_id,
            operation="unbind",
            business_page_name=business_page_name,
            status="unbind_pending",
        )
        for index, p in enumerate(phones)
    ]


def mark_requested(record: BindingRecord, at: Optional[str] = None, page_url: str = "") -> BindingRecord:
    at = at or _now()
    return replace(
        record,
        status="binding_requested",
        attempt_count=record.attempt_count + 1,
        first_task_at=record.first_task_at or at,
        bind_requested_at=at,
        page_url=page_url,
        last_error="",
        alert_type=None,
        merchant_alert_message="",
    )


def mark_code_received(
    record: BindingRecord, code: str | VerificationCodeResult, at: Optional[str] = None
) -> BindingRecord:
    at = at or _now()
    if isinstance(code, VerificationCodeResult):
        return replace(
            record,
            status="code_received",
            code_received_at=at,
            verification_code=code.verification_code,
            otp_message_timestamp_ms=code.otp_message_timestamp_ms,
            otp_device_status=code.otp_device_status,
            otp_lookup_status=code.otp_lookup_status,
            otp_lookup_message=code.otp_lookup_message,
            last_error="",
            alert_type=None,
            merchant_alert_message="",
        )
    return replace(
        record,
        status="code_received",
        code_received_at=at,
        verification_code=code,
        last_error="",
        alert_type=None,
        merchant_alert_message="",
    )


def mark_verifying(record: BindingRecord) -> BindingRecord:
    return replace(record, status="verifying", last_error="", alert_type=None, merchant_alert_message="")


def mark_success(record: BindingRecord, at: Optional[str] = None) -> BindingRecord:
    at = at or _now()
    return replace(
        record,
        status="success",
        success=True,
        first_task_at=record.first_task_at or at,
        first_success_at=record.first_success_at or at,
        bound_at=at,
        last_error="",
        alert_type=None,
        merchant_alert_message="",
    )


def mark_unbinding(record: BindingRecord, at: Optional[str] = None, page_url: str = "") -> BindingRecord:
    at = at or _now()
    return replace(
        record,
        status="unbinding",
        attempt_count=record.attempt_count + 1,
        first_task_at=record.first_task_at or at,
        bind_requested_at=at,
        page_url=page_url,
        last_error="",
        alert_type=None,
        merchant_alert_message="",
    )


def mark_unbound(record: BindingRecord, at: Optional[str] = None) -> BindingRecord:
    at = at or _now()
    return replace(
        record,
        status="unbound",
        success=True,
        first_task_at=record.first_task_at or at,
        first_success_at=record.first_success_at or at,
        unbound_at=at,
        last_error="",
        alert_type=None,
        merchant_alert_message="",
    )


def mark_unbind_not_found(record: BindingRecord, error: str = "无法找到", at: Optional[str] = None) -> BindingRecord:
    at = at or _now()
    return replace(
        record, status="unbind_not_found", success=False, first_task_at=record.first_task_at or at, last_error=error
    )


def mark_unbind_ad_occupied(record: BindingRecord, error: str = "广告占用中", at: Optional[str] = None) -> BindingRecord:
    at = at or _now()
    return replace(
        record, status="unbind_ad_occupied", success=False, first_task_at=record.first_task_at or at, last_error=error
    )


def mark_unbind_failed(record: BindingRecord, error: str, at: Optional[str] = None) -> BindingRecord:
    at = at or _now()
    return replace(
        record, status="unbind_failed", success=False, first_task_at=record.first_task_at or at, last_error=error
    )


def fail_current(record: BindingRecord, error: str, at: Optional[str] = None) -> BindingRecord:
    at = at or _now()
    return replace(record, status="failed", success=False, first_task_at=record.first_task_at or at, last_error=error)


def mark_disconnected(record: BindingRecord, message: str, at: Optional[str] = None) -> BindingRecord:
    at = at or _now()
    return replace(
        record,
        status="disconnected",
        success=False,
        first_task_at=record.first_task_at or at,
        last_error=message,
        error_type="disconnected",
        error_message=message,
        error_occurred_at=at,
        alert_type=None,
        merchant_alert_message="",
    )


def should_retry(record: BindingRecord) -> bool:
    return record.attempt_count < MAX_ATTEMPTS


def is_terminal_status(status: str) -> bool:
    return status in {
        "success",
        "failed",
        "disconnected",
        "skipped",
        "unbound",
        "unbind_not_found",
        "unbind_ad_occupied",
        "unbind_failed",
    }
