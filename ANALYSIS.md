# JAEGER Architectural Analysis

**Date:** 2026-03-25
**Scope:** Full repo, FCP deep-dive
**Analyst:** Claude Code

---

## Executive Summary

The FCP is a well-structured MVC Python/Tkinter application with a functional core (UDP receive, RAT display, sensor commanding, analytics DB). Several **critical bugs** exist — most importantly, direct Tkinter widget mutation from a background thread and a UDP listener that permanently dies on a single bad packet. Three SOW requirements for the FCP have no implementation at all, and two more are only partially met.

---

## Checkpoint 1 — MVC Architecture

**Status: ✓ Fixed**

The MVC separation is largely clean. The controller correctly owns communication logic and bridges model ↔ view.

Previously, `fcp_controller.py` and `dnn_sim_controller.py` called Tkinter widget methods directly from background threads. All cross-thread view calls have been wrapped in `self.view.after(0, lambda: ...)` to schedule them on the main event loop:

- [fcp_controller.py](fcp/controller/fcp_controller.py) — `update_rat()` and `update_dnn_node()` now use `after(0, ...)`
- [dnn_sim_controller.py](simulators/dnn_sim/controller/dnn_sim_controller.py) — RAT frame update, `recv_data_frame`, `sent_data_frame`, and `handle_command()` now use `after(0, ...)`

**Recommendation:** None remaining.

---

## Checkpoint 2 — Threading & Concurrency

**Status: ✓ Fixed**

| Location | Issue | Severity | Resolution |
|---|---|---|---|
| [fcp_controller.py](fcp/controller/fcp_controller.py) | `_listen_loop` mutated Tkinter widgets directly | High | ✓ Fixed — all calls use `after(0, ...)` |
| [fcp_controller.py](fcp/controller/fcp_controller.py) | `except Exception: break` — one bad packet killed listener permanently | Critical | ✓ Fixed — changed to `continue` |
| [dnn_sim_controller.py](simulators/dnn_sim/controller/dnn_sim_controller.py) | RAT update loop mutated Tkinter widgets directly | High | ✓ Fixed — all calls use `after(0, ...)` |
| [dnn_sim_controller.py](simulators/dnn_sim/controller/dnn_sim_controller.py) | Same `break` on exception pattern in DNN sim listener | High | ✓ Fixed — changed to `continue` |
| [fcp_model.py](fcp/model/fcp_model.py) | `rats` dict written from listener thread, `remove_rat()` compound check-then-delete not atomic | Low | ✓ Fixed — `threading.Lock` added in `__post_init__`; `update_rat` and `remove_rat` both acquire it |

**Recommendation:** None remaining.

---

## Checkpoint 3 — UDP Communication Protocol

**Status: ✓ Fixed (two gaps resolved; two low-priority gaps remain)**

- Buffer size 65535 is correct (max UDP payload ≈65507 bytes).
- Port assignments are consistent: FCP recv=5000 matches DNN sim send=5000; FCP send=5001 matches DNN sim recv=5001. ✓
- **No schema validation.** If a packet arrives with valid JSON but missing `msg_type`, it is silently ignored. If JSON is malformed, an exception is raised and (per Checkpoint 2) the listener continues. Low-priority.
- **No sequence numbering.** Out-of-order or duplicate packets are indistinguishable. Low-priority.
- `_send_detection_command` opens a new UDP socket per command and closes it — fine for infrequent commands.

**Standalone sim incompatibility:** ✓ Fixed — [dnn_pos_sim.py](simulators/fcp/dnn_pos_sim.py) now includes `msg_type: 'positional'` and a `zone` field (derived from `range_value` against SOW zone thresholds: ≤30m=3, ≤60m=2, ≤85m=1, else 0) in every packet. Port default corrected from `"100"` to `"5000"`.

**Staleness handling:** ✓ Fixed — `FCPController._check_staleness()` ([fcp_controller.py](fcp/controller/fcp_controller.py)) runs every 5 seconds on the main thread via `view.after()`. RATs not updated within 10 seconds are removed from the model, their `RatFrame` widget is destroyed, and a `'lost'` event is logged to the analytics DB.

**Recommendation:** None remaining for C3.

---

## Checkpoint 4 — Data Models

**Status: OK (with minor notes)**

- Both `Rat` ([fcp/model/rat_model.py](fcp/model/rat_model.py)) and `DNNSimRat` ([simulators/dnn_sim/model/dnn_sim_rat_model.py](simulators/dnn_sim/model/dnn_sim_rat_model.py)) have the same 8 fields. `DNNSimRat.to_message()` produces exactly the structure `Rat.__init__` expects. **Schemas are in sync.** ✓
- `Rat` is declared `@dataclass` but overrides `__init__` with a dict-parsing constructor — the dataclass decorator adds no value here and could confuse readers. Minor.
- ~~**Type inconsistency:** [rat_model.py:18](fcp/model/rat_model.py#L18) — `self.zone = data.get('zone', '')` defaults to empty string `''` if zone is absent. The field is typed `int`. This will cause `zone_value.set('')` to raise a Tkinter `ValueError` (IntVar cannot hold a string).~~ ✓ **Fixed** — default changed to `0`.
- `Node` model correctly uses `health.get(...)` with numeric defaults. ✓
- Zone semantics: zones 1 (outer, 85m), 2 (middle, 60m), 3 (central/engagement, 30m) per SOW §1.2. Only `zone == 3` enables the engage button — correct.

**Recommendation:** ~~Fix `zone` default from `''` to `0` in [rat_model.py:18](fcp/model/rat_model.py#L18).~~ ✓ Fixed.

---

## Checkpoint 5 — SQLite Analytics Layer

**Status: OK (with one gap)**

- WAL mode enabled — safe for concurrent reads from main thread while background thread writes. ✓
- All SQL uses parameterized `?` placeholders — **no SQL injection risk.** ✓
- Single persistent connection with `check_same_thread=False` — background thread writes directly. With WAL this is low-risk but technically a threading concern. A write lock would be cleaner.
- `get_sensor_durations()` sorts by `event_time ASC` as ISO-8601 strings — correct for UTC timestamps. ✓
- `get_time_to_engage()` tracks detect→zone3→engage timing — this is the primary F2T2EA metric. ✓
- **`analytics.db` is NOT in `.gitignore`.** The SQLite file at `fcp/data/analytics.db` accumulates mission data and will be committed to git history as a growing binary blob.

**Recommendation:** Add `*.db` (or `fcp/data/*.db`) to `.gitignore`.

---

## Checkpoint 6 — GUI Design & Completeness

**Status: Partial**

All 7 frame classes exist and are wired. Individual assessments:

| Frame | Status | Notes |
|---|---|---|
| `VideoFrame` | ✓ OK | OpenCV+Pillow, `after()` scheduling, resource cleanup on stop |
| `AlertFrame` | Gap | Only logs sensor mode changes; no alerts on RAT detection, no alerts for node fault/power/signal |
| `ControlFrame` | Risk | `update_rat()` called from background thread (thread-unsafe) |
| `MapFrame` / `NodeFrame` | Gap | Displays health numbers only (battery%, temp, error, status). SOW 3.4 requires a network topology map with node **locations** and **links** — not present |
| `RatFrame` | ✓ OK | Zone→engage button logic correct; engage button enabled at zone==3 |
| `AnalyticsFrame` | Partial | Sensor usage and detect-to-engage tables live; 4 sections stub pending Effector integration |

**Recommendation:** See SOW gaps below.

---

## Checkpoint 7 — Configuration Management

**Status: OK**

- No hardcoded IPs or ports found in FCP or DNN sim Python source. All config read from INI files. ✓
- No startup validation — if `config.ini` is missing or malformed, `configparser` silently returns empty values and the socket bind will fail (with a caught exception that prints a message but doesn't abort the app). Acceptable for now.
- `.env` is used only by `dnn_pos_sim.py` — inconsistency with the INI approach used everywhere else. Low priority.
- Default port in `dnn_pos_sim.py` UI is `"100"` ([dnn_pos_sim.py:175](simulators/fcp/dnn_pos_sim.py#L175)) — clearly a placeholder that will fail to route to anything. Should default to `5000`.

---

## Checkpoint 8 — Detectors Integration Boundary

**Status: Gap / Stub**

- [DNN_Wrapper.m](Detectors/DNN_Wrapper.m) is a 14-line stub. It generates a placeholder `currentMode` time series and has a comment "Unpack a json string from FCP" — not implemented. No UDP sending, no Simulink model invocation.
- `Detectors/src/` and `Detectors/tests/` are empty.
- The Python codebase has no code path that expects to communicate with real MATLAB hardware — the DNN simulator is the current full substitute.
- SOW §1.5 requires optical, passive RF, acoustic, and ultrasonic detection modes. The DNN simulator mocks this with random data; actual sensor integration is entirely pending.

**Recommendation:** This is a known implementation gap. The MATLAB integration path needs a UDP-sending component in `Detectors/src/` that speaks the same positional message format as `DNNSimRat.to_message()`.

---

## Checkpoint 9 — Effectors Gap

**Status: ✓ Fixed (simulator added; analytics stubs still pending)**

- `FCPController.engage_rat()` ([fcp_controller.py](fcp/controller/fcp_controller.py)) now sends a binary targeting command to the DNE over serial and adds the RAT to `model.engaged_rats`.
- **DNE simulator** added at [simulators/dne_sim/](simulators/dne_sim/) — MVC app mirroring the DNN sim. Displays received targeting data, exposes clickable toggles for `am_i_healthy` and `laser_firing`.
- **Serial protocol** (little-endian binary, no framing):
  - FCP → DNE: 26 bytes — `<6f2B` (az, el, range, az_rate, el_rate, range_rate, fire, state_command)
  - DNE → FCP: 2 bytes — `<2B` (am_i_healthy, laser_firing)
- FCP sends targeting data on every positional update for RATs in zone ≥ 2 (`fire=0, state_cmd=1`). Engage sets `fire=1, state_cmd=2`.
- DNE health responses update the FCP `MapFrame` DNE status panel and trigger an alert on unhealthy reports.
- For simulation: DNE sim acts as a TCP server; FCP connects via `pyserial serial_for_url("socket://localhost:6000")`. Switch to hardware by changing `fcp/cfg/config.ini` `[DNE.serial] port` to `/dev/ttyUSB0`.
- The 4 analytics stub sections remain pending (require engagement outcome data from a real/simulated DNE to populate).

**Recommendation:** Populate analytics stubs once engagement outcome feedback is defined.

---

## Checkpoint 10 — Dependency & Build Health

**Status: OK (minor gaps)**

- Dependencies correctly pinned with ranges: Pillow ≥12.1, OpenCV ≥4.13, NumPy ≥2.4, python-dotenv ≥1.2. ✓
- `tkinter` and `sqlite3` correctly absent from pyproject (system packages). ✓
- **No test dependencies, no pytest setup.** Zero automated tests exist anywhere in the repo.
- MATLAB/Simulink is outside Poetry — requires a separately-installed MATLAB license. No documentation for this dependency in README.
- `poetry run` must be executed from the repo root since imports use relative package names (e.g., `from model.fcp_model import FCPModel`) — no `sys.path` manipulation or proper packaging. Works fine given `package-mode = false`.

---

## FCP Deep Dives

### 1. Detect-and-Display Latency Path

```
UDP packet arrives
  → _listen_loop (background thread)
    → json.loads()
    → Rat(data_dict)           # ~0ms
    → _handle_rat_analytics()  # DB write (synchronous, ~1-5ms)
    → model.update_rat()       # dict write
    → view.after(0, lambda: view.control_frame.update_rat(rat))  # ✓ scheduled on main thread
      → RatFrame widgets updated (zone, az, el, range, rates)
```

**No buffering, no polling delay.** Display update is scheduled on the main event loop via `after(0, ...)` — one event-loop tick of latency (typically <1ms) added but now thread-safe. The DB write remains the dominant latency source at ~1-5ms. Well within the SOW 2000ms zone-update requirement.

### 2. Mission Lifecycle

- **Start:** Automatic on app launch — `FCPApp.__init__` calls `analytics_db.start_mission()` ([fcp_app.py:20](fcp/fcp_app.py#L20)).
- **Initial sensor events:** All three sensors logged as 'enabled' at mission start ([fcp_app.py:23-25](fcp/fcp_app.py#L23)).
- **End:** `_on_close()` calls `end_mission()` then `close()` on window close ([fcp_app.py:42-45](fcp/fcp_app.py#L42)).
- **No manual mission control.** No "Start Mission" / "End Mission" UI. Every app launch = new mission row in DB.
- The thread-safety crash risk has been resolved; however a force-kill (SIGKILL, power loss) still leaves an open mission row.

### 3. Detection Mode Command Flow

```
User clicks LiDAR label in ControlFrame
  → update_lidar_checkbutton()         [control_frame.py:50]
    → controller.set_lidar_enabled()   [fcp_controller.py:106]
      → model.set_lidar_enabled()      # state update
      → alert_frame.add_alert()        # UI feedback
      → analytics_db.log_sensor_event() # persistence
      → _send_detection_command('lidar', enabled)
        → new UDP socket → sendto(port 5001) → close socket
          → DNN sim _listen_loop receives on port 5001
            → view.after(0, lambda: handle_command())  [dnn_sim_controller.py]  ✓ Fixed
              → model.set_lidar_enabled()
              → view.mode_frame.set_lidar_enabled()
```

**No acknowledgment.** The FCP has no confirmation that the command was received. If the DNN is offline, the command silently disappears. The FCP model state diverges from the DNN model state.

### 4. Stale Target Handling

**✓ Fixed.** `FCPController._check_staleness()` runs every 5 seconds on the main thread. Any RAT whose last positional update is older than 10 seconds is removed from the model (`FCPModel.remove_rat()`), its `RatFrame` widget is destroyed (`ControlFrame.remove_rat()`), and a `'lost'` event is logged to the analytics DB. Last-seen timestamps are updated in `_listen_loop` each time a `positional` packet is processed.

### 5. Alert Frame Logic

Only **sensor mode toggle** events trigger alerts. Nothing else does:
- New RAT detected: no alert
- RAT enters zone 3: no alert
- Node battery low: no alert
- Node error code non-zero: no alert
- Node status WARNING/ERROR: no alert

The `AlertFrame` is a append-only `ScrolledText` with no severity model, no categories, no timestamps. SOW §3.5 specifically requires alerts for "fault or failure" and "signal and power levels." Node health data (battery%, error_code, status_flag) is received and displayed in `NodeFrame` but never evaluated for alert conditions.

**Recommendation:** Add alert trigger logic in `update_dnn_node()` (or the controller's health processing path): alert on `status_flag != 'OK'`, `battery_percent < threshold`, `error_code != 0`. Add RAT detection alerts. Add timestamps to alert messages.

---

## SOW Requirements Traceability (FCP — Section 3)

| Req | Description | Status | Evidence |
|---|---|---|---|
| 3.1 | Real-time video ≥30fps | ✓ Met | `video_frame.py`, default 30fps |
| 3.2 | Computer vision tracking confidence ≥30fps | ✗ Not started | No CV overlay, no confidence data in protocol |
| 3.3 | F2T2EA performance metrics post-mission | Partial | Sensor usage + detect-to-engage live; 4 effector metrics are stubs |
| 3.4 | Node network map (health, status, location, links) ≤1000ms | Partial | Health/status displayed; no topology, no node locations, no links |
| 3.5 | Alerts for fault/failure, signal/power ≤5000ms | Partial | Only sensor mode changes alerted; no node fault/power alerts |
| 3.6 | Power (120VAC) | N/A | Hardware requirement |
| 3.7 | Commanding the Ground-Based Defense Network | ✓ Met | Detection mode commands over UDP |

### Critical unimplemented FCP requirements:
1. **3.2 Computer vision / tracking confidence** — requires either (a) DNN to include a confidence field in positional messages and FCP to render it, or (b) an on-FCP CV overlay on the video feed.
2. **3.4 Network topology map** — the `MapFrame` needs to become a canvas-based node graph showing node positions, the FCP position, and link lines. The DNN protocol needs to include node location data.
3. **3.5 Node fault/power alerts** — straightforward: evaluate received `Node` health in the controller and call `alert_frame.add_alert()` on threshold violations.

---

## Summary of Findings

| # | Area | Status | Priority |
|---|---|---|---|
| C1 | MVC separation | ✓ Fixed — all cross-thread view calls use `after(0, ...)` | — |
| C2 | Threading | ✓ Fixed — `continue` on exception; all Tkinter calls thread-safe; `rats` dict lock added | — |
| C3 | UDP protocol | ✓ Fixed — standalone sim now sends `msg_type`/`zone`; staleness timer added | — |
| C4 | Data models | ✓ Fixed — zone default corrected to `0` | — |
| C5 | SQLite analytics | ✓ Fixed — `analytics.db` added to gitignore | — |
| C6 | GUI completeness | Partial — MapFrame and AlertFrame under-implemented | High |
| C7 | Config management | ✓ Fixed — standalone sim port default corrected to 5000 | — |
| C8 | Detectors boundary | Stub — MATLAB wrapper not implemented | Medium (not FCP) |
| C9 | Effectors gap | ✓ Fixed — DNE sim + serial integration; engage_rat() sends fire command | — |
| C10 | Build health | OK — no tests | Medium |
| D1 | Latency path | ✓ Fixed — thread-safe, one `after()` tick added (~<1ms) | — |
| D2 | Mission lifecycle | Gap — force-kill leaves open mission row | Medium |
| D3 | Command flow | Partial — `handle_command()` now runs on main thread; no ACK | Medium |
| C9/D | DNE integration | ✓ Fixed — binary serial protocol; DNE sim at `simulators/dne_sim/`; FCP MapFrame shows DNE status | — |
| D4 | Stale targets | ✓ Fixed — `_check_staleness()` removes RATs after 10s; logs `'lost'` event | — |
| D5 | Alert logic | Gap — only sensor modes alerted; SOW 3.5 not met | High |

### Immediate action items (before any demo):
1. ~~Fix `break` → `continue` in both UDP listener loops~~ ✓ Done
2. ~~Wrap cross-thread view calls in `after(0, ...)`~~ ✓ Done
3. ~~Fix `zone` default from `''` to `0` in `rat_model.py`~~ ✓ Done
4. ~~Add `*.db` to `.gitignore`~~ ✓ Done
5. ~~Fix standalone sim to include `msg_type` and `zone` fields~~ ✓ Done
6. ~~Implement stale target removal~~ ✓ Done

### Pre-demo implementation gaps (SOW compliance):
7. SOW 3.2: Add tracking confidence to protocol and display
8. ~~SOW 3.4: Build topology map in `MapFrame`~~
9. ~~SOW 3.5: Add node health alert triggers~~
10. SOW 3.3/C9: Implement effector command and populate analytics stubs
