# JAEGER — CLAUDE.md

JAEGER is the **TURBODRONE** command and control system: a distributed ground-based drone-detection network with a Python/Tkinter GUI at its center. The mission is F2T2EA (Find, Fix, Track, Target, Engage, Assess) of rogue aerial targets (RATs) across three concentric quarter-circle zones.

## Repo Structure

```
JAEGER/
├── fcp/                    # Forward Command Post — main C2 GUI (owner: Jeff)
│   ├── fcp_app.py          # Entry point; wires Model + View + Controller, starts mission
│   ├── controller/         # UDP listener, command sender, analytics trigger
│   ├── model/              # FCPModel (state), Rat, Node, FCPAnalyticsDB (SQLite)
│   ├── view/               # FCPView layout + 7 frames (video, map, alert, control, analytics, rat, node)
│   ├── cfg/config.ini      # Network config: recv 0.0.0.0:5000, send 127.0.0.1:5001
│   └── data/analytics.db   # SQLite mission DB (NOT in .gitignore — keep large test runs out of commits)
├── simulators/
│   ├── dnn_sim/            # Full DNN simulator with its own MVC GUI
│   └── dne_sim/            # Full DNE simulator with its own MVC GUI
├── ANALYSIS.md             # Full architectural analysis with findings and SOW traceability
└── TDC_2025-2026_SOW_FINAL_REV3.pdf  # Contract Statement of Work (project "TURBODRONE")
```

## Running the Applications

Requires Python 3.12, Poetry, and `sudo apt-get install python3-tk`. Run from the repo root.

```bash
# Forward Command Post (primary app)
poetry run python fcp/fcp_app.py

# DNN Simulator (pair with FCP for end-to-end testing)
poetry run python simulators/dnn_sim/dnn_sim_app.py

# Standalone position simulator (legacy — currently broken with FCP)
poetry run python simulators/fcp/dnn_pos_sim.py
```

## Architecture

**Pattern:** MVC throughout. Each app has `model/`, `view/`, `controller/` packages.

**Communication:** JSON over UDP.
- DNN → FCP: port 5000 (positional and health messages)
- FCP → DNN: port 5001 (detection mode commands)

**Message types:**
- `positional` — `{msg_type, rat_id, zone, current_time, values: {az,el,range}, rates: {az,el,range}}`
- `health` — `{msg_type, current_time, health: {battery_percent, temperature_c, error_code, status_flag}}`
- `command` — `{msg_type, command: "set_detection_mode", mode: "lidar|rf|acoustic", enabled: bool}`

**Zones (SOW §1.2):** 1=outer (85m detection), 2=middle (60m tracking), 3=central (30m engagement). Zone 3 enables the engage button on a RAT card.

**Mission lifecycle:** Auto-started on app launch (`start_mission()`), auto-ended on window close (`end_mission()`). All events persist to `analytics.db`.

## SOW Compliance Status (FCP — Section 3)

| Req | Status |
|-----|--------|
| 3.1 Real-time video ≥30fps | ✓ Done |
| 3.2 CV tracking confidence ≥30fps | ✗ Partial -- CV integration done separately |
| 3.3 F2T2EA performance analytics | ✓ Done |
| 3.4 Node network map with locations & links ≤1000ms | ✓ Done |
| 3.5 Node fault/power alerts ≤5000ms | ✓ Done |
| 3.7 Command the Ground-Based Defense Network | ✓ Done |

## Development Notes

- All DB queries use parameterized `?` placeholders — no SQL injection risk.
- `analytics.db` is not gitignored — avoid committing it after test runs.
- `Effectors/` is empty. `engage_rat()` in the controller logs to DB but sends no effector command.
- The MATLAB `Detectors/DNN_Wrapper.m` is a stub. The DNN simulator is the current full substitute.
- There are zero automated tests in the repo.
- Poetry `package-mode = false`; imports use bare package names so scripts must be run from the repo root via `poetry run`.
