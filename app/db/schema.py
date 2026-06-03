from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import get_engine

logger = logging.getLogger(__name__)

# MySQL 终态 schema（幂等）。等价于老项目 server/migrations 的 12 个 PG 增量迁移的最终状态。
DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS admin_batches (
      batch_id VARCHAR(64) PRIMARY KEY,
      summary TEXT,
      current_operation TEXT,
      started_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_binding_records (
      id VARCHAR(128) NOT NULL,
      batch_id VARCHAR(64) NOT NULL,
      phone VARCHAR(32) NOT NULL,
      payload JSON NOT NULL,
      status VARCHAR(32) GENERATED ALWAYS AS
        (json_unquote(json_extract(payload, '$.status'))) STORED,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (batch_id, id),
      KEY admin_binding_records_batch_id_idx (batch_id),
      KEY admin_binding_records_status_idx (status),
      KEY admin_binding_records_phone_idx (phone),
      CONSTRAINT admin_binding_records_batch_fk FOREIGN KEY (batch_id)
        REFERENCES admin_batches (batch_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_operation_logs (
      id VARCHAR(128) NOT NULL,
      batch_id VARCHAR(64) NOT NULL,
      phone VARCHAR(32) NULL,
      time DATETIME NOT NULL,
      payload JSON NOT NULL,
      PRIMARY KEY (batch_id, id),
      KEY admin_operation_logs_batch_id_idx (batch_id),
      KEY admin_operation_logs_phone_idx (phone),
      KEY admin_operation_logs_time_idx (time),
      CONSTRAINT admin_operation_logs_batch_fk FOREIGN KEY (batch_id)
        REFERENCES admin_batches (batch_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS merchants (
      merchant_id VARCHAR(64) PRIMARY KEY,
      merchant_name VARCHAR(255) NOT NULL UNIQUE,
      fb_page_id VARCHAR(64) NOT NULL DEFAULT '',
      personal_profile_id VARCHAR(64) NOT NULL DEFAULT '',
      personal_profile_name VARCHAR(255) NOT NULL DEFAULT '',
      manual_bound_wa_count INT NOT NULL DEFAULT 0,
      created_page_url VARCHAR(1024) NOT NULL DEFAULT '',
      page_created_at DATETIME NULL,
      page_pool_status VARCHAR(16) NOT NULL DEFAULT 'NAME_POOL',
      latest_status_type VARCHAR(64) NOT NULL DEFAULT '',
      latest_status_message TEXT,
      latest_status_updated_at DATETIME NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      KEY merchants_page_created_at_idx (page_created_at),
      KEY merchants_fb_page_id_idx (fb_page_id),
      KEY merchants_personal_profile_id_idx (personal_profile_id),
      KEY merchants_latest_status_type_idx (latest_status_type),
      KEY merchants_page_pool_status_idx (page_pool_status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS page_names (
      name_id VARCHAR(64) PRIMARY KEY,
      page_name VARCHAR(255) NOT NULL UNIQUE,
      status VARCHAR(16) NOT NULL DEFAULT 'NAME_POOL',
      allocated_at DATETIME NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      KEY page_names_status_idx (status),
      KEY page_names_created_at_idx (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS personal_profiles (
      profile_id VARCHAR(64) PRIMARY KEY,
      profile_name VARCHAR(255) NOT NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      KEY personal_profiles_created_at_idx (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def ensure_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for ddl in DDL_STATEMENTS:
            conn.execute(text(ddl))
    logger.info("MySQL schema 已就绪")
