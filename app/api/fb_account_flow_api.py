from fastapi import APIRouter

from app.schemas.base import BaseResp
from app.schemas.fb_account_flow import (
    FbBindNumberReq,
    FbOtpCodeReq,
    FbRemoveCompletedReq,
    FbTaskResp,
    FbTaskStatusResp,
)
from app.services.fb_account_flow_service import (
    get_task_status,
    start_bind_number,
    start_remove_completed,
    submit_otp_code,
)


router = APIRouter()


@router.post("/rpa/fb/account-flow/bind-number", response_model=BaseResp[FbTaskResp])
async def bind_number(req: FbBindNumberReq):
    task = start_bind_number(req)
    return BaseResp.success(FbTaskResp(task_id=task.task_id, status=task.status))


@router.post("/rpa/fb/account-flow/remove-completed", response_model=BaseResp[FbTaskResp])
async def remove_completed(req: FbRemoveCompletedReq):
    task = start_remove_completed(req)
    return BaseResp.success(FbTaskResp(task_id=task.task_id, status=task.status))


@router.post("/rpa/fb/account-flow/submit-otp", response_model=BaseResp[None])
def submit_otp(req: FbOtpCodeReq):
    submit_otp_code(req.task_id, req.otp_code)
    return BaseResp.success()


@router.get("/rpa/fb/account-flow/tasks/{task_id}", response_model=BaseResp[FbTaskStatusResp])
def task_status(task_id: str):
    return BaseResp.success(get_task_status(task_id))
