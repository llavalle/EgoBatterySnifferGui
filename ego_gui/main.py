"""Phase 1 CLI: read NDJSON from serial (or a captured file), maintain
BatteryState, print a one-line dashboard each second.

Run:
    python -m ego_gui.main --list-ports
    python -m ego_gui.main --port COM5
    python -m ego_gui.main --replay capture.ndjson
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterator

import serial
from serial.tools import list_ports

from .parser import parse_line
from .state import BatteryState


def cmd_list_ports() -> int:
    ports = list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return 0
    for p in ports:
        vid = f"{p.vid:04X}" if p.vid else "----"
        pid = f"{p.pid:04X}" if p.pid else "----"
        print(f"{p.device}\tVID={vid} PID={pid}\t{p.description}")
    return 0


def render_dashboard(s: BatteryState) -> str:
    parts = [f"mode={s.mode}"]
    if s.id_bytes:
        parts.append(f"id={s.id_bytes.hex().upper()}")
    if s.s_count is not None:
        parts.append(f"{s.s_count}S")
    if s.gen is not None:
        parts.append(f"gen{s.gen}")
    if s.ah_per_cell_x100 is not None:
        parts.append(f"{s.ah_per_cell_x100 / 100:.2f}Ah/cell")

    if s.mode == "discharge":
        pv = s.pack_voltage_cv()
        if pv is not None:
            parts.append(f"pack={pv / 100:.2f}V")
        slots = s.s_count or len(s.cells_cv)
        cells_seen = sum(1 for c in s.cells_cv[:slots] if c is not None)
        parts.append(f"cells={cells_seen}/{slots}")
        if any(t is not None for t in s.temps_f):
            ts = ",".join(f"{t}F" if t is not None else "-" for t in s.temps_f)
            parts.append(f"temps={ts}")
    elif s.mode == "charge":
        if s.soc_pct is not None:
            parts.append(f"soc={s.soc_pct}%")
        if s.cur is not None:
            parts.append(f"cur={s.cur / 100:.2f}A")
        if s.i_out_ca is not None:
            parts.append(f"target={s.i_out_ca / 100:.2f}A")
        if s.v_out_cv is not None:
            parts.append(f"vout={s.v_out_cv / 100:.2f}V")
        if s.output_enabled is not None:
            parts.append(f"out={'ON' if s.output_enabled else 'OFF'}")
        if s.fan_set is not None:
            parts.append(f"fan={s.fan_set}")
    elif s.mode == "idle":
        if s.last_id_seen:
            parts.append(f"last_id={time.monotonic() - s.last_id_seen:.1f}s")

    return "  ".join(parts)


def stream_serial(port: str, baud: int) -> Iterator[str]:
    """Yield decoded serial lines. Yields '' on read timeout so the caller
    can still tick the dashboard while the bus is quiet."""
    ser = serial.Serial(port, baud, timeout=0.5)
    print(f"opened {port} @ {baud}", file=sys.stderr)
    try:
        while True:
            raw = ser.readline()
            if not raw:
                yield ""
                continue
            yield raw.decode("utf-8", errors="replace")
    finally:
        ser.close()


def stream_replay(path: Path) -> Iterator[str]:
    """Yield lines from a captured NDJSON file. Used for offline testing."""
    with path.open() as f:
        for line in f:
            yield line


def run(stream: Iterator[str]) -> None:
    state = BatteryState()
    last_print = 0.0
    for line in stream:
        if line:
            ev = parse_line(line)
            if ev is not None:
                state.apply(ev)
        now = time.monotonic()
        state.update_mode(now)
        if now - last_print >= 1.0:
            print(render_dashboard(state))
            last_print = now


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EGO battery sniffer CLI (Phase 1)")
    p.add_argument("--port", help="Serial port (e.g. COM5 or /dev/ttyUSB0)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--replay", type=Path, help="Read NDJSON from a file instead of serial")
    p.add_argument("--list-ports", action="store_true", help="List available serial ports and exit")
    args = p.parse_args(argv)

    if args.list_ports:
        return cmd_list_ports()
    if not args.port and not args.replay:
        p.error("either --port or --replay is required")

    try:
        if args.replay:
            run(stream_replay(args.replay))
        else:
            run(stream_serial(args.port, args.baud))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
    except serial.SerialException as e:
        print(f"serial error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
