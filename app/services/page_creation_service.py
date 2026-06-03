from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.automation.browser import CdpBrowserSession
from app.automation.fb_page_creation import (
    DEFAULT_PERSONAL_PROFILE_NAME,
    FbPageCreationAutomation,
)
from app.db.session import db_enabled
from app.repositories import merchants as merchants_repo
from app.repositories import page_names as page_names_repo

logger = logging.getLogger(__name__)


@dataclass
class PageCreationTask:
    task_id: str
    status: str = "RUNNING"  # RUNNING / SUCCESS / FAIL
    summary: str = ""
    page_url: str = ""
    fb_page_id: str = ""
    page_name: str = ""
    logs: list[str] = field(default_factory=list)


page_tasks: dict[str, PageCreationTask] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_page_task_view(task_id: str) -> dict[str, Any]:
    task = page_tasks.get(task_id)
    if not task:
        raise ValueError("任务不存在")
    return {
        "taskId": task.task_id,
        "status": task.status,
        "summary": task.summary,
        "pageUrl": task.page_url,
        "fbPageId": task.fb_page_id,
        "pageName": task.page_name,
        "logs": task.logs[-100:],
    }


async def _run(task: PageCreationTask, req: dict[str, Any]) -> None:
    page_name: Optional[str] = (req.get("pageName") or "").strip() or None
    name_id: Optional[str] = (req.get("nameId") or "").strip() or None
    merchant_id: Optional[str] = (req.get("merchantId") or "").strip() or None
    from_pool = False

    def log(message: str) -> None:
        task.summary = message
        task.logs.append(f"{_now()} {message}")
        logger.info("[page-create %s] %s", task.task_id, message)

    try:
        # 名称：优先请求指定；否则从 MySQL 名字池随机取一个（置为 ALLOCATED）
        if not page_name:
            if not db_enabled():
                raise RuntimeError("未指定 pageName 且未配置 DATABASE_URL，无法从名字池取名")
            picked = await asyncio.to_thread(page_names_repo.get_next_page_name)
            if not picked:
                raise RuntimeError("名字池中暂无未创建的名字")
            page_name = picked["pageName"]
            name_id = picked["nameId"]
            merchant_id = picked["merchantId"]
            from_pool = True

        task.page_name = page_name
        personal_profile_name = (req.get("personalProfileName") or "").strip() or DEFAULT_PERSONAL_PROFILE_NAME
        personal_profile_id = (req.get("personalProfileId") or "").strip()

        log(f"开始创建公共主页：{page_name}")
        async with CdpBrowserSession() as session:
            page = await session.get_target_page(FbPageCreationAutomation.FACEBOOK_HOME)
            automation = FbPageCreationAutomation(page, report=lambda m: log(m))
            await automation.select_owning_personal_profile(personal_profile_name)
            await page.goto(FbPageCreationAutomation.PAGES_LIST, wait_until="domcontentloaded")
            created = await automation.create_business_page_from_list(page_name)

        created_page = {
            "nameId": name_id or "",
            "merchantId": merchant_id or "",
            "pageName": created["pageName"],
            "pageUrl": created["pageUrl"],
            "fbPageId": created["fbPageId"],
            "personalProfileId": personal_profile_id,
            "personalProfileName": personal_profile_name,
            "createdAt": _now(),
        }
        if db_enabled():
            await asyncio.to_thread(merchants_repo.create_merchant_from_created_page, created_page)
            if from_pool:
                await asyncio.to_thread(
                    page_names_repo.consume_page_name,
                    {"nameId": name_id, "merchantId": merchant_id, "pageName": created["pageName"]},
                )

        task.page_url = created["pageUrl"]
        task.fb_page_id = created["fbPageId"]
        task.status = "SUCCESS"
        log(f"创建完成：{created['pageUrl']}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("page creation failed")
        task.status = "FAIL"
        log(f"创建失败：{exc}")
        if from_pool and db_enabled() and name_id:
            try:
                await asyncio.to_thread(
                    page_names_repo.release_page_name,
                    {"nameId": name_id, "merchantId": merchant_id, "pageName": page_name},
                )
            except Exception:  # noqa: BLE001
                logger.exception("释放名字池名称失败")


def start_page_creation(req: dict[str, Any]) -> PageCreationTask:
    task = PageCreationTask(task_id=str(uuid.uuid4()))
    page_tasks[task.task_id] = task
    asyncio.create_task(_run(task, req))
    return task
