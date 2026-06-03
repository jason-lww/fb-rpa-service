from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from patchright.async_api import Page, TimeoutError as PWTimeoutError

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---- 文案常量，移植自 src/extension/domAutomation.ts ----
FEATURE_RATE_LIMIT_ALERT_TITLE = "你暂时无法使用这一功能"
SEND_CODE_PHONE_ERROR_MESSAGE = "发送验证码时出错。请检查你的手机号并重试。"
NON_BUSINESS_ACCOUNT_MESSAGE = "非商业账号"
UNCONFIRMED_BINDING_MESSAGE = "绑定已提交成功，但未确认验证码弹窗关闭或列表中号码，请人工复核。"
BIND_REQUEST_BUTTON_TEXTS = ["绑定", "发送 WhatsApp 验证码", "发送验证码"]
ADD_PHONE_BUTTON_TEXT = "绑定另一电话号码"
CONFIRM_BUTTON_TEXT = "确认"
REMOVE_BUTTON_TEXT = "移除"
NON_BLOCKING_DIALOGS = [
    ("添加 WhatsApp 按钮", "跳过"),
    ("发布包含 WhatsApp 按钮的帖子", "跳过"),
    ("创建 WhatsApp 广告", "取消"),
]

ProgressCb = Callable[[str], Awaitable[None] | None]


class MerchantHomepageAlert(Exception):
    """商户主页风控（限频/发码失败），需暂停人工处理。"""


class NonBusinessAccountError(Exception):
    pass


@dataclass
class BindingConfirmationResult:
    binding_confirmed: bool
    confirmation_message: str


async def _emit(cb: Optional[ProgressCb], message: str) -> None:
    if cb is None:
        logger.info(message)
        return
    result = cb(message)
    if asyncio.iscoroutine(result):
        await result


class FbBindingAutomation:
    """把 domAutomation.ts 的核心 DOM 流程翻译到 patchright Page 上。"""

    def __init__(self, page: Page, report: Optional[ProgressCb] = None):
        self.page = page
        self.report = report
        self._action_delay = settings.action_delay_ms / 1000

    async def _pace(self) -> None:
        await asyncio.sleep(self._action_delay)

    # ---------- 商业主页 ----------
    async def confirm_current_business_page_name(self) -> str:
        existing = await self._find_current_business_page_name()
        if not existing:
            await _emit(self.report, "正在点击右上角头像入口")
            await self._click_account_menu()
        await _emit(self.report, "正在读取当前商业主页名称")
        name = await self._wait_for(self._find_current_business_page_name, timeout_ms=5000)
        if not name:
            raise RuntimeError("无法读取当前商业主页名称")
        await _emit(self.report, f"当前商业主页：{name}")
        return name

    # ---------- 国家码 / 号码 ----------
    async def select_country_code(self, country_code: str = "MX+52") -> None:
        await _emit(self.report, "正在查找国家/地区代码下拉按钮")
        button = self.page.locator(
            f'[role="button"][aria-label*="国家/地区代码"], [role="button"]:has-text("{country_code}")'
        ).first
        try:
            await button.wait_for(timeout=settings.fb_default_timeout_ms)
        except PWTimeoutError:
            return
        label = (await button.get_attribute("aria-label")) or ""
        text = (await button.text_content()) or ""
        if country_code in label or country_code in text:
            await _emit(self.report, f"国家/地区代码已是 {country_code}")
            return
        await _emit(self.report, "正在点击国家/地区代码下拉按钮")
        await button.click()
        await self._pace()
        option = self.page.get_by_text(country_code, exact=False).first
        await option.wait_for(timeout=8000)
        await option.click()
        await self._pace()

    async def open_whatsapp_linking(self) -> None:
        """新版入口：在“已绑定帐户”(linked_profiles) 页点开 WhatsApp，进入绑定表单。

        若已在表单页（tel 输入框或“绑定另一电话号码”已存在）则跳过。
        """
        if await self._tel_input_present() or await self._binding_list_ready():
            return
        if "tab=linked_whatsapp" in self.page.url and await self._tel_input_present():
            return
        await _emit(self.report, "正在打开“已绑定帐户”中的 WhatsApp")
        wa_entry = self.page.get_by_text("WhatsApp", exact=False).first
        try:
            await wa_entry.scroll_into_view_if_needed(timeout=5000)
            await wa_entry.click(timeout=8000)
        except PWTimeoutError:
            raise RuntimeError("未在“已绑定帐户”页找到 WhatsApp 入口")
        await self._pace()
        # 等表单或号码列表就绪
        await self._wait_for(
            lambda: self._tel_input_present_or_list_ready(),
            timeout_ms=settings.fb_default_timeout_ms,
        )

    async def _tel_input_present_or_list_ready(self) -> bool:
        return await self._tel_input_present() or await self._binding_list_ready()

    async def _open_add_phone_form_if_needed(self) -> None:
        await self.dismiss_non_blocking_dialogs()
        if await self._tel_input_present():
            return
        await _emit(self.report, f"正在查找“{ADD_PHONE_BUTTON_TEXT}”按钮")
        add_btn = self.page.get_by_role("button", name=ADD_PHONE_BUTTON_TEXT).first
        await add_btn.click(timeout=settings.fb_default_timeout_ms)
        await self._pace()

    async def bind_phone_on_page(
        self, phone: str, business_page_name: str = "未知商户", country_code: str = "MX+52"
    ) -> None:
        await self.dismiss_non_blocking_dialogs()
        await self.open_whatsapp_linking()
        await self._open_add_phone_form_if_needed()
        await self.select_country_code(country_code)
        await _emit(self.report, "正在输入 WhatsApp 电话号码")
        tel = self.page.locator('input[autocomplete="tel"]').first
        await tel.wait_for(timeout=settings.fb_default_timeout_ms)
        await tel.fill(phone)
        await self._pace()
        await _emit(self.report, "正在等待手机号有效校验")
        await self._wait_phone_valid()
        await _emit(self.report, "正在点击 WhatsApp 验证码发送按钮")
        await self._click_bind_request_button()
        await self._wait_post_bind_outcome()
        await self._raise_if_blocked(business_page_name)

    async def submit_verification_code(self, code: str, phone: str) -> BindingConfirmationResult:
        if not re.fullmatch(r"\d{5,6}", code):
            raise ValueError("验证码必须是 5 位或 6 位数字")
        await _emit(self.report, "正在输入验证码")
        code_input = self.page.locator(
            'input[inputmode="numeric"][maxlength="5"], input[inputmode="numeric"][maxlength="6"]'
        ).first
        await code_input.wait_for(timeout=settings.fb_default_timeout_ms)
        await code_input.fill(code)
        await self._pace()
        await _emit(self.report, "正在点击“确认”按钮")
        await self.page.get_by_role("button", name=CONFIRM_BUTTON_TEXT).first.click()
        return await self._wait_binding_completion(phone)

    async def unbind_phone_on_page(self, phone: str) -> None:
        await self.dismiss_non_blocking_dialogs()
        await self.open_whatsapp_linking()
        tail = re.sub(r"\D", "", phone)[-8:]
        spaced = f"{tail[:4]} {tail[4:]}" if len(tail) == 8 else tail
        await _emit(self.report, f"正在查找待解绑号码：{spaced}")
        row = self.page.locator('[role="row"], tr, div').filter(has_text=spaced).filter(
            has=self.page.get_by_role("button", name=REMOVE_BUTTON_TEXT)
        ).first
        try:
            await row.wait_for(timeout=8000)
        except PWTimeoutError:
            raise RuntimeError("无法找到")
        await row.get_by_role("button", name=REMOVE_BUTTON_TEXT).first.click()
        await self._pace()
        dialog = self.page.locator('[role="dialog"]').filter(has_text="移除 WhatsApp 电话号码").first
        try:
            await dialog.wait_for(timeout=5000)
        except PWTimeoutError:
            dialog = self.page.locator('[role="dialog"]').first
        if await self._dialog_is_ad_occupied(dialog):
            await dialog.get_by_role("button", name="取消").first.click()
            raise RuntimeError("广告占用中")
        await dialog.get_by_role("button", name=REMOVE_BUTTON_TEXT).first.click()
        await _emit(self.report, "正在等待 Facebook 完成移除")
        await self._pace()

    # ---------- 非阻塞弹窗 ----------
    async def dismiss_non_blocking_dialogs(self) -> bool:
        for title, action in NON_BLOCKING_DIALOGS:
            dialog = self.page.locator('[role="dialog"], [aria-modal="true"]').filter(has_text=title).first
            try:
                if await dialog.count() == 0 or not await dialog.is_visible():
                    continue
                action_btn = dialog.get_by_role("button", name=action).first
                if await action_btn.count() == 0:
                    continue
                await _emit(self.report, f"正在点击“{action}”处理非阻塞弹窗：{title}")
                await action_btn.click()
                await self._pace()
                return True
            except PWTimeoutError:
                continue
        return False

    # ---------- 风控/错误检测 ----------
    async def _raise_if_blocked(self, business_page_name: str) -> None:
        body = (await self._body_text()).replace(" ", "")
        if SEND_CODE_PHONE_ERROR_MESSAGE.replace(" ", "") in body:
            raise MerchantHomepageAlert(SEND_CODE_PHONE_ERROR_MESSAGE)
        if "此号码没有关联WhatsApp账户或WhatsAppBusiness业务账户" in body:
            raise NonBusinessAccountError(NON_BUSINESS_ACCOUNT_MESSAGE)
        if re.search(r"重试次数.*上限.*几分钟.*再试", body):
            raise MerchantHomepageAlert(f"商户{business_page_name or '未知商户'}，当前无法绑定新号")
        if FEATURE_RATE_LIMIT_ALERT_TITLE in await self._body_text():
            raise MerchantHomepageAlert(FEATURE_RATE_LIMIT_ALERT_TITLE)

    async def _wait_post_bind_outcome(self) -> None:
        await _emit(self.report, "正在等待 Facebook 返回绑定结果")
        deadline = asyncio.get_event_loop().time() + 5
        while asyncio.get_event_loop().time() < deadline:
            await self.dismiss_non_blocking_dialogs()
            body = await self._body_text()
            if (
                FEATURE_RATE_LIMIT_ALERT_TITLE in body
                or SEND_CODE_PHONE_ERROR_MESSAGE.replace(" ", "") in body.replace(" ", "")
                or await self._verification_input_present()
            ):
                return
            await asyncio.sleep(0.25)

    async def _wait_binding_completion(self, phone: str) -> BindingConfirmationResult:
        await _emit(self.report, "正在等待验证码弹窗关闭并确认绑定列表")
        deadline = asyncio.get_event_loop().time() + 30
        while asyncio.get_event_loop().time() < deadline:
            await self.dismiss_non_blocking_dialogs()
            if FEATURE_RATE_LIMIT_ALERT_TITLE in await self._body_text():
                raise MerchantHomepageAlert(FEATURE_RATE_LIMIT_ALERT_TITLE)
            verification_present = await self._verification_input_present()
            phone_in_list = await self._phone_in_list(phone)
            if not verification_present and phone_in_list:
                await _emit(self.report, "列表已确认绑定成功")
                return BindingConfirmationResult(True, "列表已确认绑定成功")
            if not verification_present and await self._binding_list_ready():
                await _emit(self.report, UNCONFIRMED_BINDING_MESSAGE)
                return BindingConfirmationResult(False, UNCONFIRMED_BINDING_MESSAGE)
            await asyncio.sleep(0.25)
        return BindingConfirmationResult(False, UNCONFIRMED_BINDING_MESSAGE)

    # ---------- 低层工具 ----------
    async def _click_bind_request_button(self) -> None:
        for text in BIND_REQUEST_BUTTON_TEXTS:
            btn = self.page.get_by_role("button", name=text, exact=True).first
            try:
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await self._pace()
                    return
            except PWTimeoutError:
                continue
        # 兜底：包含“发送 + 验证码”关键字的按钮
        btn = self.page.get_by_role("button").filter(has_text="验证码").first
        await btn.click(timeout=settings.fb_default_timeout_ms)
        await self._pace()

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

    async def _wait_phone_valid(self) -> None:
        await self._wait_for(
            lambda: self._body_contains_any(["输入WhatsApp 电话号码有效", "电话号码有效"]),
            timeout_ms=settings.fb_default_timeout_ms,
        )

    async def _tel_input_present(self) -> bool:
        return await self.page.locator('input[autocomplete="tel"]').count() > 0

    async def _verification_input_present(self) -> bool:
        return (
            await self.page.locator(
                'input[inputmode="numeric"][maxlength="5"], input[inputmode="numeric"][maxlength="6"]'
            ).count()
            > 0
        )

    async def _binding_list_ready(self) -> bool:
        has_add = await self.page.get_by_role("button", name=ADD_PHONE_BUTTON_TEXT).count() > 0
        return has_add and not await self._verification_input_present()

    async def _dialog_is_ad_occupied(self, dialog) -> bool:
        try:
            text = (await dialog.text_content()) or ""
        except PWTimeoutError:
            return False
        return any(k in text for k in ["投放中的广告系列将受到影响", "广告系列将暂停", "仍要解除关联"])

    async def _phone_in_list(self, phone: str) -> bool:
        digits = re.sub(r"\D", "", phone)
        body = re.sub(r"\D", "", await self._body_text())
        return bool(digits) and (digits in body or body.endswith(digits))

    async def _body_text(self) -> str:
        try:
            return await self.page.locator("body").inner_text(timeout=settings.fb_default_timeout_ms)
        except PWTimeoutError:
            return ""

    async def _body_contains_any(self, needles: list[str]) -> bool:
        body = await self._body_text()
        return any(n in body for n in needles)

    async def _find_current_business_page_name(self) -> Optional[str]:
        return await self.page.evaluate(
            """() => {
              const scopes = Array.from(document.querySelectorAll('[role="menu"], [role="dialog"]')).filter((el) => {
                const text = el.textContent || "";
                return Boolean(el.querySelector('[aria-current="page"]')) || text.includes("查看所有主页") || text.includes("退出登录");
              });
              const extract = (el) => {
                const spans = Array.from(el.querySelectorAll("span"))
                  .map((s) => (s.textContent || "").trim())
                  .filter((t) => t && t.length > 1 && t !== "查看所有主页");
                return spans.length ? spans[spans.length - 1] : null;
              };
              for (const scope of scopes) {
                const current = scope.querySelector('[aria-current="page"]');
                if (current) {
                  const name = extract(current);
                  if (name) return name;
                }
              }
              for (const scope of scopes) {
                const candidate = Array.from(scope.querySelectorAll('[role="button"], a')).map(extract).find(Boolean);
                if (candidate) return candidate;
              }
              return null;
            }"""
        )

    async def _wait_for(self, predicate: Callable[[], Awaitable], timeout_ms: int = 10000, interval_ms: int = 250):
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            value = await predicate()
            if value:
                return value
            await asyncio.sleep(interval_ms / 1000)
        return None
