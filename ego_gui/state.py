"""BatteryState model + vocabulary-based mode detection.

The state is the consumer's accumulated view of what the battery and its
peer (tool / charger / nothing) are doing. Updated by feeding parsed
events through `apply()`. Call `update_mode()` periodically to recompute
which mode panel the GUI should show.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal


# Vocabulary classification for mode detection (per guiplan.md)
CHARGE_CMDS = frozenset({
    "EVACHG", "GETCG1", "OUTCG1", "GET_VM", "OUT_VM", "GET_CM", "OUT_CM",
    "EN_OUT", "CHGING", "ADDCUR", "OUTCUR", "CHGPCT", "FAN_ON",
})

DISCHARGE_CMDS = frozenset({
    "RD_VOL", "RD_TMP", "RD_SPC", "RD_CAP", "RD_FSH",
})

# These appear in both modes (or are mode-neutral); they don't classify on
# their own but their presence in isolation indicates idle.
NEUTRAL_CMDS = frozenset({"ID", "START_", "ADJUST"})

Mode = Literal["idle", "discharge", "charge", "unknown"]

# How recently a vocabulary frame must have been seen to lock that mode
MODE_VOCAB_WINDOW_S = 5.0
# How long without any frames before declaring "unknown"
MODE_DEAD_WINDOW_S = 10.0


@dataclass
class BatteryState:
    # Identity (from ID frame + RD_SPC + RD_CAP + RD_FSH)
    id_bytes: bytes | None = None
    s_count: int | None = None
    model: int | None = None
    gen: int | None = None
    ah_per_cell_x100: int | None = None
    fsh_status: int | None = None
    last_id_seen: float = 0.0  # monotonic timestamp

    # Discharge / diagnostic readouts
    cells_cv: list[int | None] = field(default_factory=lambda: [None] * 14)
    temps_f: list[int | None] = field(default_factory=lambda: [None, None])

    # Charging readouts
    v_out_cv: int | None = None
    i_out_ca: int | None = None
    cur: int | None = None
    add_cur: int | None = None
    soc_pct: int | None = None
    fan_req: int | None = None
    fan_set: int | None = None
    output_enabled: bool | None = None
    chg_id: int | None = None

    # Mode tracking (recomputed by update_mode)
    mode: Mode = "unknown"
    last_charge_cmd_at: float = 0.0
    last_discharge_cmd_at: float = 0.0
    last_frame_at: float = 0.0
    last_activity: float = 0.0

    # Connection / firmware identity
    fw: str | None = None
    fw_build: str | None = None

    # Pairing state for indexed read commands. The protocol sends
    # TOOL->RD_VOL with `cell` and BATT->RD_VOL with `v_cv` in separate
    # frames; we hold the last query's index so the next matching
    # response can be assigned to the right slot.
    _pending_cell: int | None = field(default=None, repr=False, compare=False)
    _pending_sensor: int | None = field(default=None, repr=False, compare=False)

    def apply(self, event: dict[str, Any]) -> None:
        """Update state from a parsed NDJSON event."""
        t = event.get("t")
        now = time.monotonic()
        if t == "hello":
            self.fw = event.get("fw")
            self.fw_build = event.get("build")
            return
        if t == "tx":
            self.last_activity = now
            return
        if t == "frame":
            self.last_frame_at = now
            self.last_activity = now
            self._apply_frame(event, now)
            return
        # evt: not state-bearing for now (could be logged)

    def _apply_frame(self, ev: dict[str, Any], now: float) -> None:
        cmd = ev.get("cmd")

        if cmd == "ID":
            bytes_str = ev.get("bytes", "")
            try:
                self.id_bytes = bytes.fromhex(bytes_str.replace(" ", ""))
            except ValueError:
                pass
            self.last_id_seen = now
            return

        if cmd in CHARGE_CMDS:
            self.last_charge_cmd_at = now
        elif cmd in DISCHARGE_CMDS:
            self.last_discharge_cmd_at = now

        # Per-command field application -- mirrors the firmware's emit logic.
        if cmd == "RD_VOL":
            if "cell" in ev:
                self._pending_cell = ev["cell"]            # tool query
            elif "v_cv" in ev and self._pending_cell is not None:
                idx = self._pending_cell                    # battery response
                if 0 <= idx < len(self.cells_cv):
                    self.cells_cv[idx] = ev["v_cv"]
                self._pending_cell = None
        elif cmd == "RD_TMP":
            if "sensor" in ev:
                self._pending_sensor = ev["sensor"]
            elif "temp_f" in ev and self._pending_sensor is not None:
                idx = self._pending_sensor
                if 0 <= idx < len(self.temps_f):
                    self.temps_f[idx] = ev["temp_f"]
                self._pending_sensor = None
        elif cmd == "RD_SPC":
            if "s_count" in ev:
                self.s_count = ev["s_count"]
            if "model" in ev:
                self.model = ev["model"]
        elif cmd == "RD_CAP":
            if "ah_per_cell_x100" in ev:
                self.ah_per_cell_x100 = ev["ah_per_cell_x100"]
        elif cmd == "RD_FSH":
            status = ev.get("status")
            if isinstance(status, str):
                try:
                    self.fsh_status = int(status, 16)
                except ValueError:
                    pass
            if "gen" in ev:
                self.gen = ev["gen"]
        elif cmd == "START_":
            if "chg_id" in ev:
                self.chg_id = ev["chg_id"]
        elif cmd == "OUT_VM":
            if "v_out_cv" in ev:
                self.v_out_cv = ev["v_out_cv"]
        elif cmd == "OUT_CM":
            if "i_out_ca" in ev:
                self.i_out_ca = ev["i_out_ca"]
        elif cmd == "EN_OUT":
            if "enabled" in ev:
                self.output_enabled = ev["enabled"]
        elif cmd == "ADDCUR":
            if "add_cur" in ev:
                self.add_cur = ev["add_cur"]
        elif cmd == "OUTCUR":
            if "cur" in ev:
                self.cur = ev["cur"]
        elif cmd == "CHGPCT":
            if "soc_pct" in ev:
                self.soc_pct = ev["soc_pct"]
        elif cmd == "FAN_ON":
            if "fan_req" in ev:
                self.fan_req = ev["fan_req"]
            if "fan_set" in ev:
                self.fan_set = ev["fan_set"]

    def update_mode(self, now: float | None = None) -> None:
        """Recompute self.mode based on observed activity. Call ~1Hz."""
        if now is None:
            now = time.monotonic()
        if self.last_frame_at == 0.0 or now - self.last_frame_at > MODE_DEAD_WINDOW_S:
            self.mode = "unknown"
            return
        if now - self.last_charge_cmd_at < MODE_VOCAB_WINDOW_S:
            self.mode = "charge"
        elif now - self.last_discharge_cmd_at < MODE_VOCAB_WINDOW_S:
            self.mode = "discharge"
        elif now - self.last_id_seen < MODE_VOCAB_WINDOW_S:
            self.mode = "idle"
        # else: leave mode unchanged (transient gap)

    def pack_voltage_cv(self) -> int | None:
        """Sum of populated cell voltages, in centivolts. None until full."""
        if self.s_count is None:
            return None
        cells = [c for c in self.cells_cv[: self.s_count] if c is not None]
        if len(cells) != self.s_count:
            return None
        return sum(cells)
