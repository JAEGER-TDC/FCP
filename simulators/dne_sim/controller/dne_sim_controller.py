import os
import socket
import threading
import configparser

from model.dne_sim_model import DNESimModel
from view.dne_sim_view import DNESimView
from protocol.dne_target import Target, PacketReceiver, make_packet


class DNESimController:
    def __init__(self, model: DNESimModel, view: DNESimView):
        self.model = model
        self.view = view

        config = configparser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), '..', 'cfg', 'config.ini'))
        self._listen_port = config['FCP.serial'].getint('listen_port')

        self._conn_lock = threading.Lock()
        self._active_conn: socket.socket | None = None

        self._start_server()

    #===================================================================

    def _start_server(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('', self._listen_port))
            server.listen(1)
            print(f"DNE sim listening on port {self._listen_port}")
        except Exception as e:
            print(f"DNE sim failed to start server on port {self._listen_port}: {e}")
            return

        def _handle_conn(conn):
            with self._conn_lock:
                self._active_conn = conn
            self.view.after(0, lambda: self.view.recv_data_frame.add_alert('FCP connected'))
            # Send an immediate zero-state heartbeat so FCP shows Connected right away
            try:
                heartbeat = Target(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)
                conn.sendall(make_packet(heartbeat))
            except Exception:
                pass
            receiver = PacketReceiver()
            try:
                while True:
                    byte = conn.recv(1)
                    if not byte:
                        break
                    result = receiver.process_byte(byte[0])
                    if result is None:
                        continue

                    def _update(r=result):
                        self.model.az = r.azimuth
                        self.model.el = r.elevation
                        self.model.range_m = r.range
                        self.model.az_rate = r.azimuth_d
                        self.model.el_rate = r.elevation_d
                        self.model.range_rate = r.range_d
                        self.model.fire = r.fire
                        self.model.state_command = r.state
                        # Auto-fire: mirror the FCP's fire command into laser_firing
                        if r.fire == 1 and self.model.am_i_healthy:
                            self.model.laser_firing = True
                            self.view.status_frame.set_laser_firing(True)
                        elif r.fire == 0:
                            self.model.laser_firing = False
                            self.view.status_frame.set_laser_firing(False)
                        self.view.targeting_frame.update_targeting(
                            r.azimuth, r.elevation, r.range,
                            r.azimuth_d, r.elevation_d, r.range_d,
                            r.fire, r.state)
                        self.view.recv_data_frame.add_alert(
                            f"az={r.azimuth:.2f} el={r.elevation:.2f} range={r.range:.2f} "
                            f"azr={r.azimuth_d:.2f} elr={r.elevation_d:.2f} rngr={r.range_d:.2f} "
                            f"fire={r.fire} state={r.state}"
                        )
                    self.view.after(0, _update)

                    # Echo back with laser_firing state substituted for fire;
                    # suppress response entirely when unhealthy (FCP infers DNE is down)
                    if self.model.am_i_healthy:
                        echo = Target(
                            result.azimuth, result.elevation, result.range,
                            result.azimuth_d, result.elevation_d, result.range_d,
                            int(self.model.laser_firing), result.state,
                        )
                        conn.sendall(make_packet(echo))

            except Exception as e:
                print(f"DNE sim connection error: {e}")
            finally:
                conn.close()
                with self._conn_lock:
                    self._active_conn = None
                self.view.after(0, lambda: self.view.recv_data_frame.add_alert('FCP disconnected'))

        def _accept_loop():
            while True:
                try:
                    conn, addr = server.accept()
                    t = threading.Thread(target=_handle_conn, args=(conn,), daemon=True)
                    t.start()
                except Exception as e:
                    print(f"DNE sim accept error: {e}")

        t = threading.Thread(target=_accept_loop, daemon=True)
        t.start()

    #===================================================================

    def set_healthy(self, value: bool):
        self.model.am_i_healthy = value
        self.view.status_frame.set_healthy(value)

    def set_laser_firing(self, value: bool):
        self.model.laser_firing = value
        self.view.status_frame.set_laser_firing(value)
