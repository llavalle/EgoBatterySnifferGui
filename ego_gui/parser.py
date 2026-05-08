# SPDX-License-Identifier: GPL-3.0-or-later
"""NDJSON event parser for the EGO sniffer firmware.

The firmware emits one self-describing JSON object per line. See guiplan.md
for the full schema. This module just turns raw lines into dicts and
silently drops anything that isn't a well-formed event - serial often has
boot garbage and partial reads at the start of a session.
"""

from __future__ import annotations

import json
from typing import Any


def parse_line(line: str) -> dict[str, Any] | None:
    """Parse a single NDJSON line. Returns the dict on success, else None."""
    line = line.strip()
    if not line or line[0] != "{":
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "t" not in obj:
        return None
    return obj
