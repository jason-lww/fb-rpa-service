import asyncio
import logging
import random
from contextlib import suppress
from typing import Optional

from patchright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from app.core.config import settings
from app.utils.otp_store import otp_store
from app.utils.phone_pool_excel import PhonePoolRow, mark_ready_for_delivery, mark_removed


logger = logging.getLogger(__name__)


class FbAccountFlowCrawler:
    def __init__(self, task_id: str, phone_pool_file: str, dry_run: bool = False):
        self.task_id = task_id
        self.phone_pool_file = phone_pool_file
        self.dry_run = dry_run

    async def bind_number(
        self,
        phone_row: PhonePoolRow,
        company_page_name: Optional[str] = None,
        company_page_url: Optional[str] = None,
    ):
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=settings.fb_user_data_dir,
                channel="chrome",
                headless=settings.browser_headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(settings.fb_default_timeout_ms)
            try:
                await self._open_company_page(page, company_page_name, company_page_url)
                await self._open_linked_accounts(page)
                await self._choose_whatsapp(page)
                await self._connect_another_number(page)
                await self._fill_phone(page, phone_row.phone)
                if self.dry_run:
                    logger.info("dry_run enabled, skip submit OTP and Excel update")
                    return
                otp_code = await otp_store.wait_for(self.task_id)
                await self._confirm_otp(page, otp_code)
                await self._assert_phone_visible(page, phone_row.phone)
                mark_ready_for_delivery(self.phone_pool_file, phone_row)
            finally:
                await context.close()

    async def remove_number(
        self,
        phone_row: PhonePoolRow,
        company_page_name: Optional[str] = None,
        company_page_url: Optional[str] = None,
    ):
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=settings.fb_user_data_dir,
                channel="chrome",
                headless=settings.browser_headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(settings.fb_default_timeout_ms)
            try:
                await self._open_company_page(page, company_page_name, company_page_url)
                await self._open_linked_accounts(page)
                await self._remove_phone_from_list(page, phone_row.phone)
                if not self.dry_run:
                    mark_removed(self.phone_pool_file, phone_row)
            finally:
                await context.close()

    async def _open_company_page(self, page: Page, page_name: Optional[str], page_url: Optional[str]):
        await page.goto(page_url or "https://www.facebook.com/", wait_until="domcontentloaded")
        await self._human_delay()
        if page_url:
            return
        if page_name:
            clicked = await self._click_by_text(page, [page_name], timeout=5000)
            if clicked:
                await page.wait_for_load_state("domcontentloaded")
                return
        logger.info("未指定或未自动切换公司主页，请在打开的 Chrome 中确认当前身份为公司主页")

    async def _open_linked_accounts(self, page: Page):
        if "professional_dashboard" not in page.url:
            await self._click_by_text(page, ["Professional dashboard", "专业面板", "专业控制面板"])
        await self._click_by_text(page, ["All tools", "所有工具"])
        await self._click_by_text(page, ["Linked accounts", "关联账户"])

    async def _choose_whatsapp(self, page: Page):
        await self._click_by_text(page, ["WhatsApp", "whatsapp"])

    async def _connect_another_number(self, page: Page):
        await self._click_by_text(page, ["Connect another number", "绑定其他号码", "连接其他号码"])

    async def _fill_phone(self, page: Page, phone: str):
        phone_input = page.locator("input[type='tel'], input[name*='phone'], input[aria-label*='phone']").first
        await phone_input.fill(phone)
        await self._human_delay()
        await self._click_by_text(page, ["Next", "Continue", "下一步", "继续"])
        logger.info("已提交手机号，等待 OTP: task_id=%s phone=%s", self.task_id, phone)

    async def _confirm_otp(self, page: Page, otp_code: str):
        code_input = page.locator("input[inputmode='numeric'], input[name*='code'], input[aria-label*='code']").first
        await code_input.fill(otp_code)
        await self._human_delay()
        await self._click_by_text(page, ["Confirm", "Done", "确认", "完成"])

    async def _assert_phone_visible(self, page: Page, phone: str):
        normalized_tail = "".join(ch for ch in phone if ch.isdigit())[-6:]
        await page.get_by_text(normalized_tail, exact=False).wait_for(timeout=30000)

    async def _remove_phone_from_list(self, page: Page, phone: str):
        normalized_tail = "".join(ch for ch in phone if ch.isdigit())[-6:]
        row = page.get_by_text(normalized_tail, exact=False).locator("xpath=ancestor::*[self::tr or @role='row'][1]")
        with suppress(PlaywrightTimeoutError):
            await row.wait_for(timeout=5000)
        remove_clicked = await self._click_by_text(row, ["Remove", "Disconnect", "移除", "解除关联"], timeout=5000)
        if not remove_clicked:
            await page.get_by_text(normalized_tail, exact=False).click()
            await self._click_by_text(page, ["Remove", "Disconnect", "移除", "解除关联"])
        await self._click_by_text(page, ["Confirm", "Remove", "确认", "移除"])

    async def _click_by_text(self, root, texts: list[str], timeout: int = 15000) -> bool:
        for text in texts:
            locator = root.get_by_text(text, exact=False).first
            try:
                await locator.click(timeout=timeout)
                await self._human_delay()
                return True
            except PlaywrightTimeoutError:
                continue
        return False

    async def _human_delay(self):
        await asyncio.sleep(random.uniform(0.8, 2.0))
