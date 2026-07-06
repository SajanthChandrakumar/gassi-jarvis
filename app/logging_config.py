"""
Central logging configuration for Gassi-Jarvis.

All modules should do `log = logging.getLogger(__name__)` at the top.
The root level is configurable via the JARVIS_LOG_LEVEL env var
(DEBUG | INFO | WARNING | ERROR). Default: INFO.
"""

import logging
import os


def setup_logging() -> None:
    """Configure the root logger once at process start."""
    level_name = os.environ.get("JARVIS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Quiet down noisy third-party libs.
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # We deliberately run mixed manual + callable tools, which disables the
    # SDK's Automatic Function Calling. Memory tools are dispatched by hand in
    # agent.py, so the SDK's per-call "AFC is disabled" warning is expected noise.
    logging.getLogger("google_genai.types").setLevel(logging.ERROR)
