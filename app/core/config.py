from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


OtpServiceEnvironment = Literal["production", "test"]


class Settings(BaseSettings):
    """运行配置，全部来自环境变量 / .env。"""

    project_name: str = "ics-rpa-service"
    port: int = 8790

    # 养号系统网关
    incubation_gateway_key: str = ""
    otp_service_environment: OtpServiceEnvironment = "production"

    # PostgreSQL 留档（Phase2 使用）
    database_url: str = ""

    # 真实 Chrome 调试端点
    cdp_endpoint: str = "http://127.0.0.1:9222"

    # FB 自动登录（高风险：遇 2FA/安全验证会停下转人工）
    fb_account: str = ""
    fb_password: str = ""
    fb_auto_login: bool = False

    # 拟人化节奏
    between_phone_delay_min_seconds: int = 10
    between_phone_delay_max_seconds: int = 120
    action_delay_ms: int = 300

    # FB 目标页：新版入口是“已绑定帐户”(linked_profiles)，点开 WhatsApp 才进入绑定表单
    fb_binding_url: str = "https://www.facebook.com/settings/?tab=linked_profiles"
    fb_default_timeout_ms: int = 15000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
