from __future__ import annotations

import logging
from typing import Optional

from patchright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.config import settings

logger = logging.getLogger(__name__)


class CdpBrowserSession:
    """通过 connect_over_cdp 连到一个已登录 FB 的真实 Chrome，复用其已有会话。

    启动真实 Chrome（务必带已登录 FB 的 user-data-dir）：
        chrome --remote-debugging-port=9222 --user-data-dir=/path/to/profile
    """

    def __init__(self, cdp_endpoint: Optional[str] = None):
        self.cdp_endpoint = cdp_endpoint or settings.cdp_endpoint
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "CdpBrowserSession":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_endpoint)
        if not self._browser.contexts:
            raise RuntimeError("CDP 连接成功但没有已存在的浏览器上下文，请确认 Chrome 已正常打开并登录 FB")
        # 复用已登录会话，绝不 new_context()
        self._context = self._browser.contexts[0]
        return self

    async def __aexit__(self, *exc_info) -> None:
        # 仅断开 CDP 连接，不关闭用户的真实 Chrome
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._pw is not None:
                await self._pw.stop()

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("浏览器会话未初始化")
        return self._context

    async def get_target_page(self, url: str) -> Page:
        """复用已在目标页的标签页；否则复用一个已有标签页跳转；都没有则新开。"""
        context = self.context
        for page in context.pages:
            if _same_target(page.url, url):
                return page
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(settings.fb_default_timeout_ms)
        await page.goto(url, wait_until="domcontentloaded")
        return page


def _same_target(current: Optional[str], target: str) -> bool:
    if not current:
        return False
    return current.split("#")[0].rstrip("/") == target.split("#")[0].rstrip("/")
