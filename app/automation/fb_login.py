from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from patchright.async_api import Page, TimeoutError as PWTimeoutError

from app.core.config import settings

logger = logging.getLogger(__name__)

FACEBOOK_HOME = "https://www.facebook.com/"
# 需要人工处理的安全验证页特征（URL 片段 + 文案）
MANUAL_URL_MARKERS = ["checkpoint", "confirmemail", "two_step_verification", "login/device-based", "/recover"]
MANUAL_TEXT_MARKERS = [
    "确认你的身份",
    "确认邮箱",
    "输入登录码",
    "双重验证",
    "两步验证",
    "安全验证",
    "我们给你发送了验证码",
    "请输入验证码以继续",
]
# 登录后“保存登录信息/记住设备”弹窗的跳过按钮
SAVE_DEVICE_SKIP_TEXTS = ["现在不要", "以后再说", "暂时不要", "Not now"]

ProgressCb = Callable[[str], Awaitable[None] | None]


class LoginNeedsManual(Exception):
    """登录撞到 2FA/邮箱确认/安全验证，需人工处理。"""


class LoginFailed(Exception):
    pass


async def _emit(cb: Optional[ProgressCb], message: str) -> None:
    if cb is None:
        logger.info(message)
        return
    result = cb(message)
    if asyncio.iscoroutine(result):
        await result


async def is_logged_in(page: Page) -> bool:
    """粗略判断：没有 email/pass 登录框，且不在 login/checkpoint 页。"""
    url = page.url or ""
    if any(m in url for m in ("login", "checkpoint", "confirmemail")):
        return False
    has_email = await page.locator('input[name="email"]').count()
    has_pass = await page.locator('input[name="pass"]').count()
    return not (has_email and has_pass)


async def ensure_logged_in(
    page: Page,
    account: Optional[str] = None,
    password: Optional[str] = None,
    report: Optional[ProgressCb] = None,
) -> str:
    """确保已登录 FB；未登录则用账号密码登录。

    返回状态文案；遇安全验证抛 LoginNeedsManual，凭据缺失/失败抛 LoginFailed。
    """
    account = account if account is not None else settings.fb_account
    password = password if password is not None else settings.fb_password

    await page.goto(FACEBOOK_HOME, wait_until="domcontentloaded")
    await asyncio.sleep(2)
    await _raise_if_manual(page)

    if await is_logged_in(page):
        await _emit(report, "FB 已登录，跳过自动登录")
        return "already_logged_in"

    if not account or not password:
        raise LoginFailed("未登录且未配置 FB_ACCOUNT/FB_PASSWORD")

    await _emit(report, f"正在自动登录 FB：{_mask(account)}")
    email = page.locator('input[name="email"]').first
    pwd = page.locator('input[name="pass"]').first
    await email.wait_for(timeout=settings.fb_default_timeout_ms)
    await email.fill(account)
    await pwd.fill(password)
    await asyncio.sleep(0.5)

    login_btn = page.locator(
        'button[name="login"], [data-testid="royal_login_button"], button[type="submit"]'
    ).first
    if await login_btn.count() > 0:
        await login_btn.click()
    else:
        await pwd.press("Enter")

    # 等待跳转/结果
    for _ in range(20):  # 最多 ~20s
        await asyncio.sleep(1)
        await _dismiss_save_device(page, report)
        await _raise_if_manual(page)
        if await is_logged_in(page):
            await _emit(report, "FB 自动登录成功")
            return "logged_in"

    # 还停在登录页 → 可能账密错误
    if await page.locator('input[name="pass"]').count():
        raise LoginFailed("登录后仍停留在登录页，请检查账号密码")
    raise LoginFailed("登录结果未知，请人工确认")


async def _dismiss_save_device(page: Page, report: Optional[ProgressCb]) -> None:
    for text in SAVE_DEVICE_SKIP_TEXTS:
        btn = page.get_by_role("button", name=text).first
        try:
            if await btn.count() > 0 and await btn.is_visible():
                await _emit(report, f"跳过“保存登录信息”：{text}")
                await btn.click()
                await asyncio.sleep(1)
                return
        except PWTimeoutError:
            continue


async def _raise_if_manual(page: Page) -> None:
    url = page.url or ""
    if any(m in url for m in MANUAL_URL_MARKERS):
        raise LoginNeedsManual(f"需人工处理安全验证：{url}")
    try:
        body = await page.locator("body").inner_text(timeout=4000)
    except PWTimeoutError:
        return
    hit = next((m for m in MANUAL_TEXT_MARKERS if m in body), None)
    if hit:
        raise LoginNeedsManual(f"需人工处理安全验证：{hit}")


def _mask(account: str) -> str:
    if "@" in account:
        name, _, domain = account.partition("@")
        return (name[:2] + "***") + "@" + domain
    return account[:3] + "***"
