import threading
from dataclasses import dataclass, field
from model.rat_model import Rat
from model.analytics_db import FCPAnalyticsDB

@dataclass
class FCPModel:
    lidar_enabled: bool = True
    rf_enabled: bool = True
    acoustic_enabled: bool = True
    rats: dict[str, Rat] = field(default_factory=dict)
    analytics_db: FCPAnalyticsDB = field(default_factory=FCPAnalyticsDB)
    dne_healthy: bool = False
    dne_laser_firing: bool = False
    engaged_rats: set = field(default_factory=set)
    neutralized_rats: set[str] = field(default_factory=set)
    primary_target_id: str | None = None
    pending_engage_rat_id: str | None = None
    # Previous DNN node health snapshot for change-detection de-duplication.
    # None until the first health message is received.
    dnn_node_prev: dict | None = field(default=None)

    # CV tracking state — updated by the in-process CV engine poller.
    # cv_centroid/cv_frame_size are None until the first frame is processed.
    cv_state: str = "SEARCHING"
    cv_confidence: float = 0.0
    cv_centroid: tuple[int, int] | None = field(default=None)
    cv_frame_size: tuple[int, int] | None = field(default=None)
    cv_last_update: float = 0.0

    def __post_init__(self):
        self._rats_lock = threading.Lock()

    def set_lidar_enabled(self, enabled: bool):
        self.lidar_enabled = bool(enabled)

    def set_rf_enabled(self, enabled: bool):
        self.rf_enabled = bool(enabled)

    def set_acoustic_enabled(self, enabled: bool):
        self.acoustic_enabled = bool(enabled)

    def update_rat(self, rat: Rat):
        with self._rats_lock:
            self.rats[rat.rat_id] = rat

    def remove_rat(self, rat_id: str):
        with self._rats_lock:
            if rat_id in self.rats:
                del self.rats[rat_id]