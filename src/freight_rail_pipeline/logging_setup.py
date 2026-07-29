from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            log_entry["extra"] = record.extra
        return json.dumps(log_entry)


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    json_format: bool = False,
    logger_name: Optional[str] = None,
) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(logger_name or "freight_rail_pipeline")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stdout)
    if json_format:
        stream_handler.setFormatter(JsonFormatter())
    else:
        stream_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        filename=log_dir / "pipeline.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)

    error_handler = RotatingFileHandler(
        filename=log_dir / "pipeline_error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(JsonFormatter())
    root.addHandler(error_handler)

    return root
