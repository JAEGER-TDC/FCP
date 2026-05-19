# JAEGER — TURBODRONE Command & Control System

JAEGER is the **Forward Command Post (FCP)** for the TURBODRONE distributed drone-detection network. It provides a real-time C2 interface for the F2T2EA (Find, Fix, Track, Target, Engage, Assess) mission across three concentric detection zones, integrating live video with CV tracking, sensor management, network health monitoring, and mission analytics.

---

## System Requirements

| Requirement | Details |
|-------------|---------|
| OS | Ubuntu / Debian (WSL2 supported) |
| Python | 3.12 (exact version required by Poetry) |
| Package manager | [Poetry](https://python-poetry.org/docs/#installation) |
| System package | `python3-tk` (see below) |
| GPU (optional) | NVIDIA GPU with TensorRT — required only for Video and Camera CV modes; Simulator mode runs on any machine |

### Install system dependencies (Ubuntu/Debian)

```bash
sudo apt-get install python3-tk
```

---

## Installation

```bash
git clone <repo-url>
cd FCP
sudo apt-get install python3-tk
poetry install
```

All commands in this guide must be run from the **repo root** (`FCP/`). Poetry's `package-mode = false` means imports resolve relative to the working directory.

---

## Running the Applications

### Forward Command Post (primary)

```bash
poetry run python fcp/fcp_app.py
```

### DNN Simulator — pair with FCP for end-to-end testing

```bash
poetry run python simulators/dnn_sim/dnn_sim_app.py
```

### DNE Simulator — simulated effector (laser system)

```bash
poetry run python simulators/dne_sim/dne_sim_app.py
```

### Standalone Position Simulator (legacy)

```bash
poetry run python simulators/fcp/dnn_pos_sim.py
```

> **Note:** The standalone simulator is a legacy tool. For full end-to-end testing, use the DNN Simulator instead.

---

## Quick-Start: First Run

1. **Launch the DNN Simulator** — `poetry run python simulators/dnn_sim/dnn_sim_app.py`
2. **Launch the FCP** — `poetry run python fcp/fcp_app.py`
3. **CV Launch Dialog appears** — select **Simulator** (no GPU required)
4. Watch the Zone Map — RAT targets will appear as the DNN Simulator generates detections
5. Monitor the Alert Log for zone transition events
6. When a RAT reaches **Zone 3**, the **Engage** button turns green — click it to fire

For a full end-to-end simulation including the effector, also launch the DNE Simulator before starting the FCP.

---

## Network Architecture

| Direction | Protocol | Address | Purpose |
|-----------|----------|---------|---------|
| DNN → FCP | UDP / JSON | `0.0.0.0:5000` | Positional and health messages |
| FCP → DNN | UDP / JSON | `127.0.0.1:5001` | Detection mode commands |
| FCP → DNE | Serial / TCP | `socket://localhost:6000` | Targeting packets and fire commands |

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Pause / resume CV tracking |
| `R` | Reset CV tracking |
| `S` | Save screenshot |
| `V` | Restart video |
| `Q` | Quit |

Shortcuts are ignored when a text input field has focus.

---

## Configuration

| File | Purpose |
|------|---------|
| `fcp/cfg/config.ini` | FCP network ports, DNN health alert thresholds, layout splitter ratios |
| `simulators/dnn_sim/cfg/config.ini` | DNN Simulator network ports |
| `.env` | Standalone position simulator environment variables |

See the [User Manual](docs/USER_MANUAL.md#configuration-reference) for a full annotated reference of all `config.ini` keys.
