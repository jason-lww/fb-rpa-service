from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Optional

from app.shared.models import BindingRecord, NormalizedPhone, WarpaAccountType, WarpaFbBindStatus
from app.shared.phone import normalize_phone
from app.shared.queue import create_binding_queue

BINDABLE_STATUSES = {"WAITING_BIND", "BINDING", "BIND_RETRY"}


def _normalize_jid(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    account = text.split("@", 1)[0].split(":", 1)[0].strip()
    return account or text


def _normalize_account_type(value: Any) -> Optional[WarpaAccountType]:
    return value if value in ("CAT", "TIGER", "FIVE_SEGMENT") else None


def _bindable_status(value: Any) -> Optional[WarpaFbBindStatus]:
    return value if value in BINDABLE_STATUSES else None


def create_warpa_binding_queue(instances: list[dict[str, Any]], batch_id: str = "") -> list[BindingRecord]:
    seen: set[str] = set()
    eligible: list[tuple[dict[str, Any], str, NormalizedPhone, str]] = []
    for instance in instances:
        jid = _normalize_jid(instance.get("jid"))
        normalized = normalize_phone(jid) if jid else None
        status = _bindable_status(instance.get("fbBindStatus"))
        if not normalized or not status:
            continue
        dedupe_key = f"{normalized.country_code}:{normalized.phone}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        eligible.append((instance, jid, normalized, status))

    base = create_binding_queue([e[2] for e in eligible], batch_id)
    records: list[BindingRecord] = []
    for record, (instance, jid, _normalized, status) in zip(base, eligible):
        records.append(
            replace(
                record,
                instance_id=(instance.get("instanceId") or None),
                jid=jid,
                wa_type=_normalize_account_type(instance.get("type") or instance.get("waType")),
                serial_no=(instance.get("serialNo") or None),
                tenant_id=instance.get("tenantId"),
                proxy_ip=(instance.get("proxyIp") or None),
                route_line_id=instance.get("routeLineId"),
                server_fb_bind_status=status,
            )
        )
    return records


def get_writeback_status(record: BindingRecord) -> Optional[str]:
    if record.status == "success":
        return "BIND_SUCCESS"
    if record.status == "disconnected":
        return "BIND_RETRY"
    if record.status == "failed" and record.error_type not in ("merchant_homepage", "non_business_account"):
        return "BIND_RETRY"
    return None


def mark_writeback_success(record: BindingRecord, status: str) -> BindingRecord:
    return replace(
        record,
        server_fb_bind_status=status,
        server_writeback_at=datetime.now(timezone.utc).isoformat(),
        server_writeback_error="",
    )


def mark_writeback_failure(record: BindingRecord, error: str) -> BindingRecord:
    return replace(
        record, server_writeback_at=datetime.now(timezone.utc).isoformat(), server_writeback_error=error
    )
