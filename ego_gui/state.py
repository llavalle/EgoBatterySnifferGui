# SPDX-License-Identifier: GPL-3.0-or-later
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


# Vocabulary classification for mode detection (per guiplan.md, plus the
# full-battery end-of-session commands documented in the firmware README).
CHARGE_CMDS = frozenset({
    "EVACHG", "GETCG1", "OUTCG1", "GET_VM", "OUT_VM", "GET_CM", "OUT_CM",
    "EN_OUT", "CHGING", "ADDCUR", "DECCUR", "OUTCUR", "CHGPCT", "FAN_ON",
    "FANOFF", "DISOUT", "CHGFUL", "SLEEP_",
})

DISCHARGE_CMDS = frozenset({
    "RD_VOL", "RD_TMP", "RD_SPC", "RD_CAP", "RD_FSH",
})

# Charging vocabulary that classifies the session, including the
# end-of-session sequence seen on a battery that's already full.


# These appear in both modes (or are mode-neutral); they don't classify on
# their own but their presence in isolation indicates idle.
NEUTRAL_CMDS = frozenset({"ID", "START_", "ADJUST"})

Mode = Literal["idle", "discharge", "charge", "unknown"]

# How recently a vocabulary frame must have been seen to lock that mode
MODE_VOCAB_WINDOW_S = 5.0
# How long without any frames before declaring "unknown"
MODE_DEAD_WINDOW_S = 10.0
# Max gap between consecutive ID frames that still counts as the same
# heartbeat run. Larger gaps reset id_interval_ms so the EWMA tracks the
# current cadence instead of dragging in a stale interval.
ID_CADENCE_GAP_S = 1.0
# EWMA weight on the most recent inter-arrival sample (0..1). 0.3 ≈
# 3-sample moving average; smooth enough to not jitter, fast enough to
# track a cadence change within a few beats.
ID_CADENCE_ALPHA = 0.3


@dataclass
class BatteryState:
    # Identity (from ID frame + RD_SPC + RD_CAP + RD_FSH)
    id_bytes: bytes | None = None
    s_count: int | None = None
    p_count: int | None = None
    gen: int | None = None
    ah_per_cell_x100: int | None = None
    fsh_status: int | None = None
    # Gen1 flash-page map: addr (e.g. 0x78..0x7B) -> byte at that address.
    # Populated as the tool sweeps RD_FSH pages. Gen2 packs answer a single
    # status read at 0x38, which also lands here.
    fsh_pages: dict[int, int] = field(default_factory=dict)
    last_id_seen: float = 0.0  # monotonic timestamp

    # Discharge / diagnostic readouts
    cells_cv: list[int | None] = field(default_factory=lambda: [None] * 14)
    temps_f: list[int | None] = field(default_factory=lambda: [None, None])

    # Charging readouts
    v_out_cv: int | None = None
    i_out_ca: int | None = None
    cur: int | None = None
    add_cur: int | None = None
    dec_cur: int | None = None
    # Most recent battery delta-current request, signed: + from ADDCUR
    # (ramp up), - from DECCUR (taper). Whichever was seen most recently
    # wins.
    delta_cur: int | None = None
    soc_pct: int | None = None
    fan_req: int | None = None
    fan_set: int | None = None
    output_enabled: bool | None = None
    chg_id: int | None = None
    # True after a CHGFUL handshake (battery was already full when plugged
    # in); cleared when EVACHG opens a new charge session.
    battery_full: bool = False

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

    # ID heartbeat cadence (EWMA over consecutive ID frames). None until
    # at least two IDs have been seen within ID_CADENCE_GAP_S of each
    # other; reset when a longer gap appears (e.g. a discharge session
    # where the tool dominates the bus).
    id_interval_ms: float | None = None
    _prev_id_seen: float = field(default=0.0, repr=False, compare=False)

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
            # Heartbeat cadence: EWMA on the inter-arrival, but reset on
            # long gaps so a stale interval from a previous run doesn't
            # bias the average.
            if self._prev_id_seen > 0.0:
                gap = now - self._prev_id_seen
                if gap < ID_CADENCE_GAP_S:
                    sample_ms = gap * 1000.0
                    if self.id_interval_ms is None:
                        self.id_interval_ms = sample_ms
                    else:
                        self.id_interval_ms = (
                            (1.0 - ID_CADENCE_ALPHA) * self.id_interval_ms
                            + ID_CADENCE_ALPHA * sample_ms
                        )
                else:
                    self.id_interval_ms = None
            self._prev_id_seen = now
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
            if "p_count" in ev:
                self.p_count = ev["p_count"]
        elif cmd == "RD_CAP":
            if "ah_per_cell_x100" in ev:
                self.ah_per_cell_x100 = ev["ah_per_cell_x100"]
        elif cmd == "RD_FSH":
            addr = ev.get("fsh_addr")
            val = ev.get("fsh_value")
            status = ev.get("status")
            status_int: int | None = None
            if isinstance(status, str):
                try:
                    status_int = int(status, 16)
                    self.fsh_status = status_int
                except ValueError:
                    pass
            # Legacy captures (pre-fsh_addr/fsh_value firmware) only had
            # `status`; derive addr/value from it so replayed captures still
            # populate the page map.
            if status_int is not None:
                if not isinstance(addr, int):
                    addr = (status_int >> 8) & 0xFF
                if not isinstance(val, int):
                    val = status_int & 0xFF
            if isinstance(addr, int) and isinstance(val, int):
                self.fsh_pages[addr] = val
        elif cmd == "ADJUST":
            # Battery's ADJUST reply is the documented gen marker: Gen1
            # echoes 0x0000, Gen2 replies 0x00A0. Firmware emits `gen` on
            # BATT->ADJUST; legacy captures used a (wrong) RD_FSH-based
            # `gen` instead, so fall back to inferring it from `data` when
            # the new field is absent and the frame is from the battery.
            if "gen" in ev:
                self.gen = ev["gen"]
            elif ev.get("dir") == "BATT":
                data = ev.get("data")
                if data == 0x0000:
                    self.gen = 1
                elif data == 0x00A0:
                    self.gen = 2
        elif cmd == "START_":
            if "chg_id" in ev:
                self.chg_id = ev["chg_id"]
        elif cmd == "EVACHG":
            # New charge session beginning -- clear any "full" flag carried
            # over from a previous plug-in.
            self.battery_full = False
        elif cmd == "OUT_VM":
            if "v_out_cv" in ev:
                self.v_out_cv = ev["v_out_cv"]
        elif cmd == "OUT_CM":
            if "i_out_ca" in ev:
                self.i_out_ca = ev["i_out_ca"]
        elif cmd == "EN_OUT":
            if "enabled" in ev:
                self.output_enabled = ev["enabled"]
        elif cmd == "DISOUT":
            # Counterpart to EN_OUT in the full-battery sequence; the
            # output is being commanded off regardless of payload.
            self.output_enabled = False
        elif cmd == "ADDCUR":
            val = ev.get("add_cur", ev.get("data"))
            if val is not None:
                self.add_cur = val
                self.delta_cur = +val
        elif cmd == "DECCUR":
            # Firmware doesn't emit a per-command field for DECCUR, so
            # fall back to the generic `data` field.
            val = ev.get("dec_cur", ev.get("data"))
            if val is not None:
                self.dec_cur = val
                self.delta_cur = -val
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
        elif cmd == "FANOFF":
            # Counterpart to FAN_ON in the full-battery sequence.
            # BATT->FANOFF is the request, TOOL->FANOFF the actual setting.
            dir_ = ev.get("dir")
            if dir_ == "BATT":
                self.fan_req = 0
            elif dir_ == "TOOL":
                self.fan_set = 0
        elif cmd == "CHGFUL":
            self.battery_full = True

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
