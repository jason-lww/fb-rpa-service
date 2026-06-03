from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

BindingStatus = Literal[
    "pending",
    "binding_requested",
    "code_received",
    "verifying",
    "success",
    "failed",
    "disconnected",
    "skipped",
    "unbind_pending",
    "unbinding",
    "unbound",
    "unbind_not_found",
    "unbind_ad_occupied",
    "unbind_failed",
]

BindingErrorType = Literal[
    "merchant_homepage",
    "feature_rate_limit",
    "non_business_account",
    "verification_failed",
    "automation_failed",
    "disconnected",
]

OtpLookupStatus = Literal["found", "pending", "unconnected", "invalid"]
WarpaAccountType = Literal["CAT", "TIGER", "FIVE_SEGMENT"]
WarpaFbBindStatus = Literal["WAITING_BIND", "BINDING", "BIND_SUCCESS", "BIND_RETRY", "BIND_FAILED"]


@dataclass
class NormalizedPhone:
    phone: str
    country_code: str
    original: str


@dataclass
class VerificationCodeResult:
    verification_code: str
    code: str
    otp_lookup_status: OtpLookupStatus = "pending"
    otp_message_timestamp_ms: Optional[int] = None
    otp_device_status: Optional[str] = None
    otp_lookup_message: Optional[str] = None


@dataclass
class BindingRecord:
    # NormalizedPhone
    phone: str
    country_code: str
    original: str

    id: str
    batch_id: str = ""
    operation: Literal["bind", "unbind"] = "bind"
    business_page_name: str = ""

    instance_id: Optional[str] = None
    jid: Optional[str] = None
    wa_type: Optional[WarpaAccountType] = None
    serial_no: Optional[str] = None
    tenant_id: Optional[str | int] = None
    proxy_ip: Optional[str] = None
    route_line_id: Optional[str | int] = None

    server_fb_bind_status: Optional[WarpaFbBindStatus] = None
    server_writeback_at: Optional[str] = None
    server_writeback_error: Optional[str] = None

    alert_type: Optional[Literal["merchant_homepage", "feature_rate_limit"]] = None
    merchant_alert_message: str = ""
    error_type: Optional[BindingErrorType] = None
    error_message: Optional[str] = None
    error_occurred_at: Optional[str] = None

    status: BindingStatus = "pending"
    success: bool = False
    attempt_count: int = 0
    first_task_at: str = ""
    bind_requested_at: str = ""
    code_received_at: str = ""
    first_success_at: str = ""
    bound_at: str = ""
    unbound_at: str = ""
    verification_code: str = ""
    otp_message_timestamp_ms: Optional[int] = None
    otp_device_status: Optional[str] = None
    otp_lookup_status: Optional[OtpLookupStatus] = None
    otp_lookup_message: Optional[str] = None
    last_error: str = ""
    page_url: str = ""


@dataclass
class NormalizePhoneResult:
    records: list[NormalizedPhone] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
