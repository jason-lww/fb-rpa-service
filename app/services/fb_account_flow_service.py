import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.crawler.fb.account_flow import FbAccountFlowCrawler
from app.schemas.fb_account_flow import FbBindNumberReq, FbRemoveCompletedReq, FbTaskStatusResp
from app.utils.otp_store import otp_store
from app.utils.phone_pool_excel import list_delivery_completed, pick_next_bindable_phone


logger = logging.getLogger(__name__)


@dataclass
class FbTaskState:
    task_id: str
    status: str
    message: str = ""
    phone: Optional[str] = None
    company_page_name: Optional[str] = None


tasks: dict[str, FbTaskState] = {}


def start_bind_number(req: FbBindNumberReq) -> FbTaskState:
    phone_pool_file = _resolve_phone_pool_file(req.phone_pool_file)
    phone_row = pick_next_bindable_phone(phone_pool_file, req.phone)
    task = _create_task("WAIT", phone_row.phone, req.company_page_name)
    asyncio.create_task(_run_bind(task, phone_pool_file, phone_row, req))
    return task


def start_remove_completed(req: FbRemoveCompletedReq) -> FbTaskState:
    phone_pool_file = _resolve_phone_pool_file(req.phone_pool_file)
    rows = list_delivery_completed(phone_pool_file)
    if not rows:
        raise ValueError("号码池中没有状态为“投放完成”的号码")
    task = _create_task("WAIT", rows[0].phone, req.company_page_name)
    asyncio.create_task(_run_remove_completed(task, phone_pool_file, rows, req))
    return task


def submit_otp_code(task_id: str, otp_code: str):
    if task_id not in tasks:
        raise ValueError("任务不存在")
    otp_store.set(task_id, otp_code)
    tasks[task_id].message = "OTP 已提交，等待 FB 确认结果"


def get_task_status(task_id: str) -> FbTaskStatusResp:
    task = tasks.get(task_id)
    if not task:
        raise ValueError("任务不存在")
    return FbTaskStatusResp(**task.__dict__)


async def _run_bind(task: FbTaskState, phone_pool_file: str, phone_row, req: FbBindNumberReq):
    task.status = "RUNNING"
    task.message = "正在绑定 WhatsApp 号码"
    try:
        crawler = FbAccountFlowCrawler(task.task_id, phone_pool_file, req.dry_run)
        await crawler.bind_number(phone_row, req.company_page_name, req.company_page_url)
        task.status = "SUCCESS"
        task.message = "号码绑定完成，号码池已更新为待投放"
    except Exception as exc:
        logger.exception("FB bind number failed: task_id=%s", task.task_id)
        task.status = "FAIL"
        task.message = str(exc)


async def _run_remove_completed(task: FbTaskState, phone_pool_file: str, rows, req: FbRemoveCompletedReq):
    task.status = "RUNNING"
    task.message = f"正在移除 {len(rows)} 个投放完成号码"
    try:
        crawler = FbAccountFlowCrawler(task.task_id, phone_pool_file, req.dry_run)
        for row in rows:
            task.phone = row.phone
            await crawler.remove_number(row, req.company_page_name, req.company_page_url)
        task.status = "SUCCESS"
        task.message = "投放完成号码已移除"
    except Exception as exc:
        logger.exception("FB remove completed failed: task_id=%s", task.task_id)
        task.status = "FAIL"
        task.message = str(exc)


def _create_task(status: str, phone: Optional[str], company_page_name: Optional[str]) -> FbTaskState:
    task_id = str(uuid.uuid4())
    task = FbTaskState(
        task_id=task_id,
        status=status,
        phone=phone,
        company_page_name=company_page_name,
    )
    tasks[task_id] = task
    return task


def _resolve_phone_pool_file(file_path: Optional[str]) -> str:
    resolved = file_path or settings.phone_pool_file
    if not resolved:
        raise ValueError("请在请求或配置中提供 phone_pool_file")
    return resolved
