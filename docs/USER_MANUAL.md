# JAEGER TURBODRONE C2 — User Manual

**System:** JAEGER Forward Command Post (FCP)  
**Mission:** F2T2EA — Find, Fix, Track, Target, Engage, Assess  

Sections marked **[OPERATOR]** use mission-operations language and assume familiarity with the F2T2EA framework. Sections marked **[TECHNICAL]** address configuration, integration, and troubleshooting for developers and system administrators.

---

## Table of Contents

1. [Mission Overview](#1-mission-overview) — OPERATOR
2. [Interface Layout](#2-interface-layout) — OPERATOR
3. [CV Launch Dialog](#3-cv-launch-dialog) — TECHNICAL
4. [Zone Map](#4-zone-map) — OPERATOR
5. [Sensor Management](#5-sensor-management) — OPERATOR
6. [Target Tracking and Engagement](#6-target-tracking-and-engagement) — OPERATOR
7. [Alert Log](#7-alert-log) — OPERATOR
8. [Analytics Panel](#8-analytics-panel) — OPERATOR
9. [Health Monitoring](#9-health-monitoring) — OPERATOR / TECHNICAL
10. [Keyboard Shortcuts](#10-keyboard-shortcuts) — OPERATOR
11. [Configuration Reference](#11-configuration-reference) — TECHNICAL
12. [Troubleshooting](#12-troubleshooting) — TECHNICAL

---

## 1. Mission Overview

**[OPERATOR]**

JAEGER is the command and control system for the **TURBODRONE** distributed ground-based drone-detection network. The FCP is the operator's primary interface for the full F2T2EA kill chain against **Rogue Aerial Targets (RATs)**.

### Detection Zones

The battlespace is divided into three concentric quarter-circle zones radiating outward from the Forward Command Post. All ranges are ground-truth distances from the FCP sensor origin.

| Zone | Name | Range | Phase |
|------|------|-------|-------|
| Zone 1 | Outer — Detection | 85 m | **Find / Fix** — RAT first detected; tracking begins |
| Zone 2 | Middle — Tracking | 60 m | **Track / Target** — continuous position updates; effector pre-aimed |
| Zone 3 | Central — Engagement | 30 m | **Engage** — operator authorized to fire; Engage button goes live |

### Network Nodes

| Node | Role |
|------|------|
| **DNN** (Distributed Networked Nodes) | Multi-modal sensor array (LiDAR, RF, Acoustic); detects and tracks RATs; reports position and health to FCP over UDP |
| **FCP** (Forward Command Post) | This system — command, display, analytics, engagement authorization |
| **DNE** (Distributed Networked Effector) | Ground-based laser effector; receives targeting data and fire commands from FCP |

### Mission Lifecycle

A mission **starts automatically** when the FCP application launches and **ends automatically** when the window is closed. All events are persisted to `fcp/data/analytics.db` and survive across sessions.

---

## 2. Interface Layout

**[OPERATOR]**

The FCP window is divided into four panels separated by adjustable splitters. All splitter positions are saved automatically on exit and restored on the next launch.

```
┌─────────────────────────┬─────────────────────────┐
│                         │                         │
│   VIDEO / CV TRACKING   │   ZONE MAP + NETWORK    │
│        (top-left)       │       (top-right)       │
│                         │                         │
├──────────────┬──────────┴──────────────────────── ┤
│              │                                    │
│   SENSORS +  │        F2T2EA ANALYTICS            │
│  ALERT LOG   │         (bottom-right)             │
│ (bottom-left)│                                    │
└──────────────┴────────────────────────────────────┘
```

| Panel | Location | Purpose |
|-------|----------|---------|
| **Video / CV Tracking** | Top-left | Live video feed with CV tracker overlay — shows target state, confidence, and lock reticle |
| **Zone Map + Network** | Top-right | Tactical zone fan showing RAT positions + node health topology |
| **Sensor Controls + Alert Log** | Bottom-left | LiDAR / RF / Acoustic toggles, Engage button, real-time alert feed |
| **F2T2EA Analytics** | Bottom-right | Mission database tables with CSV export |

Drag any splitter to resize panels. The layout is saved on close.

---

## 3. CV Launch Dialog

**[TECHNICAL]**

On startup, JAEGER presents a modal dialog requiring the operator to select a CV operating mode before the mission proceeds. The dialog cannot be dismissed without making a selection.

| Mode | Icon | Description | GPU Required |
|------|------|-------------|--------------|
| **Simulator** | ▶ | Scripted tracking on test video; simulates CV lock/confidence states on a scripted oval track | No |
| **Load Video + Real CV** | → | Browse for an `.mp4`, `.avi`, or `.mov` file; processed by the TensorRT tracking engine | Yes (NVIDIA + TensorRT) |
| **USB Camera + Real CV** | ◎ | Live webcam feed (device index 0) processed by the TensorRT tracking engine | Yes (NVIDIA + TensorRT) |

**Recommendation:** Use **Simulator** mode for all testing and development. Switch to Video or Camera mode only when a TensorRT-capable GPU is available and a trained model is loaded.

The selected mode can be switched mid-mission only by restarting the application.

---

## 4. Zone Map

**[OPERATOR]**

The Zone Map occupies the top-right panel and is divided vertically into two areas:

### Zone Fan (upper portion)

The zone fan is a quarter-circle tactical display showing the three detection zones and the live positions of all tracked RATs.

**Reading the zone fan:**

- **Zone 1 (outer)** — light blue arc at 85 m radius; RATs here have been detected
- **Zone 2 (middle)** — medium blue arc at 60 m; RATs here are being actively tracked and the effector is pre-aimed
- **Zone 3 (central)** — red arc at 30 m; RATs here are engagement-eligible

**RAT symbols:**

| Symbol | Meaning |
|--------|---------|
| Small dot with crosshair | Active RAT — tracked but not engaged |
| Larger highlighted dot | Engaged RAT — effector firing in progress |
| Strikethrough marker | Neutralized RAT — confirmed kill |

RAT position is expressed as azimuth and elevation relative to the FCP origin. The dot position within the fan represents the RAT's current azimuth bearing and zone depth.

### Network Topology Strip (lower portion)

The topology strip shows the three nodes in the network and their live status:

| Node (left → right) | Indicators |
|---------------------|-----------|
| **DNE** (Effector) | Online/offline status; laser firing indicator |
| **FCP** (Command Post, center) | Operator status |
| **DNN** (Detector) | Battery %, temperature (°C), error code, status flag |

Status flags: `OK` (normal), `WARNING` (threshold approaching), `ERROR` (threshold exceeded or node offline).

---

## 5. Sensor Management

**[OPERATOR]**

The three detection modalities are controlled from the Sensor Controls section in the bottom-left panel.

| Sensor | Button color when enabled | Button color when disabled |
|--------|--------------------------|---------------------------|
| **LiDAR** | Blue | Gray |
| **RF** | Blue | Gray |
| **Acoustic** | Blue | Gray |

Clicking a sensor toggle sends a `set_detection_mode` command to the DNN over UDP, enabling or disabling that modality on the sensor node. The visual state updates immediately to reflect the command sent.

All three sensors are **enabled by default** at mission start. Disabling a sensor reduces the DNN's detection capability for the affected modality. Sensor enable/disable events and durations are logged to the analytics database.

---

## 6. Target Tracking and Engagement

**[OPERATOR]**

### Detection and Zone Progression

When the DNN detects a new RAT, a detection event is logged and the RAT appears on the Zone Map. As the RAT closes distance, it transitions through zones:

```
Zone 1 (85 m) → Zone 2 (60 m) → Zone 3 (30 m) → Neutralized
   Detected       Tracking        Engagement
```

Each zone transition is logged with a timestamp to the analytics database.

### Primary Target Selection

JAEGER automatically selects a **primary target** for the DNE effector to track. Selection priority:

1. Keep the current Zone 3 target if it remains in Zone 3
2. Closest RAT in Zone 3 (if no current Zone 3 target is engaged)
3. Closest RAT in Zone 2 (if no Zone 3 targets present)
4. No target — effector stands by

The primary target changes only when the current target leaves Zone 3 or is neutralized. This prevents the effector from thrashing between targets.

### Engaging a RAT

The **Engage** button in the Sensor Controls section becomes active (green) when at least one RAT is in Zone 3.

- **Click Engage** — sends a fire command to the DNE effector and logs an `engage_commanded` event
- The button label changes to **Stop** while engagement is active
- **Click Stop** — cancels engagement; sends a stop-fire command to the DNE

**Engagement latch:** If Engage is pressed before the primary target has reached Zone 3, JAEGER latches the intent. The fire command is automatically sent the moment that target enters Zone 3, without requiring a second button press.

### Neutralization

A RAT is confirmed neutralized when the CV tracker maintains a continuous lock on the engaged target for **2 seconds** (accumulated on-target dwell time). On confirmation:

- A `neutralized` event is logged to the analytics database
- The RAT symbol on the Zone Map changes to the strikethrough marker
- An INFO alert is posted to the Alert Log
- The RAT is removed from the engaged set; a new primary target is selected if others remain

If the CV tracker loses lock before 2 seconds, the dwell counter resets and must accumulate from zero again.

---

## 7. Alert Log

**[OPERATOR]**

The Alert Log in the bottom-left panel provides a real-time timestamped feed of all significant mission events.

### Format

```
[HH:MM:SS]  [SEVERITY]  Message text
```

### Severity Levels

| Severity | Color | Examples |
|----------|-------|---------|
| **INFO** | Green | RAT detected, zone transition, sensor enabled/disabled, neutralization confirmed |
| **WARNING** | Yellow | DNN battery below 20%, DNN temperature above 70°C |
| **ERROR** | Red | DNN battery critical (below 10%), DNN offline, DNE offline, error code change |

The log auto-scrolls to the most recent entry. Alerts are de-duplicated — a threshold crossing fires one alert, not one per update cycle.

---

## 8. Analytics Panel

**[OPERATOR]**

The Analytics Panel in the bottom-right provides live mission data pulled from the SQLite analytics database. All tables auto-refresh every second.

### Tables

| Table | Contents |
|-------|---------|
| **Sensor Duration** | Total enabled/disabled time per modality (LiDAR, RF, Acoustic) |
| **RAT Detection Events** | All events per RAT: detected, zone_change, engage_commanded, engaged, neutralized, lost, CV lock |
| **Zone Timeline** | Zone progression history per RAT with entry timestamps |
| **Time-to-Engage** | Latency from first detection to Zone 3 entry to engagement for each RAT |
| **Neutralization Events** | Confirmed kills with RAT ID and timestamp |
| **Health Alert Timeline** | DNN battery, temperature, error code, and status flag threshold events |

### CSV Export

Each table has an **Export CSV** button. Click it to save the table contents to a `.csv` file via the system file-save dialog.

### Data Persistence

Mission data accumulates in `fcp/data/analytics.db` across sessions. Each run creates a new mission record. Historical data from previous missions is preserved and included in all table queries.

> To start with a clean database, delete `fcp/data/analytics.db` before launching. A new database is created automatically on the next launch.

---

## 9. Health Monitoring

**[OPERATOR / TECHNICAL]**

JAEGER continuously monitors the health of the DNN and DNE nodes.

### DNN Health (received via UDP health messages)

| Condition | Threshold | Alert Severity |
|-----------|-----------|---------------|
| Battery low | < 20% | WARNING |
| Battery critical | < 10% | ERROR |
| Temperature high | > 70°C | WARNING |
| Error code change | Any non-zero value | ERROR |
| Status flag change | Any change from previous | INFO / WARNING / ERROR (matches new flag) |
| DNN offline | No health message for 10 seconds | ERROR |

### DNE Health (monitored via serial/socket echo)

| Condition | Threshold | Alert Severity |
|-----------|-----------|---------------|
| DNE offline | No echo packet for 3 seconds | ERROR |
| DNE comes back online | Echo received after offline period | INFO |

### De-duplication

Health alerts fire **only on state change**, not on every polling cycle. For example, a battery level that stays below 20% for 5 minutes generates exactly one WARNING, not one per second.

---

## 10. Keyboard Shortcuts

**[OPERATOR]**

These shortcuts are active at all times except when a text input field has keyboard focus.

| Key | Action |
|-----|--------|
| `Space` | Pause / resume CV tracking |
| `R` | Reset CV tracking (clears current lock, returns to SEARCHING state) |
| `S` | Save a screenshot of the video frame to disk |
| `V` | Restart the video (Video mode only — rewinds to the beginning of the loaded file) |
| `Q` | Quit the application (triggers mission end and database close) |

---

## 11. Configuration Reference

**[TECHNICAL]**

All FCP configuration lives in `fcp/cfg/config.ini`. Changes take effect on the next application launch.

```ini
[DNN.recv.connection]
ip = 0.0.0.0        # Interface to listen on for DNN messages (0.0.0.0 = all interfaces)
port = 5000         # UDP port FCP listens on for positional and health messages from DNN

[DNN.send.connection]
ip = 127.0.0.1      # IP address of the DNN to send commands to
port = 5001         # UDP port DNN listens on for detection mode commands from FCP

[DNE.serial]
port = socket://localhost:6000  # Serial/TCP socket address of the DNE effector
baudrate = 9600                 # Baud rate for serial fallback (unused in socket mode)

[DNN.health.thresholds]
battery_low = 20.0       # Battery % below which a WARNING alert fires
battery_critical = 10.0  # Battery % below which an ERROR alert fires
temperature_high = 70.0  # Temperature (°C) above which a WARNING alert fires

[layout.sash]
vertical = 0.5           # Vertical splitter ratio (top/bottom panel height split, 0.0–1.0)
top_horizontal = 0.5     # Top row horizontal splitter ratio (video/map width split)
bot_horizontal = 0.5     # Bottom row horizontal splitter ratio (controls/analytics width split)
```

Splitter ratios are updated automatically by the application when the window is closed. To reset the layout to equal splits, set all three sash values to `0.5`.

### DNN Simulator Configuration

The DNN Simulator has its own config at `simulators/dnn_sim/cfg/config.ini`. Its receive/send ports must be the mirror image of the FCP config:

| Setting | DNN Sim | FCP |
|---------|---------|-----|
| Receives on | port 5001 | — |
| Sends to | port 5000 | — |

---

## 12. Troubleshooting

**[TECHNICAL]**

### FCP shows no RATs

1. Confirm the DNN Simulator is running: `poetry run python simulators/dnn_sim/dnn_sim_app.py`
2. Check that both apps are using matching ports — FCP listens on 5000, DNN sends to 5000
3. If running on separate machines, confirm `DNN.send.connection.ip` in the DNN Simulator's config points to the FCP's IP address, not `127.0.0.1`
4. Check the Alert Log for a "Failed to bind UDP listener" error at startup, which indicates port 5000 is already in use

### DNE shows offline

1. Confirm the DNE Simulator is running: `poetry run python simulators/dne_sim/dne_sim_app.py`
2. Verify the DNE Simulator is listening on `localhost:6000`
3. Check `fcp/cfg/config.ini` `[DNE.serial] port` value matches the simulator's listening address

### CV mode fails to start (Video or Camera mode)

1. TensorRT must be installed and a trained model must be present — check the CV engine logs in the terminal
2. Fall back to **Simulator** mode by restarting the FCP and selecting Simulator in the launch dialog
3. Simulator mode is fully functional for all FCP features except live CV inference

### `analytics.db` grows large or contains stale data

The SQLite database at `fcp/data/analytics.db` accumulates data from every mission run and is not automatically pruned.

To start fresh:
```bash
rm fcp/data/analytics.db
```
A new database is created automatically on the next launch. **Do not commit `analytics.db` to git** after test runs — it accumulates significant size from positional update events.

### Layout looks wrong on restart

If the splitter ratios saved in `config.ini` are corrupt or cause panels to collapse:

1. Open `fcp/cfg/config.ini`
2. Set all three sash values to `0.5`:
   ```ini
   [layout.sash]
   vertical = 0.5
   top_horizontal = 0.5
   bot_horizontal = 0.5
   ```
3. Relaunch the FCP

### Port already in use

If startup prints "Failed to bind UDP listener on 0.0.0.0:5000":
```bash
# Find the process using port 5000
sudo lsof -i :5000
# Kill it by PID
kill <pid>
```

### Application window doesn't open (WSL2)

WSL2 requires a working X11 display. Ensure an X server (e.g., VcXsrv, WSLg) is running and `DISPLAY` is set:
```bash
echo $DISPLAY   # should return :0 or similar
```
If blank, WSLg should handle this automatically on Windows 11. On Windows 10, install and launch VcXsrv and set `export DISPLAY=:0`.
