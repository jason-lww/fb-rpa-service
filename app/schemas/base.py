from typing import Generic, Optional, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class BaseResp(BaseModel, Generic[T]):
    code: int
    message: str
    data: Optional[T] = None

    @classmethod
    def success(cls, data: Optional[T] = None, message: str = "OK") -> "BaseResp[T]":
        return cls(code=200, message=message, data=data)

    @classmethod
    def fail(cls, code: int = 400, message: str = "Error") -> "BaseResp[None]":
        return cls(code=code, message=message)
