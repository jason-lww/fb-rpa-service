from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.automation.browser import CdpBrowserSession
from app.automation.fb_login import LoginFailed, LoginNeedsManual, ensure_logged_in
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LoginTask:
    task_id: str
    status: str = "RUNNING"  # RUNNING / SUCCESS / NEEDS_MANUAL / FAIL
    summary: str = ""
    logs: list[str] = field(default_factory=list)


login_tasks: dict[str, LoginTask] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_login_task_view(task_id: str) -> dict[str, Any]:
    task = login_tasks.get(task_id)
    if not task:
        raise ValueError("任务不存在")
    return {"taskId": task.task_id, "status": task.status, "summary": task.summary, "logs": task.logs[-50:]}


async def run_login(task: LoginTask) -> None:
    def log(message: str) -> None:
        task.summary = message
        task.logs.append(f"{_now()} {message}")
        logger.info("[login %s] %s", task.task_id, message)

    try:
        async with CdpBrowserSession() as session:
            page = session.context.pages[0] if session.context.pages else await session.context.new_page()
            status = await ensure_logged_in(page, report=lambda m: log(m))
        task.status = "SUCCESS"
        log(f"登录完成：{status}")
    except LoginNeedsManual as exc:
        task.status = "NEEDS_MANUAL"
        log(str(exc))
    except LoginFailed as exc:
        task.status = "FAIL"
        log(str(exc))
    except Exception as exc:  # noqa: BLE001
        task.status = "FAIL"
        logger.exception("login failed")
        log(f"登录异常：{exc}")


def start_login() -> LoginTask:
    task = LoginTask(task_id=str(uuid.uuid4()))
    login_tasks[task.task_id] = task
    asyncio.create_task(run_login(task))
    return task
