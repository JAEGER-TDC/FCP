# JAEGER

Command and control system for multi-sensor detection and tracking.

## Prerequisites

- Python 3.12
- [Poetry](https://python-poetry.org/docs/#installation)
- `tkinter` (system package, not pip-installable)

### Install tkinter on Ubuntu/Debian

```bash
sudo apt-get install python3-tk
```

## Setup

Clone the repo, then install dependencies:

```bash
poetry install
```

## Running

### Forward Command Post (FCP)

```bash
poetry run python fcp/fcp_app.py
```

### DNN Simulator

```bash
poetry run python simulators/dnn_sim/dnn_sim_app.py
```

### Standalone Position Simulator

```bash
poetry run python simulators/fcp/dnn_pos_sim.py
```

## Configuration

- FCP network settings: `fcp/cfg/config.ini`
- DNN Simulator network settings: `simulators/dnn_sim/cfg/config.ini`
- Standalone simulator environment variables: `.env` (see `.env` at repo root)
