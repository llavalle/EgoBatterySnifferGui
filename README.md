# EGO Battery GUI

Cross-platform Python GUI for the EGO battery sniffer firmware (see the
sibling `EgoBatterySnifferFirmware` repo). Reads NDJSON over USB serial,
maintains a `BatteryState` model, and shows mode-aware UI panels
(discharge / charging / idle).

See [guiplan.md](guiplan.md) for the full plan and protocol schema.

## Setup

```sh
python -m venv .venv
source .venv/Scripts/activate         # Git Bash on Windows
# or: .venv\Scripts\Activate.ps1       # PowerShell
pip install -r requirements.txt
```

## Phase 2 (current): minimal GUI

```sh
python -m ego_gui                            # launch the GUI
```

Port dropdown auto-selects boards matching a known sniffer VID/PID
(currently `2341:0042` - Arduino-LLC Mega 2560), Connect/Disconnect,
scrolling NDJSON debug log, RX activity LED, and a persistent header
showing battery identity + current mode.

## CLI (Phase 1, still useful headless)

```sh
python -m ego_gui.main                       # auto-detect the Mega by VID/PID
python -m ego_gui.main --list-ports          # list ports; sniffer matches marked *
python -m ego_gui.main --port COM5           # explicit port
python -m ego_gui.main --replay capture.ndjson
```

If no `--port` (or `--replay`) is given, the CLI scans serial ports for a
known sniffer VID/PID and opens the match. Pass `--port` to override or
to use a clone with a different VID/PID.

`--replay` reads a saved NDJSON file instead of opening a serial port -
useful for offline testing and protocol-decoder development.

## License

GNU General Public License v3.0 or later (`GPL-3.0-or-later`). See
[LICENSE](LICENSE) for the full text. Source files carry the SPDX
identifier so license scanners pick it up automatically.
