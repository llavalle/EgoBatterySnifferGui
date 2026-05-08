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

## Phase 1 (current): CLI dashboard

Read NDJSON from the firmware over serial, maintain state, print a
one-line dashboard each second:

```sh
python -m ego_gui.main --list-ports
python -m ego_gui.main --port COM5
python -m ego_gui.main --replay capture.ndjson
```

`--replay` reads a saved NDJSON file instead of opening a serial port -
useful for offline testing and protocol-decoder development.
