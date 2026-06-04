# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-platform "keep the system awake" hooks.

Windows : SetThreadExecutionState
macOS   : IOPMAssertionCreateWithName / IOPMAssertionRelease
Linux   : no-op (could add systemd-inhibit / org.freedesktop.ScreenSaver)
"""

from __future__ import annotations

import ctypes
import sys

# Windows ES_* flags
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

# macOS IOKit assertion ID (0 = none held)
_macos_assertion_id: int = 0


def _macos_iokit() -> ctypes.CDLL | None:
    try:
        return ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit"
        )
    except OSError:
        return None


def keep_awake_supported() -> bool:
    """True if this platform has a real implementation of set_keep_awake."""
    return sys.platform in ("win32", "darwin")


def set_keep_awake(enabled: bool) -> bool:
    """Request that the OS not sleep / blank the display while `enabled`.

    Returns True if the platform-specific call was made (regardless of
    its result), False if no implementation is available for this OS.
    """
    global _macos_assertion_id

    if sys.platform == "win32":
        flags = _ES_CONTINUOUS
        if enabled:
            flags |= _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        return True

    if sys.platform == "darwin":
        iokit = _macos_iokit()
        if iokit is None:
            return False
        if enabled and _macos_assertion_id == 0:
            # IOReturn IOPMAssertionCreateWithName(
            #     CFStringRef type, IOPMAssertionLevel level,
            #     CFStringRef name, IOPMAssertionID *id)
            CoreFoundation = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            CoreFoundation.CFStringCreateWithCString.restype = ctypes.c_void_p
            CoreFoundation.CFStringCreateWithCString.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
            ]
            kCFStringEncodingUTF8 = 0x08000100
            assertion_type = CoreFoundation.CFStringCreateWithCString(
                None, b"NoDisplaySleepAssertion", kCFStringEncodingUTF8
            )
            assertion_name = CoreFoundation.CFStringCreateWithCString(
                None, b"EgoBatterySniffer active capture", kCFStringEncodingUTF8
            )
            iokit.IOPMAssertionCreateWithName.restype = ctypes.c_uint32
            iokit.IOPMAssertionCreateWithName.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32)
            ]
            aid = ctypes.c_uint32(0)
            kIOPMAssertionLevelOn = 255
            ret = iokit.IOPMAssertionCreateWithName(
                assertion_type, kIOPMAssertionLevelOn, assertion_name,
                ctypes.byref(aid)
            )
            if ret == 0:  # kIOReturnSuccess
                _macos_assertion_id = aid.value
        elif not enabled and _macos_assertion_id != 0:
            iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
            iokit.IOPMAssertionRelease(_macos_assertion_id)
            _macos_assertion_id = 0
        return True

    return False
