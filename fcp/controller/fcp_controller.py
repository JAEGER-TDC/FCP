import os
import socket
import threading
import json
import time

import serial

from model.fcp_model import FCPModel
from model.rat_model import Rat
from model.node_model import Node
from view.fcp_view import FCPView
from protocol.dne_target import Target, DNEHealth, PacketReceiver, make_packet
from view.frames.alert_frame import INFO, WARNING, ERROR
from cv.cv_engine import CVEngine
from cv.cv_engine_sim import CVEngineSimulator
from cv.hit_confirm import HitConfirmEngine


class FCPController:
    def __init__(self, model: FCPModel, view: FCPView):
        self.model = model
        self.view = view

        self.config = self.read_config(os.path.join(os.path.dirname(__file__), '..', 'cfg', 'config.ini'))

        self.dnn_recv_ip = self.config['DNN.recv.connection']['ip']
        self.dnn_recv_port = self.config['DNN.recv.connection'].getint('port')

        self.dnn_send_ip = self.config['DNN.send.connection']['ip']
        self.dnn_send_port = self.config['DNN.send.connection'].getint('port')

        self.dne_port = self.config['DNE.serial']['port']
        self.dne_baud = self.config['DNE.serial'].getint('baudrate')

        # Track which RATs have already received a 'detected' log so we only
        # emit it once per mission, and track last-known zone per RAT so we
        # only log zone_change when the zone actually changes.
        self._known_rats: set[str] = set()
        self._rat_zones: dict[str, int] = {}
        self._rat_last_seen: dict[str, float] = {}

        self._ser: serial.SerialBase | None = None
        self._ser_lock = threading.Lock()

        # CV engine — set by start_mode_* after CVLaunchDialog selection
        self.cv_engine   = None
        self._cv_cfg_path = os.path.join(os.path.dirname(__file__), '..', 'cfg', 'config.ini')

        # Hit confirmation — active while a RAT is engaged
        self._hit_confirm: HitConfirmEngine | None = None

        # Per-RAT accumulated on-target dwell seconds; reset when off-target or lock lost
        self._engage_dwell: dict[str, float] = {}

        self._start_udp_listener()
        self._start_dne_serial()
        self.view.after(5000, self._check_staleness)
        self.view.after(500, self._poll_cv_state)

        _th = self.config['DNN.health.thresholds']
        self._thresh_battery_low      = _th.getfloat('battery_low',      20.0)
        self._thresh_battery_critical = _th.getfloat('battery_critical',  10.0)
        self._thresh_temperature_high = _th.getfloat('temperature_high',  70.0)

        self._dnn_last_health_time: float | None = None
        self._dnn_health_silence_threshold = 10.0  # 10× the 1 Hz health rate
        self._dnn_offline_alerted: bool = False

    #===================================================================

    def read_config(self, config_file):
        import configparser
        config = configparser.ConfigParser()
        config.read(config_file)
        return config

    #===================================================================

    def _start_udp_listener(self):
        print(f"Trying to bind UDP listener on {self.dnn_recv_ip}:{self.dnn_recv_port}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.dnn_recv_ip, self.dnn_recv_port))
            print("UDP listener successfully bound")
        except Exception as e:
            print(f"Failed to bind UDP listener on {self.dnn_recv_ip}:{self.dnn_recv_port}: {e}")
            return

        def _listen_loop(s):
            while True:
                try:
                    data, addr = s.recvfrom(65535)
                    data_dict = json.loads(data.decode('utf-8'))

                    if data_dict.get('msg_type') == 'positional':
                        rat = Rat(data_dict)
                        self._handle_rat_analytics(rat, data_dict.get('current_time'))
                        self.model.update_rat(rat)
                        self._rat_last_seen[rat.rat_id] = time.time()
                        zone_counts = {z: sum(1 for rt in self.model.rats.values() if rt.zone == z)
                                       for z in (1, 2, 3)}
                        any_z3 = zone_counts.get(3, 0) > 0

                        # Check pending engagement latch before selecting primary
                        pending = self.model.pending_engage_rat_id
                        if pending and rat.rat_id == pending and rat.zone == 3:
                            self.engage_rat(pending)
                            self.model.pending_engage_rat_id = None

                        primary_id = self._select_primary_target()
                        self.model.primary_target_id = primary_id

                        def _rat_update(zc=zone_counts, rs=dict(self.model.rats), az3=any_z3,
                                        pid=primary_id, er=set(self.model.engaged_rats)):
                            self.view.control_frame.update_engage_state(az3)
                            self.view.control_frame.update_engagement_active(bool(er))
                            self.view.map_frame.update_zone_counts(zc, rs)
                            self.view.map_frame.update_engagement_state(pid, er)
                        self.view.after(0, _rat_update)

                        # Send targeting data to DNE for primary target only
                        if primary_id and primary_id in self.model.rats:
                            primary_rat = self.model.rats[primary_id]
                            if primary_rat.zone >= 2:
                                fire = 1 if primary_id in self.model.engaged_rats else 0
                                state_cmd = 3 if fire else 2
                                self._send_dne_targeting(primary_rat, fire=fire, state_command=state_cmd)

                    if data_dict.get('msg_type') == 'health':
                        node = Node(data_dict)
                        self._dnn_last_health_time = time.time()
                        self._dnn_offline_alerted = False
                        self.view.after(0, lambda n=node: self.view.map_frame.update_dnn_node(n))
                        self._evaluate_node_health_alerts(node)

                except Exception as e:
                    import traceback
                    print(f"UDP listener error: {e}")
                    traceback.print_exc()
                    continue

        t = threading.Thread(target=_listen_loop, args=(sock,), daemon=True)
        t.start()

    #===================================================================

    def _start_dne_serial(self):
        print(f"Connecting to DNE on {self.dne_port}")
        try:
            self._ser = serial.serial_for_url(self.dne_port, baudrate=self.dne_baud, timeout=1.0)
            print("DNE serial connection established")
        except Exception as e:
            print(f"Failed to connect to DNE on {self.dne_port}: {e}")
            self._ser = None
            return

        _DNE_HEALTH_TIMEOUT = 3.0  # seconds without an echo → declare unhealthy

        def _dne_listen_loop(ser):
            receiver = PacketReceiver()
            last_echo = time.time()
            while True:
                try:
                    byte = ser.read(1)  # returns b'' on the 1-second serial timeout
                    if not byte:
                        # No data — check if the DNE has gone silent
                        if self.model.dne_healthy and (time.time() - last_echo > _DNE_HEALTH_TIMEOUT):
                            self.model.dne_healthy = False
                            self.model.dne_laser_firing = False
                            self.view.after(0, lambda: self.view.map_frame.update_dne_status(False, False))
                            self.view.after(0, lambda: self.view.alert_frame.add_alert(
                                'DNE effector offline or unresponsive', ERROR))
                        continue
                    result = receiver.process_byte(byte[0])
                    if result is not None and isinstance(result, DNEHealth):
                        last_echo = time.time()
                        laser = bool(result.laser_firing)
                        was_unhealthy = not self.model.dne_healthy
                        self.model.dne_healthy = True
                        self.model.dne_laser_firing = laser
                        self.view.after(0, lambda l=laser: self.view.map_frame.update_dne_status(True, l))
                        if was_unhealthy:
                            self.view.after(0, lambda: self.view.alert_frame.add_alert(
                                'DNE effector reconnected', INFO))
                except Exception as e:
                    print(f"DNE serial listener error: {e}")
                    continue

        t = threading.Thread(target=_dne_listen_loop, args=(self._ser,), daemon=True)
        t.start()

    #===================================================================

    def _send_dne_targeting(self, rat: Rat, fire: int = 0, state_command: int = 2,
                            hit_confirmation: int = 0):
        if self._ser is None:
            return
        try:
            t = Target(
                rat.az_value, rat.el_value, rat.range_value,
                rat.az_rate, rat.el_rate, rat.range_rate,
                fire, state_command,
                hit_confirmation=hit_confirmation,
                time=time.time_ns() // 1000,
            )
            with self._ser_lock:
                self._ser.write(make_packet(t))
        except Exception as e:
            print(f"Failed to send DNE targeting: {e}")

    #===================================================================

    _ZONE_LABELS = {1: 'outer (detection)', 2: 'middle (tracking)', 3: 'central (engagement)'}

    def _handle_rat_analytics(self, rat: Rat, msg_timestamp: str | None):
        """Log first-detection and zone-change events to the analytics DB."""
        db = self.model.analytics_db

        if rat.rat_id not in self._known_rats:
            self._known_rats.add(rat.rat_id)
            db.log_rat_event(
                rat.rat_id, 'detected',
                zone=rat.zone,
                az=rat.az_value, el=rat.el_value, range_m=rat.range_value,
                timestamp=msg_timestamp,
            )
            self._rat_zones[rat.rat_id] = rat.zone
            zone_label = self._ZONE_LABELS.get(rat.zone, f'zone {rat.zone}')
            self.view.after(0, lambda m=f'RAT {rat.rat_id} detected — {zone_label}': self.view.alert_frame.add_alert(m, WARNING))
        elif rat.zone != self._rat_zones.get(rat.rat_id):
            prev_zone = self._rat_zones.get(rat.rat_id, 0)
            self._rat_zones[rat.rat_id] = rat.zone
            db.log_rat_event(
                rat.rat_id, 'zone_change',
                zone=rat.zone,
                az=rat.az_value, el=rat.el_value, range_m=rat.range_value,
                timestamp=msg_timestamp,
            )
            zone_label = self._ZONE_LABELS.get(rat.zone, f'zone {rat.zone}')
            if rat.zone > prev_zone:
                sev = WARNING
                msg = f'RAT {rat.rat_id} entered {zone_label}'
            else:
                sev = INFO
                msg = f'RAT {rat.rat_id} withdrew to {zone_label}'
            self.view.after(0, lambda m=msg, s=sev: self.view.alert_frame.add_alert(m, s))

            # Auto-disengage when an engaged RAT drops below zone 3
            if prev_zone == 3 and rat.zone < 3 and rat.rat_id in self.model.engaged_rats:
                self.model.engaged_rats.discard(rat.rat_id)
                db.log_rat_event(rat.rat_id, 'disengage_zone_exit')
                self.view.after(0, lambda i=rat.rat_id: self.view.alert_frame.add_alert(
                    f'RAT {i} disengaged — exited zone 3', INFO))

    #===================================================================

    def _select_primary_target(self) -> str | None:
        """Select the single RAT the DNE should track.

        Priority: sticky current zone-3 target → closest zone-3 RAT →
        closest zone-2 RAT → None.
        """
        rats = {rid: r for rid, r in self.model.rats.items()
                if rid not in self.model.neutralized_rats}
        current = self.model.primary_target_id
        if current and current in rats and rats[current].zone == 3:
            return current
        z3 = [r for r in rats.values() if r.zone == 3]
        if z3:
            return min(z3, key=lambda r: r.range_value).rat_id
        z2 = [r for r in rats.values() if r.zone == 2]
        if z2:
            return min(z2, key=lambda r: r.range_value).rat_id
        return None

    #===================================================================

    def _evaluate_node_health_alerts(self, node: Node):
        """Evaluate DNN health thresholds and fire alerts on state changes.
        Called from the UDP listener thread — all view access via view.after()."""
        prev = self.model.dnn_node_prev
        if prev is None:
            # First message: establish baseline, no alerts.
            self.model.dnn_node_prev = {
                'battery_percent': node.battery_percent,
                'temperature_c':   node.temperature_c,
                'error_code':      node.error_code,
                'status_flag':     node.status_flag,
            }
            return

        alerts = []

        # Battery (check CRITICAL first to avoid double-firing)
        prev_bat, curr_bat = prev['battery_percent'], node.battery_percent
        if curr_bat < self._thresh_battery_critical and prev_bat >= self._thresh_battery_critical:
            alerts.append((
                f'DNN battery CRITICAL: {curr_bat:.1f}% (threshold {self._thresh_battery_critical:.0f}%)',
                ERROR,
            ))
        elif curr_bat < self._thresh_battery_low and prev_bat >= self._thresh_battery_low:
            alerts.append((
                f'DNN battery LOW: {curr_bat:.1f}% (threshold {self._thresh_battery_low:.0f}%)',
                WARNING,
            ))

        # Temperature
        prev_temp, curr_temp = prev['temperature_c'], node.temperature_c
        if curr_temp > self._thresh_temperature_high and prev_temp <= self._thresh_temperature_high:
            alerts.append((
                f'DNN temperature HIGH: {curr_temp:.1f}°C (threshold {self._thresh_temperature_high:.0f}°C)',
                WARNING,
            ))

        # Error code
        prev_err, curr_err = prev['error_code'], node.error_code
        if curr_err != 0 and prev_err == 0:
            alerts.append((f'DNN fault: error code {curr_err}', ERROR))
        elif curr_err == 0 and prev_err != 0:
            alerts.append((f'DNN fault cleared (was error code {prev_err})', INFO))

        # Status flag
        prev_flag, curr_flag = prev['status_flag'], node.status_flag
        if curr_flag != prev_flag:
            if curr_flag == 'ERROR':
                alerts.append((f'DNN status: {prev_flag} → {curr_flag}', ERROR))
            elif curr_flag == 'WARNING':
                alerts.append((f'DNN status: {prev_flag} → {curr_flag}', WARNING))
            else:
                alerts.append((f'DNN status recovered: {prev_flag} → {curr_flag}', INFO))

        self.model.dnn_node_prev = {
            'battery_percent': node.battery_percent,
            'temperature_c':   node.temperature_c,
            'error_code':      node.error_code,
            'status_flag':     node.status_flag,
        }

        for msg, sev in alerts:
            self.view.after(0, lambda m=msg, s=sev: self.view.alert_frame.add_alert(m, s))

    #===================================================================

    _ENGAGE_DWELL_S = 2.0   # seconds of continuous on-target required for a confirmed kill

    def _poll_cv_state(self):
        """Poll the CV engine metadata every 100 ms, update model, fire state-change alerts."""
        if self.cv_engine is None:
            self.view.after(100, self._poll_cv_state)
            return

        err = getattr(self.cv_engine, 'get_error', lambda: None)()
        if err:
            self.view.alert_frame.add_alert(
                f'CV engine error: {err} — switching to simulator', WARNING)
            _default = os.path.join(os.path.dirname(__file__), '..', 'assets', 'RAT-CV-1.mp4')
            _video = getattr(self.cv_engine, '_video_path', None) or _default
            if not _video:  # camera mode has no video path — use default
                _video = _default
            self.cv_engine = CVEngineSimulator(video_path=_video)
            self.view.video_frame.play_cv_engine(self.cv_engine)
            self.view.after(100, self._poll_cv_state)
            return

        meta       = self.cv_engine.get_metadata()
        new_state  = meta['state']
        prev_state = self.model.cv_state

        self.model.cv_state       = new_state
        self.model.cv_confidence  = meta['confidence']
        self.view.video_frame.update_cv_status(new_state, meta['confidence'])
        self.view.video_frame.update_hud_data(meta)
        self.model.cv_centroid    = (meta['cx'], meta['cy'])
        self.model.cv_frame_size  = (meta['frame_w'], meta['frame_h'])
        self.model.cv_last_update = time.time()

        if new_state != prev_state:
            _SEV = {'LOCKED': INFO, 'DARK LOCK': INFO, 'PREDICTING': WARNING, 'SEARCHING': WARNING}
            self.view.alert_frame.add_alert(
                f'CV tracker: {prev_state} → {new_state}',
                _SEV.get(new_state, INFO))

        # Log CV confidence each time tracker acquires LOCKED state (immediate, not debounced)
        if new_state == 'LOCKED' and prev_state != 'LOCKED':
            self.model.analytics_db.log_rat_event(
                'CV_SYSTEM', 'cv_lock', confidence=meta['confidence'])

        # Dwell-based kill confirmation: accumulate on-target time per engaged RAT
        on_target = meta.get('on_target', False)
        for rat_id in list(self.model.engaged_rats):
            if on_target and new_state == 'LOCKED':
                self._engage_dwell[rat_id] = self._engage_dwell.get(rat_id, 0.0) + 0.1
                if self._engage_dwell[rat_id] >= self._ENGAGE_DWELL_S:
                    self._neutralize_rat(rat_id)
            else:
                self._engage_dwell[rat_id] = 0.0   # reset if off-target or lock lost

        # Visual hit confirmation: scan raw frame for green laser dot on drone body
        if self._hit_confirm is not None and self.model.engaged_rats:
            raw_frame = self.cv_engine.get_raw_frame()
            if raw_frame is not None and new_state in ('LOCKED', 'DARK LOCK'):
                confirmed, conf = self._hit_confirm.update(
                    raw_frame,
                    meta['cx'], meta['cy'],
                    meta.get('bbox_w', 0), meta.get('bbox_h', 0),
                )
                if confirmed:
                    rat_id = next(iter(self.model.engaged_rats), 'UNK')
                    self.view.alert_frame.add_alert(
                        f'HIT CONFIRMED — green laser detected on RAT-{rat_id} (conf {conf:.2f})',
                        ERROR)
                    self.model.analytics_db.log_rat_event(
                        rat_id, 'hit_visual_confirmed', confidence=conf)
                    self._hit_confirm.reset()   # reset so it can re-confirm on next hit
            elif new_state == 'SEARCHING':
                self._hit_confirm.reset()

        self.view.after(100, self._poll_cv_state)   # reschedule

    # ── CV mode entry points (called by CVLaunchDialog and Load Video button) ──

    def _load_cv_tuning(self, cfg) -> None:
        """Apply any saved [cv.tuning] values from config.ini onto cfg."""
        import configparser as _cp
        parser = _cp.ConfigParser()
        parser.read(self._cv_cfg_path)
        if not parser.has_section('cv.tuning'):
            return
        sect = parser['cv.tuning']
        for key, raw in sect.items():
            attr = next((a for a in dir(cfg) if a.lower() == key), None)
            if attr is None or attr.startswith('_'):
                continue
            current = getattr(cfg, attr)
            try:
                if isinstance(current, bool):
                    setattr(cfg, attr, raw.lower() in ('true', '1', 'yes'))
                elif isinstance(current, float):
                    setattr(cfg, attr, float(raw))
                elif isinstance(current, int):
                    setattr(cfg, attr, int(raw))
            except (ValueError, TypeError):
                pass

    def start_mode_simulator(self) -> None:
        """Scripted oval-track simulator — no GPU needed."""
        from cv.cv_draw import Config as DrawConfig
        _video = os.path.join(os.path.dirname(__file__), '..', 'assets', 'RAT-CV-1.mp4')
        if self.cv_engine is not None:
            self.cv_engine.stop()
        cfg = DrawConfig()
        self._load_cv_tuning(cfg)
        self.cv_engine = CVEngineSimulator(video_path=_video, cfg=cfg)
        self.view.video_frame.play_cv_engine(self.cv_engine)

    def start_mode_video(self, path: str) -> None:
        """Real CV (TensorRT) on a video file."""
        from cv.cv_draw import Config as DrawConfig
        if self.cv_engine is not None:
            self.cv_engine.stop()
        cfg = DrawConfig()
        self._load_cv_tuning(cfg)
        self.cv_engine = CVEngine(video_path=path, cfg=cfg)
        self.view.video_frame.play_cv_engine(self.cv_engine)

    def start_mode_camera(self, camera_index: int = 0) -> None:
        """Real CV (TensorRT) on a live USB camera feed."""
        from cv.cv_draw import Config as DrawConfig
        cfg = DrawConfig(USE_LIVE_CAMERA=True, CAMERA_INDEX=camera_index)
        self._load_cv_tuning(cfg)
        if self.cv_engine is not None:
            self.cv_engine.stop()
        self.cv_engine = CVEngine(video_path=None, cfg=cfg)
        self.view.video_frame.play_cv_engine(self.cv_engine)

    def load_video(self, path: str) -> None:
        """Load a new video into the current mode (real CV if possible)."""
        self.start_mode_video(path)

    def cv_pause_toggle(self) -> None:
        """Toggle CV engine pause/resume (SPACE key)."""
        if self.cv_engine is None or not hasattr(self.cv_engine, 'pause_toggle'):
            return
        paused = self.cv_engine.pause_toggle()
        self.view.alert_frame.add_alert(
            f"CV: {'Paused' if paused else 'Resumed'}", INFO)

    def cv_reset_tracking(self) -> None:
        """Reset CV tracking state to SEARCHING (r key)."""
        if self.cv_engine is None or not hasattr(self.cv_engine, 'reset_tracking'):
            return
        self.cv_engine.reset_tracking()
        self.view.alert_frame.add_alert("CV: Tracking reset", INFO)

    def cv_screenshot(self) -> None:
        """Save current CV frame to disk (s key)."""
        if self.cv_engine is None or not hasattr(self.cv_engine, 'take_screenshot'):
            return
        self.cv_engine.take_screenshot()
        self.view.alert_frame.add_alert("CV: Screenshot saved", INFO)

    def cv_restart_video(self) -> None:
        """Restart video from the beginning (v key)."""
        if self.cv_engine is None or not hasattr(self.cv_engine, 'restart_video'):
            return
        self.cv_engine.restart_video()
        self.view.alert_frame.add_alert("CV: Video restarted", INFO)

    def _neutralize_rat(self, rat_id: str):
        """Confirm a kill: log neutralized event, remove from engaged set, alert operator."""
        self.model.engaged_rats.discard(rat_id)
        if hasattr(self.cv_engine, 'set_engaged'):
            self.cv_engine.set_engaged(bool(self.model.engaged_rats))
        self.model.neutralized_rats.add(rat_id)
        if self.model.pending_engage_rat_id == rat_id:
            self.model.pending_engage_rat_id = None
        self._engage_dwell.pop(rat_id, None)
        self._hit_confirm = None
        rat = self.model.rats.get(rat_id)
        if rat:
            self._send_dne_targeting(rat, fire=0, state_command=2, hit_confirmation=1)
        self._send_hit_confirmation(rat_id)
        self.model.analytics_db.log_rat_event(rat_id, 'neutralized')
        self.view.alert_frame.add_alert(f'RAT {rat_id} NEUTRALIZED', INFO)
        primary_id = self._select_primary_target()
        self.model.primary_target_id = primary_id
        self.view.after(0, lambda p=primary_id, e=set(self.model.engaged_rats):
            self.view.map_frame.update_engagement_state(p, e))
        self.view.after(0, lambda n=set(self.model.neutralized_rats):
            self.view.map_frame.update_neutralized_rats(n))
        self.view.after(0, lambda: self.view.control_frame.update_engagement_active(
            bool(self.model.engaged_rats)))

    #===================================================================

    def set_lidar_enabled(self, enabled: bool):
        self.model.set_lidar_enabled(enabled)
        self.view.alert_frame.add_alert(f'LiDAR detection {"enabled" if enabled else "disabled"}')
        self.model.analytics_db.log_sensor_event('lidar', 'enabled' if enabled else 'disabled')
        self._send_detection_command('lidar', bool(enabled))

    #===================================================================

    def set_rf_enabled(self, enabled: bool):
        self.model.set_rf_enabled(enabled)
        self.view.alert_frame.add_alert(f'RF detection {"enabled" if enabled else "disabled"}')
        self.model.analytics_db.log_sensor_event('rf', 'enabled' if enabled else 'disabled')
        self._send_detection_command('rf', bool(enabled))

    #===================================================================

    def set_acoustic_enabled(self, enabled: bool):
        self.model.set_acoustic_enabled(enabled)
        self.view.alert_frame.add_alert(f'Acoustic detection {"enabled" if enabled else "disabled"}')
        self.model.analytics_db.log_sensor_event('acoustic', 'enabled' if enabled else 'disabled')
        self._send_detection_command('acoustic', bool(enabled))

    #===================================================================

    def _send_hit_confirmation(self, rat_id: str) -> None:
        """Notify the DNN that a RAT has been confirmed neutralized."""
        msg = {
            "msg_type": "hit_confirmed",
            "rat_id": rat_id,
            "current_time": time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(msg).encode('utf-8'), (self.dnn_send_ip, self.dnn_send_port))
            sock.close()
        except Exception as e:
            print(f"Failed to send hit confirmation for {rat_id}: {e}")

    #===================================================================

    def _send_detection_command(self, mode: str, enabled: bool):
        """Send a UDP JSON command to the DNN indicating a detection-mode change."""
        msg = {
            "msg_type": "command",
            "command": "set_detection_mode",
            "mode": mode,
            "enabled": enabled
        }
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            payload = json.dumps(msg).encode('utf-8')
            sock.sendto(payload, (self.dnn_send_ip, self.dnn_send_port))
            sock.close()
        except Exception as e:
            print(f"Failed to send detection command for {mode}: {e}")

    #===================================================================

    _STALE_TIMEOUT = 10.0  # seconds before a RAT with no update is removed

    def _check_staleness(self):
        """Remove RATs that have not sent a positional update within _STALE_TIMEOUT seconds."""
        now = time.time()

        if (self._dnn_last_health_time is not None
                and not self._dnn_offline_alerted
                and (now - self._dnn_last_health_time) > self._dnn_health_silence_threshold):
            self._dnn_offline_alerted = True
            self.view.alert_frame.add_alert(
                f'DNN node offline — no health data for {now - self._dnn_last_health_time:.0f}s',
                ERROR,
            )

        stale = [
            rat_id for rat_id, last in self._rat_last_seen.items()
            if now - last > self._STALE_TIMEOUT
        ]
        for rat_id in stale:
            del self._rat_last_seen[rat_id]
            self._known_rats.discard(rat_id)
            self._rat_zones.pop(rat_id, None)
            self.model.engaged_rats.discard(rat_id)
            self.model.neutralized_rats.discard(rat_id)
            if self.model.primary_target_id == rat_id:
                self.model.primary_target_id = None
            if self.model.pending_engage_rat_id == rat_id:
                self.model.pending_engage_rat_id = None
            self.model.remove_rat(rat_id)
            self.model.analytics_db.log_rat_event(rat_id, 'lost')
        primary_id = self._select_primary_target()
        self.model.primary_target_id = primary_id
        zone_counts = {z: sum(1 for rt in self.model.rats.values() if rt.zone == z)
                       for z in (1, 2, 3)}
        any_z3 = zone_counts.get(3, 0) > 0
        self.view.map_frame.update_zone_counts(zone_counts, dict(self.model.rats))
        self.view.map_frame.update_neutralized_rats(set(self.model.neutralized_rats))
        self.view.after(0, lambda az3=any_z3: self.view.control_frame.update_engage_state(az3))
        self.view.after(0, lambda p=primary_id, e=set(self.model.engaged_rats):
            self.view.map_frame.update_engagement_state(p, e))
        self.view.after(0, lambda: self.view.control_frame.update_engagement_active(
            bool(self.model.engaged_rats)))
        self.view.after(5000, self._check_staleness)

    #===================================================================

    def engage_rat(self, rat_id: str):
        """Engage a specific RAT — log to DB and send fire command to DNE."""
        print(f"Engaged RAT: {rat_id}")
        self._hit_confirm = HitConfirmEngine()
        self.model.analytics_db.log_rat_event(rat_id, 'engage_commanded')
        self.model.engaged_rats.add(rat_id)
        if self.cv_engine is not None and hasattr(self.cv_engine, 'set_engaged'):
            self.cv_engine.set_engaged(True)
        rat = self.model.rats.get(rat_id)
        if rat:
            self._send_dne_targeting(rat, fire=1, state_command=3)
        pid = self.model.primary_target_id
        er  = set(self.model.engaged_rats)
        self.view.after(0, lambda p=pid, e=er:
            self.view.map_frame.update_engagement_state(p, e))
        self.view.after(0, lambda: self.view.control_frame.update_engagement_active(True))

    #===================================================================

    def engage_primary_target(self):
        """Engage the primary target, or latch intent if it is not yet in zone 3."""
        pid = self.model.primary_target_id
        if pid is None:
            return
        rat = self.model.rats.get(pid)
        if rat and rat.zone == 3:
            self.engage_rat(pid)
        else:
            self.model.pending_engage_rat_id = pid
            self.view.after(0, lambda: self.view.alert_frame.add_alert(
                f'RAT {pid} engagement latched — awaiting zone-3 re-entry', WARNING))

    #===================================================================

    def cancel_pending_engagement(self):
        """Clear any latched engagement intent (called when grace period expires)."""
        self.model.pending_engage_rat_id = None

    #===================================================================

    def stop_engagement(self):
        """Cancel engagement of the primary target and revert DNE to track-only."""
        pid = self.model.primary_target_id
        if pid is None:
            return
        was_engaged = pid in self.model.engaged_rats
        self.model.engaged_rats.discard(pid)
        self._hit_confirm = None
        if self.cv_engine is not None and hasattr(self.cv_engine, 'set_engaged'):
            self.cv_engine.set_engaged(bool(self.model.engaged_rats))
        self.model.pending_engage_rat_id = None
        rat = self.model.rats.get(pid)
        if rat and rat.zone >= 2:
            self._send_dne_targeting(rat, fire=0, state_command=2)
        if was_engaged:
            self.model.analytics_db.log_rat_event(pid, 'engage_cancelled')
            self.view.after(0, lambda i=pid: self.view.alert_frame.add_alert(
                f'RAT {i} engagement stopped', INFO))
        any_z3 = any(r.zone == 3 for r in self.model.rats.values())
        er = set(self.model.engaged_rats)
        self.view.after(0, lambda az3=any_z3: self.view.control_frame.update_engage_state(az3))
        self.view.after(0, lambda: self.view.control_frame.update_engagement_active(False))
        self.view.after(0, lambda p=pid, e=er:
            self.view.map_frame.update_engagement_state(p, e))
