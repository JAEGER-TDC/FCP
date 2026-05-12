from model.dnn_sim_rat_model import DNNSimRat as Rat
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class DNNSimModel:
    STATUS_FLAGS = ["OK", "WARNING", "ERROR"]

    battery_percentage: float = 100.0
    temperature_c: float = 25.0
    error_code: int = 0
    status_flag: str = STATUS_FLAGS[0]

    lidar_enabled: bool = True
    rf_enabled: bool = True
    acoustic_enabled: bool = True
    
    rats: dict[str, Rat] = field(default_factory=dict)

    #===================================================================

    def set_lidar_enabled(self, enabled: bool):
        self.lidar_enabled = bool(enabled)

    #===================================================================

    def set_rf_enabled(self, enabled: bool):
        self.rf_enabled = bool(enabled)

    #===================================================================

    def set_acoustic_enabled(self, enabled: bool):
        self.acoustic_enabled = bool(enabled)

    #===================================================================

    def update_rat(self, rat: Rat):
        self.rats[rat.rat_id] = rat

    #===================================================================

    def remove_rat(self, rat_id: str):
        if rat_id in self.rats:
            del self.rats[rat_id]

    #===================================================================

    def update_health(self, battery: float, temperature: float,
                      error_code: int, status_flag: str):
        """Update the health fields."""
        self.battery_percentage = max(0.0, min(100.0, battery))
        self.temperature_c = temperature
        self.error_code = error_code
        self.status_flag = status_flag

    #===================================================================

    def to_health_message(self) -> dict:
        """Serialize current health into the required JSON format."""
        return {
            "msg_type": "health",
            "current_time": datetime.now().isoformat(),
            "health": {
                "battery_percent": self.battery_percentage,
                "temperature_c": self.temperature_c,
                "error_code": self.error_code,
                "status_flag": self.status_flag,
            },
        }