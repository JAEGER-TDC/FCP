import os
import socket
import threading
import json
import time
import math

from model.dnn_sim_model import DNNSimModel
from view.dnn_sim_view import DNNSimView

from model.dnn_sim_rat_model import DNNSimRat as Rat
import random

_RAT_RANGE_MAX       = 85.0   # m — outer detection boundary (SOW §1.2)
_RAT_RANGE_SPAWN_MIN = 60.0   # m — spawn at inner edge of outer zone
_RAT_ALT_MIN         = 0.0    # m — ground floor (SOW §1.1)
_RAT_ALT_MAX         = 15.0   # m — airspace ceiling (SOW §1.1)
_RAT_MAX_SPEED       = 5.0    # m/s — absolute speed cap
_RAT_MAX_ACCEL       = 0.5    # m/s² — random perturbation magnitude per step

class DNNSimController:
    def __init__(self, model: DNNSimModel, view: DNNSimView):
        self.model = model
        self.view = view

        self.config = self.read_config(os.path.join(os.path.dirname(__file__), '..', 'cfg', 'config.ini'))

        self.fcp_send_ip = self.config['FCP.send.connection']['ip']
        self.fcp_send_port = self.config['FCP.send.connection'].getint('port')

        self.fcp_recv_ip = self.config['FCP.recv.connection']['ip']
        self.fcp_recv_port = self.config['FCP.recv.connection'].getint('port')

        self.health_freq = self.config['FCP.msg.freq'].getfloat('health_freq', fallback=1.0)  # default to 1 Hz if not specified
        self.pos_freq = self.config['FCP.msg.freq'].getfloat('pos_freq', fallback=0.1)  # default to 10 Hz if not specified

        # keep track of per‑RAT update threads and their stop events
        self._rat_threads: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._health_thread: tuple[threading.Thread, threading.Event] | None = None

        # per-RAT Cartesian state {x, y, z, vx, vy, vz} — owned exclusively by each RAT's thread
        self._rat_states: dict[str, dict] = {}

        self._start_udp_listener()

    #===================================================================

    def read_config(self, config_file):
        import configparser
        config = configparser.ConfigParser()
        config.read(config_file)
        return config

    #===================================================================

    def _start_udp_listener(self):
        print(f"Trying to bind UDP listener on {self.fcp_recv_ip}:{self.fcp_recv_port}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.fcp_recv_ip, self.fcp_recv_port))
            print("UDP listener successfully bound")
        except Exception as e:
            print(f"Failed to bind UDP listener on {self.fcp_recv_ip}:{self.fcp_recv_port}: {e}")
            return

        def _listen_loop(s):
            while True:
                try:
                    data, addr = s.recvfrom(65535)
                    data_dict = json.loads(data.decode('utf-8'))
                    self.view.after(0, lambda d=data_dict, a=addr: self.view.recv_data_frame.add_alert(f"Received from {a}: {d}"))

                    if data_dict.get('msg_type') == 'command':
                        self.view.after(0, lambda d=data_dict: self.handle_command(d))
                    elif data_dict.get('msg_type') == 'hit_confirmed':
                        rat_id = data_dict.get('rat_id')
                        if rat_id:
                            self.view.after(0, lambda r=rat_id: self._handle_hit_confirmed(r))
                except Exception as e:
                    import traceback
                    print(f"UDP listener error: {e}")
                    traceback.print_exc()
                    continue

        t = threading.Thread(target=_listen_loop, args=(sock,), daemon=True)
        t.start()

    #===================================================================

    def _handle_hit_confirmed(self, rat_id: str):
        """Stop broadcasting a RAT that FCP has confirmed neutralized."""
        if rat_id in self._rat_threads:
            self.stop_rat_sim(rat_id)
        else:
            self.view.recv_data_frame.add_alert(
                f'Hit confirmed for {rat_id} — not currently active')

    #===================================================================

    def handle_command(self, command_dict):
        if command_dict.get('command') == 'set_detection_mode':
            mode = command_dict.get('mode')

            if mode == 'lidar':
                self.model.set_lidar_enabled(command_dict.get('enabled'))
                self.view.mode_frame.set_lidar_enabled(command_dict.get('enabled'))
            elif mode == 'rf':
                self.model.set_rf_enabled(command_dict.get('enabled'))
                self.view.mode_frame.set_rf_enabled(command_dict.get('enabled'))
            elif mode == 'acoustic':
                self.model.set_acoustic_enabled(command_dict.get('enabled'))
                self.view.mode_frame.set_acoustic_enabled(command_dict.get('enabled'))

    #===================================================================

    def _init_rat_state(self, rat_id: str):
        """Seed the Cartesian state for a RAT, spawning it in the outer zone with an inward velocity."""
        slant_range = random.uniform(_RAT_RANGE_SPAWN_MIN, _RAT_RANGE_MAX)
        z = random.uniform(2.0, 13.0)
        rho_h = math.sqrt(max(slant_range**2 - z**2, 0.0))
        az_spawn = random.uniform(math.pi / 4, 3 * math.pi / 4)  # 45°–135°: FOV centred on north
        x = rho_h * math.cos(az_spawn)
        y = rho_h * math.sin(az_spawn)

        inward_az = az_spawn + math.pi + random.uniform(-0.3, 0.3)
        speed = random.uniform(0.5, 3.0)
        vx = speed * math.cos(inward_az)
        vy = speed * math.sin(inward_az)
        vz = random.uniform(-0.3, 0.3)

        self._rat_states[rat_id] = {'x': x, 'y': y, 'z': z, 'vx': vx, 'vy': vy, 'vz': vz}

    #===================================================================

    def _step_rat_state(self, rat_id: str, dt: float) -> Rat:
        """
        Advance the Cartesian state of a RAT by one timestep dt (seconds),
        enforce all physical boundaries, and return a Rat dataclass with
        spherical coordinates and their exact time-derivative rates.
        """
        s = self._rat_states[rat_id]

        # a. Random acceleration perturbation
        s['vx'] += random.uniform(-_RAT_MAX_ACCEL, _RAT_MAX_ACCEL) * dt
        s['vy'] += random.uniform(-_RAT_MAX_ACCEL, _RAT_MAX_ACCEL) * dt
        s['vz'] += random.uniform(-_RAT_MAX_ACCEL, _RAT_MAX_ACCEL) * dt

        # b. Speed clamp
        spd = math.sqrt(s['vx']**2 + s['vy']**2 + s['vz']**2)
        if spd > _RAT_MAX_SPEED:
            scale = _RAT_MAX_SPEED / spd
            s['vx'] *= scale
            s['vy'] *= scale
            s['vz'] *= scale

        # c. Position integration
        s['x'] += s['vx'] * dt
        s['y'] += s['vy'] * dt
        s['z'] += s['vz'] * dt

        # d. Altitude boundary reflection
        if s['z'] < _RAT_ALT_MIN:
            s['z'] = _RAT_ALT_MIN
            s['vz'] = abs(s['vz'])
        elif s['z'] > _RAT_ALT_MAX:
            s['z'] = _RAT_ALT_MAX
            s['vz'] = -abs(s['vz'])

        # e. Azimuth sector boundary reflection (90° FOV centred on north: |x| ≤ y)
        # Right boundary az=45° is the line x=y.  Specular reflection swaps vx↔vy.
        if s['x'] > s['y']:
            s['x'] = s['y']
            if s['vx'] > s['vy']:       # only reflect if moving outward
                s['vx'], s['vy'] = s['vy'], s['vx']
        # Left boundary az=135° is the line x=-y.  Specular reflection: (vx,vy)→(-vy,-vx).
        if s['x'] < -s['y']:
            s['x'] = -s['y']
            if s['vx'] + s['vy'] < 0:  # only reflect if moving outward
                s['vx'], s['vy'] = -s['vy'], -s['vx']

        # f. Outer range boundary reflection (specular off sphere surface)
        x, y, z = s['x'], s['y'], s['z']
        r = math.sqrt(x**2 + y**2 + z**2)
        if r > _RAT_RANGE_MAX:
            rr = (x * s['vx'] + y * s['vy'] + z * s['vz']) / r
            if rr > 0:  # only reflect if still moving outward
                rx, ry, rz = x / r, y / r, z / r
                s['vx'] -= 2 * rr * rx
                s['vy'] -= 2 * rr * ry
                s['vz'] -= 2 * rr * rz

        # g. Spherical coordinate conversion with exact rate derivatives
        x, y, z = s['x'], s['y'], s['z']
        vx, vy, vz = s['vx'], s['vy'], s['vz']
        r = math.sqrt(x**2 + y**2 + z**2)
        rho = math.sqrt(x**2 + y**2)  # horizontal distance

        az_deg = math.degrees(math.atan2(y, x))
        el_deg = math.degrees(math.atan2(z, rho))
        range_rate = (x * vx + y * vy + z * vz) / r

        if rho > 1e-9:
            az_rate_degs = math.degrees((x * vy - y * vx) / (x**2 + y**2))
            el_rate_degs = math.degrees((rho**2 * vz - z * (x * vx + y * vy)) / (rho * r**2))
        else:
            az_rate_degs = 0.0
            el_rate_degs = 0.0

        # h. Zone derived from range
        if r <= 30.0:
            zone = 3
        elif r <= 60.0:
            zone = 2
        else:
            zone = 1

        return Rat(
            rat_id=rat_id,
            zone=zone,
            az_value=round(az_deg, 6),
            el_value=round(el_deg, 6),
            range_value=round(r, 6),
            az_rate=round(az_rate_degs, 6),
            el_rate=round(el_rate_degs, 6),
            range_rate=round(range_rate, 6),
        )

    #===================================================================

    def _rat_update_loop(self, rat_id: str, stop_event: threading.Event):
        """
        Background loop that continuously:
        • advances the RAT physics state,
        • updates the model,
        • refreshes the view,
        • sends the positional message over UDP.
        """
        # reuse a single UDP socket for the whole life of the thread
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dt = 1.0 / self.pos_freq

        while not stop_event.is_set():
            try:
                rat = self._step_rat_state(rat_id, dt)
                self.model.update_rat(rat)

                def _update_rat_frame(r=rat):
                    for frame in self.view.control_frame.rat_frames:
                        if frame.rat_id == r.rat_id:
                            frame.update_rat_data(r)
                            break
                self.view.after(0, _update_rat_frame)

                message = rat.to_message().encode('utf-8')
                sock.sendto(message, (self.fcp_send_ip, self.fcp_send_port))
                self.view.after(0, lambda m=message: self.view.sent_data_frame.add_alert(f"Sent: {m.decode('utf-8')}"))
                time.sleep(1.0 / self.pos_freq)
            except Exception as e:
                import traceback
                print(f"Error in RAT update thread for {rat_id}: {e}")
                traceback.print_exc()
                # Continue looping unless stop requested
        sock.close()
        print(f"RAT update thread for {rat_id} terminated")

    #===================================================================

    def start_rat_sim(self, rat_id):
        """
        Starts (or restarts) the simulation thread for a given RAT.
        If a thread already exists for this RAT, it is stopped first.
        """
        print(f"Starting simulation for RAT {rat_id}")

        # Stop existing thread if present
        if rat_id in self._rat_threads:
            self.stop_rat_sim(rat_id)

        # Seed Cartesian state before starting the thread
        self._init_rat_state(rat_id)

        # Initialise the thread & stop flag
        stop_event = threading.Event()
        t = threading.Thread(target=self._rat_update_loop,
                             args=(rat_id, stop_event),
                             daemon=True)
        self._rat_threads[rat_id] = (t, stop_event)
        t.start()

    #===================================================================

    def stop_rat_sim(self, rat_id):
        """
        Signals the associated update thread to stop and waits for it to finish.
        Also removes the RAT from the model.
        """
        print(f"Stopping simulation for RAT {rat_id}")

        thread_info = self._rat_threads.pop(rat_id, None)
        if thread_info:
            thread, stop_event = thread_info
            stop_event.set()
            thread.join(timeout=2.0)   # give it a moment to finish cleanly
        else:
            print(f"No active simulation thread found for RAT {rat_id}")

        self._rat_states.pop(rat_id, None)
        self.model.remove_rat(rat_id)

    #===================================================================

    def start_health_sim(self):
        if self._health_thread:
            self.stop_health_sim()   # restart if already running

        stop_evt = threading.Event()
        t = threading.Thread(target=self._health_update_loop,
                             args=(stop_evt,),
                             daemon=True)
        self._health_thread = (t, stop_evt)
        t.start()
        print("Health simulation started")

    #===================================================================

    def stop_health_sim(self):
        if not self._health_thread:
            print("Health simulation not running")
            return
        thread, stop_evt = self._health_thread
        stop_evt.set()
        thread.join(timeout=2.0)
        self._health_thread = None
        print("Health simulation stopped")

    #===================================================================

    def _health_update_loop(self, stop_event: threading.Event):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # start with the model’s current values
        battery = self.model.battery_percentage
        temperature = self.model.temperature_c
        error_code = self.model.error_code
        status_flag = self.model.status_flag

        while not stop_event.is_set():
            try:
                battery = round(max(0.0, battery - random.uniform(0.05, 0.2)), 2)
                temperature += random.uniform(-0.2, 0.2)
                temperature = round(temperature, 2)

                # Occasionally inject an error
                if random.random() < 0.02:
                    error_code = random.randint(1, 999)
                    status_flag = random.choice(DNNSimModel.STATUS_FLAGS[1:])
                else:
                    error_code = 0
                    status_flag = DNNSimModel.STATUS_FLAGS[0]

                self.model.update_health(battery, temperature, error_code, status_flag)

                msg = json.dumps(self.model.to_health_message()).encode('utf-8')
                sock.sendto(msg, (self.fcp_send_ip, self.fcp_send_port))

                if self.view and hasattr(self.view, 'control_frame'):
                    health_frame = self.view.control_frame.health_frame
                    # schedule UI update safely
                    self.view.after(
                        0,
                        lambda: health_frame.update_health(battery, temperature, error_code, status_flag)
                    )

                time.sleep(1.0 / self.health_freq)
            except Exception as e:
                import traceback
                print(f"Error in health simulation loop: {e}")
                traceback.print_exc()
        sock.close()
        print("Health simulation thread terminated")
