"""
logging_config.py — structured, professional logging.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

LOG_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FMT = "%H:%M:%S"

def setup(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format=LOG_FMT,
        datefmt=DATE_FMT,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    # Quiet noisy libs
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

def json_log(logger: logging.Logger, event: str, **kw) -> None:
    import json
    payload = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **kw}
    logger.info(json.dumps(payload, ensure_ascii=False))
