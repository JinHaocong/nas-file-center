"""Only the capability-park step runs before importing ordinary Worker code."""
from __future__ import annotations

from app.nas_compat_launcher import park_nas_compat_runtime


def main() -> None:
    park_nas_compat_runtime()
    import logging
    from app.worker import logger, worker_loop
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.setLevel(logging.INFO)
    worker_loop()


if __name__ == "__main__":
    main()
