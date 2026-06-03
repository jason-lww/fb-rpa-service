from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from app.clients.incubation import GatewayCodePendingError, IncubationClient
from app.shared.models import VerificationCodeResult

logger = logging.getLogger(__name__)

OTP_INITIAL_DELAY_MS = 5_000
OTP_MAX_ATTEMPTS = 5
OTP_POLL_INTERVAL_MS = 15_000

ProgressCb = Callable[[str], Awaitable[None] | None]


async def _emit(cb: Optional[ProgressCb], message: str) -> None:
    if cb is None:
        return
    result = cb(message)
    if asyncio.iscoroutine(result):
        await result


async def fetch_verification_code(
    client: IncubationClient,
    phone: str,
    *,
    initial_delay_ms: int = OTP_INITIAL_DELAY_MS,
    max_attempts: int = OTP_MAX_ATTEMPTS,
    poll_interval_ms: int = OTP_POLL_INTERVAL_MS,
    should_continue: Optional[Callable[[], bool]] = None,
    on_progress: Optional[ProgressCb] = None,
) -> VerificationCodeResult:
    """先等 initial_delay，再每 poll_interval 查一次，最多 max_attempts 次。"""
    last_pending_message = "验证码尚未匹配到"

    for attempt in range(1, max_attempts + 1):
        _assert_continue(should_continue)
        delay_ms = initial_delay_ms if attempt == 1 else poll_interval_ms
        await _emit(
            on_progress, f"{attempt}/{max_attempts} 次请求 OTP，{round(delay_ms / 1000)}s 后查询验证码服务"
        )
        await _sleep_ms(delay_ms, should_continue)
        _assert_continue(should_continue)
        await _emit(on_progress, f"正在第 {attempt}/{max_attempts} 次请求 OTP")
        try:
            return await client.request_otp_once(phone)
        except GatewayCodePendingError as exc:
            last_pending_message = exc.message or last_pending_message
            continue

    raise TimeoutError(f"验证码请求超时：{last_pending_message}")


def _assert_continue(should_continue: Optional[Callable[[], bool]]) -> None:
    if should_continue is not None and not should_continue():
        raise RuntimeError("验证码请求已停止")


async def _sleep_ms(delay_ms: int, should_continue: Optional[Callable[[], bool]]) -> None:
    remaining = delay_ms
    while remaining > 0:
        step = min(1000, remaining)
        await asyncio.sleep(step / 1000)
        remaining -= step
        _assert_continue(should_continue)
