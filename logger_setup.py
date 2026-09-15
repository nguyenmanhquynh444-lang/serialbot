"""
logger_setup.py
Configures a rotating-by-run file logger so a session's history survives
after the GUI log list is gone.
"""
import logging
import os
from datetime import datetime

from paths import logs_dir


def setup_logging() -> str:
    log_dir = logs_dir()
    log_path = os.path.join(
        log_dir, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root.addHandler(file_handler)

    return log_path
