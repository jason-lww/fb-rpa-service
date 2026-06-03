from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.automation.browser import CdpBrowserSession
from app.automation.fb_binding import (
    FbBindingAutomation,
    MerchantHomepageAlert,
    NonBusinessAccountError,
)
from app.automation.fb_login import LoginNeedsManual, ensure_logged_in
from app.clients.incubation import IncubationClient
from app.core.config import settings
from app.db.session import db_enabled
from app.repositories import admin_state as admin_state_repo
from app.services.otp import OTP_MAX_ATTEMPTS, fetch_verification_code
from app.shared.models import BindingRecord
from app.shared.phone import format_otp_lookup_phone
from app.shared.queue import (
    create_binding_queue,
    fail_current,
    mark_code_received,
    mark_disconnected,
    mark_requested,
    mark_success,
    mark_unbind_ad_occupied,
    mark_unbind_failed,
    mark_unbind_not_found,
    mark_unbinding,
    mark_unbound,
    mark_verifying,
    should_retry,
)
from app.shared.phone import normalize_phone
from app.shared.warpa_queue import (
    get_writeback_status,
    mark_writeback_failure,
    mark_writeback_success,
)

logger = logging.getLogger(__name__)


@dataclass
class TaskState:
    task_id: str
    status: str = "PENDING"  # PENDING / RUNNING / SUCCESS / FAIL / PAUSED
    summary: str = ""
    current_operation: str = ""
    records: list[BindingRecord] = field(default_factory=list)
    operation_log: list[dict[str, Any]] = field(default_factory=list)
    running: bool = False


tasks: dict[str, TaskState] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_payload(record: BindingRecord) -> dict[str, Any]:
    """BindingRecord → camelCase payload，供前端展示与 admin_state 留档复用。"""
    return {
        "id": record.id,
        "batchId": record.batch_id,
        "operation": record.operation,
        "phone": record.phone,
        "countryCode": record.country_code,
        "original": record.original,
        "jid": record.jid,
        "waType": record.wa_type,
        "businessPageName": record.business_page_name,
        "status": record.status,
        "success": record.success,
        "attemptCount": record.attempt_count,
        "firstTaskAt": record.first_task_at,
        "bindRequestedAt": record.bind_requested_at,
        "codeReceivedAt": record.code_received_at,
        "firstSuccessAt": record.first_success_at,
        "boundAt": record.bound_at,
        "verificationCode": record.verification_code,
        "serverFbBindStatus": record.server_fb_bind_status,
        "serverWritebackAt": record.server_writeback_at,
        "serverWritebackError": record.server_writeback_error,
        "alertType": record.alert_type,
        "merchantAlertMessage": record.merchant_alert_message,
        "errorType": record.error_type,
        "errorMessage": record.error_message,
        "errorOccurredAt": record.error_occurred_at,
        "lastError": record.last_error,
        "pageUrl": record.page_url,
    }


def _record_view(record: BindingRecord) -> dict[str, Any]:
    return {
        "phone": record.phone,
        "countryCode": record.country_code,
        "jid": record.jid,
        "businessPageName": record.business_page_name,
        "status": record.status,
        "attemptCount": record.attempt_count,
        "verificationCode": record.verification_code,
        "serverFbBindStatus": record.server_fb_bind_status,
        "serverWritebackAt": record.server_writeback_at,
        "lastError": record.last_error,
    }


def get_task_view(task_id: str) -> dict[str, Any]:
    task = tasks.get(task_id)
    if not task:
        raise ValueError("任务不存在")
    return {
        "taskId": task.task_id,
        "status": task.status,
        "summary": task.summary,
        "currentOperation": task.current_operation,
        "running": task.running,
        "records": [_record_view(r) for r in task.records],
        "logs": [f"{e['time']} {e['message']}" for e in task.operation_log[-100:]],
    }


class BindOrchestrator:
    """移植自 background.ts 的核心：拉号 → 绑定 → 取码 → 确认 → 回写。"""

    def __init__(self, task: TaskState, client: Optional[IncubationClient] = None):
        self.task = task
        self.client = client or IncubationClient()

    async def _log(self, message: str, phone: Optional[str] = None) -> None:
        now = _now()
        self.task.current_operation = message
        self.task.summary = message
        self.task.operation_log.append(
            {
                "id": f"{self.task.task_id}-log-{len(self.task.operation_log)}",
                "time": now,
                "level": "info",
                "message": message,
                "phone": phone,
            }
        )
        logger.info("[%s] %s", self.task.task_id, message)

    async def _persist_snapshot(self) -> None:
        if not db_enabled():
            return
        snapshot = {
            "batchId": self.task.task_id,
            "summary": self.task.summary,
            "currentOperation": self.task.current_operation,
            "records": [_record_payload(r) for r in self.task.records],
            "operationLog": list(self.task.operation_log),
        }
        try:
            await asyncio.to_thread(admin_state_repo.save_snapshot, snapshot, _now())
        except Exception:  # noqa: BLE001
            logger.exception("admin-state 留档失败（不阻断绑定流程）")

    async def _process_record(self, record: BindingRecord, automation: FbBindingAutomation) -> BindingRecord:
        current = record
        while should_retry(current):
            otp_phone = format_otp_lookup_phone(current)

            await self._log("正在检查验证码设备连接状态")
            try:
                connection = await self.client.check_connection(otp_phone)
            except Exception as exc:  # noqa: BLE001
                return mark_disconnected(current, f"断联：{exc}")
            if not connection.connected:
                return mark_disconnected(current, f"断联：设备状态 {connection.status}")

            current = mark_requested(current, _now(), settings.fb_binding_url)
            await self._log(f"正在绑定 {current.phone} 到 {current.business_page_name}，第 {current.attempt_count} 次")

            try:
                await automation.bind_phone_on_page(
                    current.phone, current.business_page_name, current.country_code
                )
            except MerchantHomepageAlert as exc:
                self.task.running = False
                return replace(
                    fail_current(current, str(exc)),
                    error_type="merchant_homepage",
                    alert_type="merchant_homepage",
                    merchant_alert_message=str(exc),
                )
            except NonBusinessAccountError as exc:
                return replace(fail_current(current, str(exc)), error_type="non_business_account")
            except Exception as exc:  # noqa: BLE001
                current = fail_current(current, str(exc))
                if not should_retry(current):
                    return current
                continue

            try:
                code_result = await fetch_verification_code(
                    self.client,
                    otp_phone,
                    should_continue=lambda: self.task.running,
                    on_progress=self._log,
                )
            except Exception as exc:  # noqa: BLE001
                if not self.task.running:
                    return current
                failure = fail_current(
                    current, f"{OTP_MAX_ATTEMPTS}/{OTP_MAX_ATTEMPTS} 次请求 OTP 仍未获取验证码，当前号码失败"
                )
                await self._log(failure.last_error)
                return failure

            current = mark_code_received(current, code_result, _now())
            current = mark_verifying(current)
            try:
                result = await automation.submit_verification_code(code_result.verification_code, current.phone)
            except MerchantHomepageAlert as exc:
                self.task.running = False
                return replace(
                    fail_current(current, str(exc)),
                    error_type="merchant_homepage",
                    alert_type="merchant_homepage",
                    merchant_alert_message=str(exc),
                )
            except Exception as exc:  # noqa: BLE001
                current = fail_current(current, str(exc))
                if not should_retry(current):
                    return current
                continue

            if result.binding_confirmed:
                return mark_success(current, _now())

            self.task.running = False
            return fail_current(current, result.confirmation_message)

        return fail_current(current, current.last_error or "重试 2 次仍未成功")

    async def _writeback(self, record: BindingRecord) -> BindingRecord:
        writeback_jid = (record.jid or "").strip() or format_otp_lookup_phone(record)
        status = get_writeback_status(record)
        if not writeback_jid or not status:
            return record
        try:
            await self.client.fb_bind_status(
                jid=writeback_jid,
                status=status,
                wa_type=record.wa_type,
                fb_page_name=record.business_page_name,
            )
            written = mark_writeback_success(record, status)
            await self._log(f"已回写服务端 FB 绑定状态：{status}")
            return written
        except Exception as exc:  # noqa: BLE001
            await self._log(f"服务端 FB 绑定状态回写失败：{exc}")
            return mark_writeback_failure(record, str(exc))

    # ---------- 单号推送模式（养号系统按服务地址推送）----------
    async def run_single_bind(self, record: BindingRecord, callback_url: Optional[str]) -> None:
        self.task.running = True
        self.task.status = "RUNNING"
        try:
            async with CdpBrowserSession() as session:
                if settings.fb_account and settings.fb_password:
                    login_page = session.context.pages[0] if session.context.pages else await session.context.new_page()
                    try:
                        await ensure_logged_in(login_page, report=self._log)
                    except LoginNeedsManual as exc:
                        self.task.running = False
                        self.task.status = "PAUSED"
                        await self._log(f"登录需人工处理，已暂停：{exc}")
                        await self._callback(callback_url, record, "BIND_RETRY", str(exc))
                        return
                page = await session.get_target_page(settings.fb_binding_url)
                automation = FbBindingAutomation(page, report=self._log)
                business_page_name = await automation.confirm_current_business_page_name()
                record = replace(record, business_page_name=business_page_name)
                self.task.records = [record]
                updated = await self._process_record(record, automation)
                updated = await self._writeback(updated)
                self.task.records = [updated]
                await self._persist_snapshot()
            self.task.running = False
            self.task.status = "SUCCESS" if updated.status == "success" else "FAIL"
            status = "BIND_SUCCESS" if updated.status == "success" else (
                get_writeback_status(updated) or "BIND_FAILED"
            )
            await self._callback(callback_url, updated, status, updated.last_error)
            await self._log(f"绑定结束：{updated.status}")
        except Exception as exc:  # noqa: BLE001
            self.task.running = False
            self.task.status = "FAIL"
            logger.exception("single bind failed")
            await self._log(f"绑定失败：{exc}")
            await self._callback(callback_url, record, "BIND_RETRY", str(exc))

    async def run_single_unbind(self, record: BindingRecord, callback_url: Optional[str]) -> None:
        self.task.running = True
        self.task.status = "RUNNING"
        try:
            async with CdpBrowserSession() as session:
                if settings.fb_account and settings.fb_password:
                    login_page = session.context.pages[0] if session.context.pages else await session.context.new_page()
                    try:
                        await ensure_logged_in(login_page, report=self._log)
                    except LoginNeedsManual as exc:
                        self.task.running = False
                        self.task.status = "PAUSED"
                        await self._log(f"登录需人工处理，已暂停：{exc}")
                        await self._unbind_callback(callback_url, record, "UNBIND_FAILED", str(exc))
                        return
                page = await session.get_target_page(settings.fb_binding_url)
                automation = FbBindingAutomation(page, report=self._log)
                record = mark_unbinding(record, _now(), settings.fb_binding_url)
                self.task.records = [record]
                try:
                    await automation.unbind_phone_on_page(record.phone)
                    record = mark_unbound(record, _now())
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc)
                    if "无法找到" in msg:
                        record = mark_unbind_not_found(record, "无法找到")
                    elif "广告占用中" in msg:
                        record = mark_unbind_ad_occupied(record, msg)
                    else:
                        record = mark_unbind_failed(record, msg)
                self.task.records = [record]
                await self._persist_snapshot()
            self.task.running = False
            self.task.status = "SUCCESS" if record.status == "unbound" else "FAIL"
            status = "UNBIND_SUCCESS" if record.status == "unbound" else "UNBIND_FAILED"
            await self._unbind_callback(callback_url, record, status, record.last_error)
            await self._log(f"解绑结束：{record.status}")
        except Exception as exc:  # noqa: BLE001
            self.task.running = False
            self.task.status = "FAIL"
            logger.exception("single unbind failed")
            await self._log(f"解绑失败：{exc}")
            await self._unbind_callback(callback_url, record, "UNBIND_FAILED", str(exc))

    async def _callback(
        self, callback_url: Optional[str], record: BindingRecord, status: str, error: str = ""
    ) -> None:
        if not callback_url:
            return
        payload = {
            "jid": record.jid or record.phone,
            "phone": record.phone,
            "status": status,
            "fbPageName": record.business_page_name,
            "success": status == "BIND_SUCCESS",
            "error": error or "",
        }
        await self._post_callback(callback_url, payload)

    async def _unbind_callback(
        self, callback_url: Optional[str], record: BindingRecord, status: str, error: str = ""
    ) -> None:
        if not callback_url:
            return
        payload = {
            "jid": record.jid or record.phone,
            "phone": record.phone,
            "status": status,
            "success": status == "UNBIND_SUCCESS",
            "error": error or "",
        }
        await self._post_callback(callback_url, payload)

    async def _post_callback(self, callback_url: str, payload: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(callback_url, json=payload)
            await self._log(f"已回传结果到 {callback_url}")
        except Exception as exc:  # noqa: BLE001
            await self._log(f"结果回传失败：{exc}")

def _build_single_record(req: dict[str, Any]) -> BindingRecord:
    phone = (req.get("phone") or "").strip()
    if not phone:
        raise ValueError("phone 不能为空")
    normalized = normalize_phone(phone)
    if not normalized:
        raise ValueError(f"无法解析号码：{phone}")
    if req.get("countryCode"):
        normalized = replace(normalized, country_code=req["countryCode"])
    record = create_binding_queue([normalized])[0]
    return replace(
        record,
        jid=(req.get("jid") or phone),
        wa_type=req.get("waType"),
        server_fb_bind_status="WAITING_BIND",
    )


def start_single_bind(req: dict[str, Any]) -> TaskState:
    record = _build_single_record(req)
    task = TaskState(task_id=str(uuid.uuid4()))
    task.records = [record]
    tasks[task.task_id] = task
    orchestrator = BindOrchestrator(task)
    asyncio.create_task(orchestrator.run_single_bind(record, req.get("callbackUrl")))
    return task


def start_single_unbind(req: dict[str, Any]) -> TaskState:
    record = _build_single_record(req)
    record = replace(record, operation="unbind", status="unbind_pending")
    task = TaskState(task_id=str(uuid.uuid4()))
    task.records = [record]
    tasks[task.task_id] = task
    orchestrator = BindOrchestrator(task)
    asyncio.create_task(orchestrator.run_single_unbind(record, req.get("callbackUrl")))
    return task


def pause_task(task_id: str) -> None:
    task = tasks.get(task_id)
    if not task:
        raise ValueError("任务不存在")
    task.running = False
    task.status = "PAUSED"
    task.current_operation = "已请求暂停队列。"
