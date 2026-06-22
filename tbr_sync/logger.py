# -*- coding: utf-8 -*-
import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=level,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Prevent bot tokens from appearing in HTTP client logs.
    for name in ("httpx", "httpcore", "telegram", "telegram.ext", "apscheduler"):
        logging.getLogger(name).setLevel(logging.WARNING)
