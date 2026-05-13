# EGO Battery GUI — Plan

A cross-platform (Windows + macOS) Python GUI that reads from the Arduino
sniffer over USB serial and shows live battery state with RX/TX activity
LEDs and a debug log.

The GUI must handle three operating modes that the battery slips between:

- **Discharge / diagnostic** — battery in a tool. Smart tool reads cells,
  temps, P/S count, capacity, FSH (`RD_VOL`/`RD_TMP`/`RD_SPC`/`RD_CAP`/`RD_FSH`).
  Dumb tool stays silent and we only see the battery's `ID, ID, START_`
  invite cycle.
- **Charging** — battery on a charger. Different vocabulary entirely:
  `EVACHG`, `GET_VM`/`OUT_VM`, `GET_CM`/`OUT_CM`, `EN_OUT`, `CHGING`,
  `ADDCUR`/`OUTCUR`, `FAN_ON`, `CHGPCT`. No cell or temp reads.
- **Idle** — battery alone, no tool / charger. Just the ID heartbeat.

The mode is detected from the command vocabulary on the wire, not declared.
The GUI auto-switches its main panel based on what it observes.

## Decisions

| Topic            | Choice                                                  |
|------------------|---------------------------------------------------------|
| GUI framework    | **PySide6** (Qt, LGPL)                                  |
| Serial format    | **NDJSON only** — Arduino emits one JSON object per line; no human-readable fallback |
| Distribution     | **Local app** (Python script + `requirements.txt`); PyInstaller bundle later if needed |
| Port selection   | **Dropdown of all serial ports**; auto-select the Arduino by VID/PID when one is detected |

## Serial format (Arduino → GUI)

Each line is a self-describing JSON object. Examples covering both modes:

```json
{"t":"hello","fw":"egodecoder/1.0","build":"<git sha or date>"}
{"t":"frame","ms":1000,"idx":1,"dir":"BATT","bits":40,"bytes":"AA 0B 4A 49 D5","crc":"ok","cmd":"ID"}

# Diagnostic / discharge mode
{"t":"frame","ms":24629,"idx":22,"dir":"TOOL","bits":73,"bytes":"00 07 4C 4F 56 5F 44 52 0F","crc":"ok","cmd":"RD_VOL","data":1792,"cell":7}
{"t":"frame","ms":24717,"idx":23,"dir":"BATT","bits":73,"bytes":"6E 01 4C 4F 56 5F 44 52 D9","crc":"ok","cmd":"RD_VOL","data":366,"v_cv":366}
{"t":"frame","ms":24800,"idx":24,"dir":"BATT","bits":73,"bytes":"49 00 50 4D 54 5F 44 52 3E","crc":"ok","cmd":"RD_TMP","data":73,"temp_f":73}
{"t":"frame","ms":25000,"idx":25,"dir":"BATT","bits":73,"bytes":"03 0E 43 50 53 5F 44 52 B0","crc":"ok","cmd":"RD_SPC","data":3587,"s_count":14,"p_count":4}
{"t":"frame","ms":25100,"idx":26,"dir":"BATT","bits":73,"bytes":"FA 00 50 41 43 5F 44 52 0A","crc":"ok","cmd":"RD_CAP","data":250,"ah_per_cell_x100":250}
{"t":"frame","ms":25200,"idx":27,"dir":"BATT","bits":73,"bytes":"02 38 48 53 46 5F 44 52 66","crc":"ok","cmd":"RD_FSH","data":14338,"status":"0x3802","gen":2}

# Charging mode
{"t":"frame","ms":50000,"idx":100,"dir":"TOOL","bits":73,"bytes":"D7 00 5F 54 52 41 54 53 EF","crc":"ok","cmd":"START_","data":215,"chg_id":215}
{"t":"frame","ms":50100,"idx":101,"dir":"TOOL","bits":73,"bytes":"70 17 4D 56 5F 54 55 4F E3","crc":"ok","cmd":"OUT_VM","data":6000,"v_out_cv":6000}
{"t":"frame","ms":50200,"idx":102,"dir":"TOOL","bits":73,"bytes":"2C 01 4D 43 5F 54 55 4F 1A","crc":"ok","cmd":"OUT_CM","data":300,"i_out_ca":300}
{"t":"frame","ms":50300,"idx":103,"dir":"TOOL","bits":73,"bytes":"01 00 54 55 4F 5F 4E 45 96","crc":"ok","cmd":"EN_OUT","data":1,"enabled":true}
{"t":"frame","ms":50400,"idx":104,"dir":"BATT","bits":73,"bytes":"05 00 52 55 43 44 44 41 2E","crc":"ok","cmd":"ADDCUR","data":5,"add_cur":5}
{"t":"frame","ms":50500,"idx":105,"dir":"TOOL","bits":73,"bytes":"E1 00 52 55 43 54 55 4F 35","crc":"ok","cmd":"OUTCUR","data":225,"cur":225}
{"t":"frame","ms":50600,"idx":106,"dir":"BATT","bits":73,"bytes":"1C 00 54 43 50 47 48 43 E4","crc":"ok","cmd":"CHGPCT","data":28,"soc_pct":28}
{"t":"frame","ms":50700,"idx":107,"dir":"BATT","bits":73,"bytes":"64 00 4E 4F 5F 4E 41 46 57","crc":"ok","cmd":"FAN_ON","data":100,"fan_req":100}
{"t":"frame","ms":50800,"idx":108,"dir":"TOOL","bits":73,"bytes":"AC 00 4E 4F 5F 4E 41 46 A6","crc":"ok","cmd":"FAN_ON","data":172,"fan_set":172}

# Events / errors
{"t":"evt","ms":24500,"evt":"long_low","dur_us":1009924}
{"t":"err","ms":13000,"err":"crc_bad","want":"B3"}
```

Rules:
- One object per line, terminated by `\n`.
- `t` (top-level type) is always present: `frame` | `evt` | `err` | `hello` | `tx`.
- `ms` is the Arduino's `millis()` timestamp (wraps at ~49 days).
- For `frame` events, `dir` is `TOOL` | `BATT` | `?` (when ADC reading not available).
- `cmd` is set when a known wire command was matched (otherwise omitted).
- Per-command fields are added by the Arduino-side decoder so the GUI doesn't re-decode:
  - **Discharge:** `cell` (req), `v_cv` (resp, centivolts), `sensor`, `temp_f`, `s_count`, `p_count`, `ah_per_cell_x100`, `q`, `status`, `gen`.
  - **Charging:** `chg_id` (charger's `START_` payload), `v_out_cv`, `i_out_ca`, `enabled`, `add_cur`, `cur`, `soc_pct`, `fan_req`, `fan_set`.
- Direction-conditional fields follow the same logic as the Arduino's text decoder: `add_cur` only on `BATT->ADDCUR`; `cur` only on `TOOL->OUTCUR`; `soc_pct` only on `BATT->CHGPCT`; `fan_req` on BATT, `fan_set` on TOOL.

Memory-wise this is fine on the Mega — manual `sprintf`, no JSON library.

## Architecture

```
┌──────────────────────────┐         ┌─────────────────────┐
│   Serial reader thread   │  queue  │   Qt GUI main loop  │
│   (pyserial readline,    │ ──────► │   (consumes queue,  │
│    parse JSON line)      │         │    updates widgets) │
└──────────────────────────┘         └─────────────────────┘
                                          │
                                          ▼
                              ┌────────────────────────┐
                              │ BatteryState model     │
                              │  - id, P, gen, S,      │
                              │    Ah, FSH             │
                              │  - cells[14], temps[2] │
                              │  - last_seen           │
                              └────────────────────────┘
```

- `SerialReader` background thread: opens the chosen port, reads lines,
  parses JSON, pushes events into a `queue.Queue`.
- Main thread runs a 30 Hz `QTimer` that drains the queue, updates the
  `BatteryState` model, and emits Qt signals to redraw widgets.
- `ActivityLed` widget lights for ~100 ms on every RX/TX event, then fades.
- Port auto-detect uses `serial.tools.list_ports`; flags Arduino devices by
  known VID/PID pairs (Mega FT232R, CH340, etc.).

`BatteryState` content:

```python
@dataclass
class BatteryState:
    # Identity (from ID frame + RD_SPC + RD_CAP + RD_FSH)
    id_bytes: bytes | None
    s_count: int | None        # series cell count (always 14 observed)
    p_count: int | None        # parallel cell count (firmware bakes in +1)
    gen: int | None            # 1 or 2
    ah_per_cell_x100: int | None
    fsh_status: int | None     # 0x38FF = Gen1 stub
    last_id_seen: float        # monotonic timestamp

    # Discharge / diagnostic readouts (from RD_VOL / RD_TMP)
    cells_cv: list[int | None] # 14 cells, centivolts, None if not yet read
    temps_f: list[int | None]  # 2 sensors, degrees F

    # Charging readouts (from charging-protocol commands)
    v_out_cv: int | None       # charger's reported output voltage, centivolts
    i_out_ca: int | None       # charger's reported output current, centiamps (target)
    cur: int | None            # actual delivered current (OUTCUR)
    add_cur: int | None        # latest battery delta request (ADDCUR)
    soc_pct: int | None        # state of charge from CHGPCT
    fan_req: int | None        # battery's fan request
    fan_set: int | None        # charger's actual fan setting
    output_enabled: bool | None
    chg_id: int | None         # charger's START_ payload (e.g. 0x00D7)

    # Derived
    mode: Literal["idle", "discharge", "charge", "unknown"]
    last_activity: float

    def pack_voltage_cv(self) -> int | None:
        cs = [c for c in self.cells_cv if c is not None]
        return sum(cs) if len(cs) == self.s_count else None
```

Mode detection rule (run after each frame is consumed):

- See `EVACHG`/`ADDCUR`/`OUTCUR`/`CHGPCT`/`OUT_VM`/`OUT_CM`/`EN_OUT`/`FAN_ON` → mode = **charge**
- See `RD_VOL`/`RD_TMP`/`RD_SPC`/`RD_CAP`/`RD_FSH` → mode = **discharge**
- Only `ID` / `START_` for >5 s with no answers from any tool → mode = **idle**
- No frames for >10 s → mode = **unknown** (sniffer not seeing anything)

## GUI layout

The window has a fixed top header (always-on identity + activity LEDs) and a
**main panel that switches based on detected mode**. All three mode panels
exist as child widgets in a `QStackedWidget`; only one is visible at a time,
matching `BatteryState.mode`. The debug log is always visible at the bottom.

A small **"Mode" indicator** in the header shows which panel is active and
when it last changed.

```
┌─ EGO Battery Monitor ──────────────────────────────────────────────┐
│ Port: [COM5 ▼] [Connect] [Disconnect]      RX ● TX ○   ──── conn   │
├────────────────────────────────────────────────────────────────────┤
│ Battery: AA 0B 4A 49 D5    Model 3 (Gen2)    14S    2.50 Ah/cell    │
│ Pack: 56.42 V    FSH: 0x3802 (Gen2)    Mode: ⚡ Charging (12s)      │
├──────────── one of the three panels below ─────────────────────────┤
```

### Discharge / diagnostic panel (mode = `discharge`)

```
├──────────────────────────────────┬─────────────────────────────────┤
│ Cells (V)                        │ Temps                           │
│  0:  4.05 ▆▆▆▆▆▆▆▆               │  Sensor 0:  72 °F               │
│  1:  4.04 ▆▆▆▆▆▆▆▆               │  Sensor 1:  73 °F               │
│  …                               │                                 │
│ 13:  4.03 ▆▆▆▆▆▆▆▆               │ Tool: smart (96b handshake seen)│
│ Δmin/max: 0.06 V                 │       or "dumb (silent)"        │
└──────────────────────────────────┴─────────────────────────────────┘
```

### Charging panel (mode = `charge`)

```
├────────────────────────────────────────────────────────────────────┤
│  SOC: ████████████░░░░░░░░░░░░░░░░  31%      Charger ID: 0x00D7    │
│                                                                    │
│  Target:    60.00 V    3.00 A   (charger setpoints)                │
│  Actual:    --.-- V    2.94 A   (delivered current)                │
│  Output:    ENABLED                                                │
│                                                                    │
│  Battery delta req:  +1                  Fan req:  100             │
│  Charger fan set:    172                                           │
│                                                                    │
│  ──── Charge current vs time ─────────────────────────             │
│  [small line chart of `cur` over the last few minutes]             │
└────────────────────────────────────────────────────────────────────┘
```

Notes:
- "Actual voltage" is left blank for now — the charger only reports its
  setpoint via `OUT_VM`, not a measured pack voltage. Could be derived
  later from `cells_cv` if a discharge session has populated them.
- Battery LED-flash window (the ~1 s `long_low` event between Gen1 cycles)
  shows up as a brief animation on the activity area.
- The fan and current setpoints animate as the BMS drives them.

### Idle panel (mode = `idle`)

```
├────────────────────────────────────────────────────────────────────┤
│  Battery is alone (no tool / charger detected on the bus).         │
│                                                                    │
│  Last identity:  AA 0B 4A 49 D5                                    │
│  Heartbeat:      ID every 180 ms                                   │
│  Time since last frame:  3.2 s                                     │
└────────────────────────────────────────────────────────────────────┘
```

### Always-visible debug log

```
├────────────────────────────────────────────────────────────────────┤
│ Debug log                                                          │
│ [scrollable, color-coded by direction; one line per JSON event]    │
└────────────────────────────────────────────────────────────────────┘
```

Reserved space for future:
- send-command panel (keys `r/t/s/c/f/a/x`)
- pack-voltage history chart for discharge mode
- save capture to file (NDJSON)
- charge-session export (CSV: ms, soc, cur, fan, …)

## Phased implementation plan

### Phase 0 — Arduino: NDJSON output
- Replace all `Serial.print(F("RX  …"))` with NDJSON emitters.
- One small helper for printing a JSON object with proper escaping for the
  hex-byte string and short keys.
- Cover **all** known commands (discharge + charging) so the same firmware
  feeds either panel.
- Validate by piping the serial stream through `jq`.

### Phase 1 — Python: minimal CLI parser + state model
- 150-line script: open serial, read NDJSON, pretty-print to stdout.
- Build the `BatteryState` model with all three modes' fields.
- Implement mode detection (vocabulary-based, see Architecture section).
- Print a one-line dashboard each second showing mode + the most relevant
  fields for that mode.
- Foundation for the GUI; if it works headless, the GUI is just rendering.

### Phase 2 — Minimal GUI: debug log + RX LED + connect
- Port dropdown (with auto-select of detected Arduino), connect button,
  scrolling log, one RX activity LED.
- Proves the threading + queue + Qt signals plumbing.
- Plus the persistent header (battery identity) and a tiny "Mode: …"
  text label that updates based on `BatteryState.mode`.

### Phase 3a — Discharge panel
- Cell-voltage list with bars and Δ-min/max highlighting.
- Temperature fields.
- Pack-voltage derived from cell sum.
- "Tool kind" indicator (smart / dumb) inferred from whether RD_* commands
  are seen.

### Phase 3b — Charging panel
- SOC progress bar from `soc_pct`.
- Setpoint vs delivered current readouts (`i_out_ca` vs `cur`).
- Output-enabled indicator (`enabled`).
- Battery's `add_cur` and `fan_req`, charger's `fan_set`.
- Small live chart of `cur` over time (rolling window).

3a and 3b are **independent** — pick whichever you'll exercise first. Both
should land before "polish."

### Phase 3c — Idle panel
- Trivial: identity + heartbeat cadence + time-since-last-frame.

### Phase 4 — Polish
- Stale-data fade (cells unread for N seconds → grey out).
- Color-code log by direction (TOOL / BATT / event / error).
- "Save capture" button → writes raw NDJSON to timestamped file.
- Smooth `QStackedWidget` cross-fades on mode transitions.
- Optional: line chart of pack voltage over time (discharge); export of
  charge session CSV.

### Phase 5 (optional) — TX panel
- Buttons that replicate the Arduino serial keys (`r/t/s/c/f/a/x`).
- Only useful if the GUI ever drives the bus, not just sniffs.

## Project layout

```
EgoBatteryGui/
├── README.md
├── requirements.txt          # pyserial, PySide6
├── ego_gui/
│   ├── __init__.py
│   ├── main.py               # entry point
│   ├── serial_reader.py      # background thread
│   ├── state.py              # BatteryState + mode detection
│   ├── widgets/
│   │   ├── activity_led.py
│   │   ├── header_panel.py
│   │   ├── debug_log.py
│   │   ├── discharge_panel.py
│   │   ├── charge_panel.py
│   │   └── idle_panel.py
│   └── parser.py             # NDJSON → events
└── captures/                 # optional, gitignored
```

## Port auto-detect

Use `serial.tools.list_ports.comports()`. For each port, check `vid:pid`
against a known list:

| Vendor          | VID    | Common PIDs           | Notes                           |
|-----------------|--------|-----------------------|---------------------------------|
| FTDI            | 0x0403 | 0x6001, 0x6010, 0x6014| Genuine Mega 2560 (FT232R)      |
| WCH (CH340)     | 0x1A86 | 0x7523, 0x5523        | Most clones                     |
| Arduino LLC     | 0x2341 | 0x0042, 0x0010, …     | Newer "Mega 2560" variants      |
| Arduino SA      | 0x2A03 | 0x0042                | Older Mega 2560                 |

Selection rule:
1. If exactly one matching port exists → auto-select it on startup.
2. If multiple match → prefer the most recently plugged (highest enumeration index)
   and remember user's last choice across launches.
3. If none match → leave dropdown unselected; user picks manually.

## Open items / future considerations

- Pack-voltage chart (QtCharts).
- Capture replay: load a saved NDJSON file and play it through the GUI.
- Diff view: compare two captures side-by-side (useful for Gen1 vs Gen2).
- Decode the 178-bit (Gen1) and 96-bit (Gen2) handshake blobs once we
  understand them better — surface tool model in the GUI header.
- Battery LED-flash timer during the Gen1 inter-cycle pause (visualize the
  `~1 s long LOW` window).
