from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import OtpServiceEnvironment, settings
from app.shared.models import VerificationCodeResult, WarpaAccountType

# 移植自 server/gateway.ts + server/waRpaClient.ts
OTP_SERVICE_ENDPOINTS: dict[str, str] = {
    "production": "http://luna.mx.incubation.cloudun.ai/api/v1/incubation/wa-msg/device/verification-code",
    "test": "https://incubation.ics.whitecatear.com/api/v1/incubation/wa-msg/device/verification-code",
}
WARPA_BASE_URLS: dict[str, str] = {
    "production": "http://luna.mx.incubation.cloudun.ai/api/v1/incubation/wa-msg",
    "test": "https://incubation.ics.whitecatear.com/api/v1/incubation/wa-msg",
}


class GatewayCodePendingError(Exception):
    def __init__(self, message: str = "验证码尚未匹配到", details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class WarpaClientError(Exception):
    pass


@dataclass
class GatewayConnectionStatus:
    connected: bool
    status: str
    message: str


def _otp_url(env: OtpServiceEnvironment) -> str:
    return OTP_SERVICE_ENDPOINTS[env]


def _warpa_url(env: OtpServiceEnvironment, path: str) -> str:
    return f"{WARPA_BASE_URLS[env]}{path}"


def _headers(gateway_key: str) -> dict[str, str]:
    return {
        "content-type": "application/json; charset=utf-8",
        "X-Incubation-Gateway-Key": gateway_key,
    }


def _path(payload: Any, keys: list[str]) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _str_path(payload: Any, keys: list[str]) -> str:
    value = _path(payload, keys)
    return value.strip() if isinstance(value, str) else ""


def _num_path(payload: Any, keys: list[str]) -> Optional[int]:
    value = _path(payload, keys)
    try:
        if value is None:
            return None
        num = int(float(value))
        return num
    except (TypeError, ValueError):
        return None


def _extract_code_from_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    m = re.search(r"\b\d{5,6}\b", value)
    return m.group(0) if m else None


def _is_pending_payload(payload: Any) -> bool:
    status = _str_path(payload, ["status"]) or _str_path(payload, ["data", "status"])
    message = _str_path(payload, ["data", "message"]) or _str_path(payload, ["message"])
    has_explicit_empty = (
        _path(payload, ["verificationCode"]) is None or _path(payload, ["data", "verificationCode"]) is None
    )
    return status == "UNCONNECTED" or (
        status == "CONNECTED" and (has_explicit_empty or "未匹配到" in message or "未找到" in message)
    )


def extract_otp_result(payload: Any) -> VerificationCodeResult:
    value = (
        _path(payload, ["verificationCode"])
        or _path(payload, ["data", "code"])
        or _path(payload, ["data", "verificationCode"])
        or _extract_code_from_text(_path(payload, ["data", "message"]))
        or _extract_code_from_text(_path(payload, ["message"]))
        or _path(payload, ["code"])
    )
    code = str(value if value is not None else "").strip()
    otp_device_status = _str_path(payload, ["status"]) or _str_path(payload, ["data", "status"]) or None
    otp_lookup_message = (
        _str_path(payload, ["data", "message"]) or _str_path(payload, ["message"]) or None
    )
    otp_message_timestamp_ms = _num_path(payload, ["timestamp"]) or _num_path(payload, ["data", "timestamp"])

    if not re.fullmatch(r"\d{5,6}", code):
        if _is_pending_payload(payload):
            raise GatewayCodePendingError(
                otp_lookup_message or "验证码尚未匹配到",
                {
                    "otp_message_timestamp_ms": otp_message_timestamp_ms,
                    "otp_device_status": otp_device_status,
                    "otp_lookup_status": "unconnected" if otp_device_status == "UNCONNECTED" else "pending",
                    "otp_lookup_message": otp_lookup_message,
                },
            )
        raise ValueError("验证码响应无效")

    return VerificationCodeResult(
        verification_code=code,
        code=code,
        otp_message_timestamp_ms=otp_message_timestamp_ms,
        otp_device_status=otp_device_status,
        otp_lookup_status="found",
        otp_lookup_message=otp_lookup_message,
    )


def extract_connection_status(payload: Any) -> GatewayConnectionStatus:
    status = _str_path(payload, ["status"]) or _str_path(payload, ["data", "status"])
    message = _str_path(payload, ["data", "message"]) or _str_path(payload, ["message"])
    if not status:
        raise ValueError("验证码连接状态响应无效")
    return GatewayConnectionStatus(connected=status == "CONNECTED", status=status, message=message)


def _parse_base_response(payload: Any) -> Any:
    if not isinstance(payload, dict):
        raise WarpaClientError("WaRPA 接口响应不是有效 JSON 对象")
    code = payload.get("code")
    try:
        code_num = int(code)
    except (TypeError, ValueError):
        code_num = -1
    if code_num != 200:
        message = payload.get("message") if isinstance(payload.get("message"), str) else ""
        raise WarpaClientError(f"WaRPA 接口返回失败：{message or f'code {code}'}")
    return payload.get("data")


def _sanitize(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if v is not None and v != ""}


class IncubationClient:
    """养号系统（incubation）网关客户端：OTP + 连接检测 + WaRPA 待绑定/回写。"""

    def __init__(
        self,
        gateway_key: Optional[str] = None,
        environment: Optional[OtpServiceEnvironment] = None,
        timeout: float = 20.0,
    ):
        self.gateway_key = gateway_key if gateway_key is not None else settings.incubation_gateway_key
        self.environment: OtpServiceEnvironment = environment or settings.otp_service_environment
        self._timeout = timeout

    def _ensure_key(self) -> None:
        if not self.gateway_key:
            raise ValueError("未配置 INCUBATION_GATEWAY_KEY")

    async def request_otp_once(self, phone: str) -> VerificationCodeResult:
        """单次查询验证码；未匹配到时抛 GatewayCodePendingError。"""
        self._ensure_key()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _otp_url(self.environment), headers=_headers(self.gateway_key), json={"phone": phone}
            )
            payload = resp.json()
            if resp.status_code >= 400:
                raise WarpaClientError(f"验证码服务请求失败：HTTP {resp.status_code}")
            return extract_otp_result(payload)

    async def check_connection(self, phone: str) -> GatewayConnectionStatus:
        self._ensure_key()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _otp_url(self.environment), headers=_headers(self.gateway_key), json={"phone": phone}
            )
            payload = resp.json()
            if resp.status_code >= 400:
                raise WarpaClientError(f"验证码连接检查失败：HTTP {resp.status_code}")
            return extract_connection_status(payload)

    async def pending_fb_bind_list(self, request: dict[str, Any]) -> dict[str, Any]:
        self._ensure_key()
        body = _sanitize({"page": 1, "pageSize": 10, **request})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _warpa_url(self.environment, "/pending-fb-bind-list"),
                headers=_headers(self.gateway_key),
                json=body,
            )
            if resp.status_code >= 400:
                raise WarpaClientError(f"WaRPA 接口请求失败：HTTP {resp.status_code}")
            return _parse_base_response(resp.json()) or {}

    async def fb_bind_status(
        self,
        jid: str,
        status: str,
        wa_type: Optional[WarpaAccountType] = None,
        fb_page_name: str = "",
        fb_page_id: str = "",
    ) -> Any:
        self._ensure_key()
        body = _sanitize(
            {"jid": jid, "status": status, "type": wa_type, "fbPageName": fb_page_name, "fbPageId": fb_page_id}
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _warpa_url(self.environment, "/fb-bind-status"),
                headers=_headers(self.gateway_key),
                json=body,
            )
            if resp.status_code >= 400:
                raise WarpaClientError(f"WaRPA 接口请求失败：HTTP {resp.status_code}")
            return _parse_base_response(resp.json())
