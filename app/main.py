from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.clients.incubation import OTP_SERVICE_ENDPOINTS
from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import db_enabled
from app.repositories import admin_state as admin_state_repo
from app.repositories import merchants as merchants_repo
from app.repositories import page_names as page_names_repo
from app.repositories import personal_profiles as profiles_repo
from app.repositories.merchants import FbPageDuplicateError
from app.schemas.api import BindRequest, TaskResp, UnbindRequest
from app.services.bind_orchestrator import (
    get_task_view,
    pause_task,
    start_single_bind,
    start_single_unbind,
)
from app.services.login_service import get_login_task_view, start_login
from app.services.page_creation_service import get_page_task_view, start_page_creation
from app.web.admin_console import ADMIN_CONSOLE_HTML

setup_logger()
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.project_name)


@app.on_event("startup")
async def on_startup() -> None:
    if db_enabled():
        try:
            from app.db.schema import ensure_schema

            ensure_schema()
        except Exception:  # noqa: BLE001
            logger.exception("MySQL schema 初始化失败；留档功能将不可用")
    else:
        logger.warning("未配置 DATABASE_URL，留档功能禁用（仅内存任务态）")

    # 可选：启动时自动登录 FB（不阻塞启动，后台执行）
    if settings.fb_auto_login and settings.fb_account and settings.fb_password:
        logger.info("FB_AUTO_LOGIN 已开启，启动后台自动登录任务")
        start_login()
    elif settings.fb_auto_login:
        logger.warning("FB_AUTO_LOGIN 开启但未配置 FB_ACCOUNT/FB_PASSWORD，跳过自动登录")


def _require_db() -> None:
    if not db_enabled():
        raise HTTPException(status_code=500, detail="服务端未配置 DATABASE_URL")


# ---------------- 健康检查 / 绑定队列 ----------------
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "otpEnvironment": settings.otp_service_environment,
        "otpEndpoint": OTP_SERVICE_ENDPOINTS[settings.otp_service_environment],
        "cdpEndpoint": settings.cdp_endpoint,
        "gatewayKeyConfigured": bool(settings.incubation_gateway_key),
        "databaseConfigured": db_enabled(),
    }


@app.post("/rpa/fb/bind", response_model=TaskResp)
async def bind_number(req: BindRequest) -> TaskResp:
    """养号系统推送单个 WhatsApp 号绑定到本服务对应 FB 主页。"""
    try:
        task = start_single_bind(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TaskResp(taskId=task.task_id, status=task.status)


@app.post("/rpa/fb/unbind", response_model=TaskResp)
async def unbind_number(req: UnbindRequest) -> TaskResp:
    """养号系统推送单个 WhatsApp 号从本服务对应 FB 主页解绑。"""
    try:
        task = start_single_unbind(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TaskResp(taskId=task.task_id, status=task.status)


@app.get("/rpa/fb/tasks/{task_id}")
def task_status(task_id: str) -> dict:
    try:
        return get_task_view(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/rpa/fb/tasks/{task_id}/pause")
def task_pause(task_id: str) -> dict:
    try:
        pause_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


# ---------------- 业务主页创建 ----------------
@app.post("/rpa/fb/business-page/create", response_model=TaskResp)
async def create_business_page_flow(request: Request) -> TaskResp:
    body = await request.json()
    task = start_page_creation(body)
    return TaskResp(taskId=task.task_id, status=task.status)


@app.get("/rpa/fb/business-page/tasks/{task_id}")
def page_task_status(task_id: str) -> dict:
    try:
        return get_page_task_view(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------- FB 登录 ----------------
@app.post("/rpa/fb/login", response_model=TaskResp)
async def fb_login() -> TaskResp:
    task = start_login()
    return TaskResp(taskId=task.task_id, status=task.status)


@app.get("/rpa/fb/login/tasks/{task_id}")
def fb_login_status(task_id: str) -> dict:
    try:
        return get_login_task_view(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------- admin 控台 ----------------
@app.get("/admin-console", response_class=HTMLResponse)
def admin_console() -> str:
    return ADMIN_CONSOLE_HTML


# ---------------- admin-state 留档 ----------------
@app.get("/api/admin-state")
def get_admin_state() -> dict:
    _require_db()
    return admin_state_repo.read_state()


@app.post("/api/admin-state")
async def save_admin_state(request: Request) -> dict:
    _require_db()
    from datetime import datetime, timezone

    body = await request.json()
    admin_state_repo.save_snapshot(body, datetime.now(timezone.utc).isoformat())
    return {"ok": True}


# ---------------- 商户 ----------------
@app.get("/api/merchants")
def list_merchants() -> dict:
    _require_db()
    return {"merchants": merchants_repo.list_merchants()}


@app.post("/api/merchants")
async def create_merchant(request: Request) -> dict:
    _require_db()
    body = await request.json()
    if not body.get("merchantId") or not body.get("merchantName"):
        raise HTTPException(status_code=400, detail="merchantId、merchantName 不能为空")
    try:
        merchants_repo.create_merchant(body)
        page_names_repo.delete_by_page_name(body["merchantName"])
    except FbPageDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True}


@app.patch("/api/merchants/{merchant_id}")
async def update_merchant(merchant_id: str, request: Request) -> dict:
    _require_db()
    body = await request.json()
    body["merchantId"] = merchant_id
    if not body.get("merchantName"):
        raise HTTPException(status_code=400, detail="merchantName 不能为空")
    merchants_repo.update_merchant(body)
    return {"ok": True}


@app.patch("/api/merchants/{merchant_id}/bound-wa-count")
async def patch_bound_wa_count(merchant_id: str, request: Request) -> dict:
    _require_db()
    body = await request.json()
    count = body.get("boundWaCount")
    if not isinstance(count, int) or count < 0:
        raise HTTPException(status_code=400, detail="boundWaCount 必须是非负整数")
    merchants_repo.update_bound_wa_count(merchant_id, count)
    return {"ok": True}


# ---------------- 主页名字池 ----------------
@app.get("/api/page-names")
def list_page_names() -> dict:
    _require_db()
    return {"pageNames": page_names_repo.list_page_names()}


@app.post("/api/page-names")
async def create_page_names(request: Request) -> dict:
    _require_db()
    body = await request.json()
    names = [n.strip() for n in body.get("names", []) if isinstance(n, str) and n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="names 必须至少包含一个名字")
    page_names_repo.create_page_names(sorted(set(names)))
    return {"ok": True}


# ---------------- 个人主页 ----------------
@app.get("/api/personal-profiles")
def list_personal_profiles() -> dict:
    _require_db()
    return {"personalProfiles": profiles_repo.list_personal_profiles()}


@app.post("/api/personal-profiles")
async def create_personal_profile(request: Request) -> dict:
    _require_db()
    body = await request.json()
    profile_id = (body.get("profileId") or "").strip()
    profile_name = (body.get("profileName") or "").strip()
    if not profile_id or not profile_name:
        raise HTTPException(status_code=400, detail="profileId、profileName 均不能为空")
    profiles_repo.create_personal_profile(profile_id, profile_name)
    return {"ok": True}


@app.delete("/api/personal-profiles/{profile_id}")
def delete_personal_profile(profile_id: str) -> dict:
    _require_db()
    if profiles_repo.count_linked_merchants(profile_id) > 0:
        raise HTTPException(status_code=409, detail="个人主页已关联公共主页，不能删除")
    profiles_repo.delete_personal_profile(profile_id)
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=True)
