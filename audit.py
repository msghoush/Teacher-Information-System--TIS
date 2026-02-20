import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

AUDIT_LOG_DIR = Path(os.getenv("AUDIT_LOG_DIR", "logs"))
AUDIT_LOG_NAME = os.getenv("AUDIT_LOG_NAME", "system_audit.log")
AUDIT_LOG_MAX_BYTES = int(os.getenv("AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
AUDIT_LOG_BACKUP_COUNT = int(os.getenv("AUDIT_LOG_BACKUP_COUNT", "7"))


def get_audit_log_path() -> Path:
    return AUDIT_LOG_DIR / AUDIT_LOG_NAME


def get_audit_logger() -> logging.Logger:
    logger = logging.getLogger("tis.audit")
    if logger.handlers:
        return logger

    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        filename=get_audit_log_path(),
        maxBytes=AUDIT_LOG_MAX_BYTES,
        backupCount=AUDIT_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def write_audit_event(event: Dict[str, Any]) -> None:
    payload = dict(event)
    payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    get_audit_logger().info(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    )
