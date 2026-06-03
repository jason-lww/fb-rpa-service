from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional
from urllib.parse import parse_qs, urlparse

from patchright.async_api import Page, TimeoutError as PWTimeoutError

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_PERSONAL_PROFILE_NAME = "María Elicia"
WOMENS_STORE_CATEGORY = "女装店"
SETUP_BUTTON_SEQUENCE = ["继续", "继续", "跳过", "继续", "完成"]
DUPLICATE_NAME_MARKERS = [
    "已经管理了名为",
    "已创建了名为",
    "已经创建了名为",
    "请尝试其他名称",
    "请选择另一个名称",
    "名称已被使用",
    "already manage",
    "already created",
    "try another name",
]

ProgressCb = Callable[[str], Awaitable[None] | None]


def extract_facebook_page_id_from_url(page_url: str) -> str:
    try:
        parsed = urlparse(page_url)
        if not parsed.path.endswith("/profile.php"):
            return ""
        ids = parse_qs(parsed.query).get("id", [])
        candidate = ids[0].strip() if ids else ""
        return candidate if candidate.isdigit() else ""
    except Exception:  # noqa: BLE001
        return ""


async def _emit(cb: Optional[ProgressCb], message: str) -> None:
    if cb is None:
        logger.info(message)
        return
    result = cb(message)
    if asyncio.iscoroutine(result):
        await result


class FbPageCreationAutomation:
    """移植自 pageCreationAutomation.ts 的核心流程（务实版，需在真实 FB 上调试选择器）。"""

    FACEBOOK_HOME = "https://www.facebook.com/"
    PAGES_LIST = "https://www.facebook.com/pages/?category=your_pages&ref=bookmarks"

    def __init__(self, page: Page, report: Optional[ProgressCb] = None):
        self.page = page
        self.report = report
        self._delay = settings.action_delay_ms / 1000

    async def _pace(self) -> None:
        await asyncio.sleep(self._delay)

    async def select_owning_personal_profile(self, personal_profile_name: str = DEFAULT_PERSONAL_PROFILE_NAME) -> str:
        await _emit(self.report, "正在点击右上角头像入口")
        await self._click_account_menu()
        name = (personal_profile_name or DEFAULT_PERSONAL_PROFILE_NAME).strip()
        await _emit(self.report, f"正在切换到个人主页：{name}")
        option = self.page.get_by_text(name, exact=False).first
        await option.wait_for(timeout=5000)
        await option.click()
        await self._pace()
        await _emit(self.report, f"已进入个人主页：{name}")
        return name

    async def create_business_page_from_list(self, page_name: str) -> dict:
        page_name = page_name.strip()
        if not page_name:
            raise ValueError("公共主页名称为空")

        await self._dismiss_leave_page_dialog()
        await _emit(self.report, "正在点击“创建公共主页”")
        await self._click_create_entry()
        await self._dismiss_leave_page_dialog()

        await _emit(self.report, "正在选择“公共主页”类型")
        await self._click_text_in_dialog("公共主页")
        await self._click_button("继续")
        await self._click_button("开始")

        created_name = await self._fill_required_fields(page_name)
        await self._wait_ready_to_create(created_name)
        await self._click_button("创建公共主页")
        wizard_url = await self._finish_setup_wizard()

        page_url = wizard_url or await self._wait_created_page_url()
        fb_page_id = extract_facebook_page_id_from_url(page_url or "")
        await _emit(self.report, f"创建完成：{page_url}")
        return {"pageName": created_name, "pageUrl": page_url or "", "fbPageId": fb_page_id}

    # ---------- 步骤实现 ----------
    async def _click_account_menu(self) -> None:
        for selector in (
            '[role="button"][aria-label*="个人主页"]',
            '[role="button"][aria-label*="帐户"]',
            '[role="button"][aria-label*="账户"]',
        ):
            loc = self.page.locator(selector).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click()
                    await self._pace()
                    return
            except PWTimeoutError:
                continue

    async def _click_create_entry(self) -> None:
        entry = self.page.get_by_role("button", name="创建公共主页").first
        if await entry.count() == 0:
            show_all = self.page.get_by_role("button", name="显示全部主页").first
            if await show_all.count() > 0:
                await _emit(self.report, "未找到“创建公共主页”，正在点击“显示全部主页”")
                await show_all.click()
                await self._pace()
            entry = self.page.get_by_text("创建公共主页", exact=False).first
        await entry.click(timeout=8000)
        await self._pace()

    async def _fill_required_fields(self, page_name: str) -> str:
        await _emit(self.report, f"正在填写公共主页名称：{page_name}")
        name_input = self.page.locator("input, textarea").filter(
            has=self.page.locator("xpath=.")
        )
        # 优先用占位/aria 文案定位名称输入框
        name_loc = self.page.get_by_label("公共主页名称").or_(
            self.page.get_by_placeholder("公共主页名称")
        ).first
        try:
            await name_loc.wait_for(timeout=settings.fb_default_timeout_ms)
        except PWTimeoutError:
            name_loc = self.page.locator("input[type='text']").first
            await name_loc.wait_for(timeout=settings.fb_default_timeout_ms)
        await name_loc.fill(page_name)
        await self._pace()
        resolved = await self._resolve_duplicate_name(name_loc, page_name)

        await _emit(self.report, f"正在输入公共主页类别：{WOMENS_STORE_CATEGORY}")
        await self._select_category(WOMENS_STORE_CATEGORY)
        return resolved

    async def _resolve_duplicate_name(self, name_loc, base_name: str) -> str:
        if not await self._has_duplicate_name_error(base_name):
            return base_name
        for attempt in range(2, 7):
            next_name = f"{base_name} {attempt}"
            await _emit(self.report, f"公共主页名称重复，正在改用：{next_name}")
            await name_loc.fill(next_name)
            await self._pace()
            if not await self._has_duplicate_name_error(next_name):
                return next_name
        raise RuntimeError("公共主页名称重复，自动换名后仍不可用")

    async def _has_duplicate_name_error(self, page_name: str) -> bool:
        body = await self._body_text()
        if page_name not in body:
            return False
        return any(marker in body for marker in DUPLICATE_NAME_MARKERS)

    async def _select_category(self, category: str) -> None:
        cat_loc = self.page.get_by_label("类别").or_(self.page.get_by_placeholder("类别")).first
        try:
            await cat_loc.wait_for(timeout=settings.fb_default_timeout_ms)
        except PWTimeoutError:
            return
        await cat_loc.click()
        await cat_loc.fill("")
        await cat_loc.press_sequentially(category, delay=120)
        await self._pace()
        option = self.page.get_by_text(category, exact=True).first
        try:
            await option.wait_for(timeout=3000)
            await option.click()
        except PWTimeoutError:
            await cat_loc.press("ArrowDown")
            await cat_loc.press("Enter")
        await self._pace()

    async def _wait_ready_to_create(self, page_name: str) -> None:
        await _emit(self.report, "正在确认名称和类别都已通过校验")
        deadline = asyncio.get_event_loop().time() + 8
        while asyncio.get_event_loop().time() < deadline:
            if not await self._has_duplicate_name_error(page_name):
                btn = self.page.get_by_role("button", name="创建公共主页").first
                if await btn.count() > 0 and await btn.is_enabled():
                    return
            await asyncio.sleep(0.25)

    async def _finish_setup_wizard(self) -> Optional[str]:
        await _emit(self.report, "正在跳过公共主页补充设置")
        for label in SETUP_BUTTON_SEQUENCE:
            url = self._current_created_page_url()
            if url:
                return url
            btn = self.page.get_by_role("button", name=label).first
            try:
                if await btn.count() > 0:
                    await btn.click(timeout=8000)
                    await self._pace()
            except PWTimeoutError:
                fallback = self._current_created_page_url()
                if fallback:
                    return fallback
        return self._current_created_page_url()

    def _current_created_page_url(self) -> Optional[str]:
        href = self.page.url
        return href if extract_facebook_page_id_from_url(href) else None

    async def _wait_created_page_url(self) -> str:
        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            url = self._current_created_page_url()
            if url:
                return url
            await asyncio.sleep(0.5)
        raise RuntimeError("已创建但未在超时时间内确认最终公共主页 URL")

    async def _click_button(self, text: str) -> None:
        await _emit(self.report, f"正在点击“{text}”")
        await self.page.get_by_role("button", name=text).first.click(timeout=settings.fb_default_timeout_ms)
        await self._pace()

    async def _click_text_in_dialog(self, text: str) -> None:
        dialog = self.page.locator('[role="dialog"]').filter(has_text=text).first
        target = dialog.get_by_text(text, exact=True).first
        await target.click(timeout=8000)
        await self._pace()

    async def _dismiss_leave_page_dialog(self) -> None:
        dialog = self.page.locator('[role="dialog"]').filter(has_text="留在页面").first
        try:
            if await dialog.count() > 0 and await dialog.is_visible():
                await _emit(self.report, "检测到离开页面确认，正在点击“留在页面”")
                await dialog.get_by_text("留在页面", exact=False).first.click()
                await self._pace()
        except PWTimeoutError:
            return

    async def _body_text(self) -> str:
        try:
            return await self.page.locator("body").inner_text(timeout=settings.fb_default_timeout_ms)
        except PWTimeoutError:
            return ""
