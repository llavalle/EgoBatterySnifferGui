"""Cross-platform "keep the system awake" hooks.

Currently implements Windows via SetThreadExecutionState. macOS / Linux
fall back to no-ops (we'd want IOPMAssertionCreateWithName on macOS and
systemd-inhibit / org.freedesktop.ScreenSaver on Linux).
"""

from __future__ import annotations

import ctypes
import sys

# Windows ES_* flags
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def keep_awake_supported() -> bool:
    """True if this platform has a real implementation of set_keep_awake."""
    return sys.platform == "win32"


def set_keep_awake(enabled: bool) -> bool:
    """Request that the OS not sleep / blank the display while `enabled`.

    Returns True if the platform-specific call was made (regardless of
    its result), False if no implementation is available for this OS.
    """
    if sys.platform == "win32":
        flags = _ES_CONTINUOUS
        if enabled:
            flags |= _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        return True
    return False
