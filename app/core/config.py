import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    project_name: str = "ICS RPA Service"
    debug: bool = False
    log_dir: str = "log/"

    kafka_bootstrap_servers: str = "localhost:9092"
    group_id: str = "ics_rpa_group"
    fb_account_flow_queue: str = "fb_account_flow_queue"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_enabled: bool = False

    browser_headless: bool = False
    fb_user_data_dir: str = ".browser/fb-profile"
    fb_default_timeout_ms: int = 15000

    phone_pool_file: str = ""

    model_config = ConfigDict(from_attributes=True)


env = os.getenv("APP_ENV", "local")
BASE_DIR = Path(__file__).resolve().parents[1]
config_path = BASE_DIR / "config" / f"config_{env}.yml"

raw_config = {}
if config_path.exists():
    with config_path.open("r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f) or {}

settings = Settings(**raw_config)
