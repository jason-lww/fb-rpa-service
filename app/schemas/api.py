from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

WarpaAccountType = Literal["CAT", "TIGER", "FIVE_SEGMENT"]


class BindRequest(BaseModel):
    phone: str = Field(..., description="待绑定 WhatsApp 号，可含国家码", examples=["5216161261519"])
    countryCode: Optional[str] = Field(None, description="国家/地区代码；不传则按号码推断", examples=["MX+52"])
    jid: Optional[str] = Field(None, description="养号系统账号 jid；不传则用 phone", examples=["5216161261519"])
    waType: Optional[WarpaAccountType] = Field(None, description="账号类型")
    callbackUrl: Optional[str] = Field(None, description="绑定结果回传地址")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "phone": "5216161261519",
                    "countryCode": "MX+52",
                    "jid": "5216161261519",
                    "waType": "CAT",
                    "callbackUrl": "https://example.com/rpa/fb-bind-callback",
                }
            ]
        }
    }


class UnbindRequest(BaseModel):
    phone: str = Field(..., description="待解绑 WhatsApp 号，可含国家码", examples=["5216161261519"])
    jid: Optional[str] = Field(None, description="养号系统账号 jid；不传则用 phone", examples=["5216161261519"])
    waType: Optional[WarpaAccountType] = Field(None, description="账号类型")
    callbackUrl: Optional[str] = Field(None, description="解绑结果回传地址")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "phone": "5216161261519",
                    "jid": "5216161261519",
                    "waType": "CAT",
                    "callbackUrl": "https://example.com/rpa/fb-unbind-callback",
                }
            ]
        }
    }


class TaskResp(BaseModel):
    taskId: str = Field(..., description="异步任务 ID")
    status: str = Field(..., description="任务初始状态")


class PageCreateRequest(BaseModel):
    pageName: Optional[str] = Field(None, description="公共主页名称；不传则从名字池随机取一个")
    nameId: Optional[str] = Field(None, description="名字池 ID")
    merchantId: Optional[str] = Field(None, description="商户 ID")
    personalProfileId: Optional[str] = Field(None, description="所属个人主页 ID")
    personalProfileName: Optional[str] = Field(None, description="所属个人主页名称", examples=["María Elicia"])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "pageName": "Cityease Demo",
                    "personalProfileName": "María Elicia",
                }
            ]
        }
    }


class AdminStateSnapshotRequest(BaseModel):
    batchId: Optional[str] = Field(None, description="批次 ID")
    records: list[dict[str, Any]] = Field(default_factory=list, description="绑定/解绑记录快照")
    operationLog: list[dict[str, Any]] = Field(default_factory=list, description="操作日志快照")
    summary: str = Field("", description="摘要")
    currentOperation: str = Field("", description="当前操作")


class MerchantRequest(BaseModel):
    merchantId: str = Field(..., description="商户 ID")
    merchantName: str = Field(..., description="商户主页名称")
    fbPageId: str = Field("", description="FB 公共主页 ID")
    personalProfileId: str = Field("", description="所属个人主页 ID")
    personalProfileName: str = Field("", description="所属个人主页名称")
    boundWaCount: int = Field(0, ge=0, description="已绑定 WA 数量")


class BoundWaCountRequest(BaseModel):
    boundWaCount: int = Field(..., ge=0, description="已绑定 WA 数量")


class PageNamesRequest(BaseModel):
    names: list[str] = Field(..., min_length=1, description="待导入的主页名称列表")

    model_config = {
        "json_schema_extra": {
            "examples": [{"names": ["Cityease Demo A", "Cityease Demo B"]}]
        }
    }


class PersonalProfileRequest(BaseModel):
    profileId: str = Field(..., description="个人主页 ID")
    profileName: str = Field(..., description="个人主页名称")
