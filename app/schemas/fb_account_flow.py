from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FbBindNumberReq(BaseModel):
    phone_pool_file: Optional[str] = None
    company_page_name: Optional[str] = None
    company_page_url: Optional[str] = None
    phone: Optional[str] = None
    dry_run: bool = False

    model_config = ConfigDict(from_attributes=True)


class FbRemoveCompletedReq(BaseModel):
    phone_pool_file: Optional[str] = None
    company_page_name: Optional[str] = None
    company_page_url: Optional[str] = None
    dry_run: bool = False

    model_config = ConfigDict(from_attributes=True)


class FbOtpCodeReq(BaseModel):
    task_id: str
    otp_code: str = Field(min_length=4, max_length=12)


class FbTaskResp(BaseModel):
    task_id: str
    status: str


class FbTaskStatusResp(BaseModel):
    task_id: str
    status: str
    message: str = ""
    phone: Optional[str] = None
    company_page_name: Optional[str] = None
