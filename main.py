# -*- coding: utf-8 -*-
"""Entry point for TBR sync bot."""

import asyncio
import logging

from tbr_sync.config import Config
from tbr_sync.logger import setup_logging
from tbr_sync.syncer import Syncer

log = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    config = Config.from_env()
    syncer = Syncer(config)
    await syncer.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Signal handlers already stop the loop cleanly; this covers Windows.
        log.info("Stopped by keyboard interrupt.")
