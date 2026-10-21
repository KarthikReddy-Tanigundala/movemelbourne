"""Keep a Windows PC from idle-sleeping while a collector run is in progress.

Uses SetThreadExecutionState, a per-thread request that Windows drops automatically when the
process exits. It changes no power settings. No-op on other platforms (GitHub Actions runners
never sleep).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def keep_awake() -> Iterator[None]:
    """Hold a 'system required' request for the duration of the block (Windows only)."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    if not kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED):
        logger.warning("could not request keep-awake; the PC may sleep during collection")
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
