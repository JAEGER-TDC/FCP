from dataclasses import dataclass

@dataclass
class DNESimModel:
    am_i_healthy: bool = True
    laser_firing: bool = False
    # Last received targeting data (displayed in UI)
    az: float = 0.0
    el: float = 0.0
    range_m: float = 0.0
    az_rate: float = 0.0
    el_rate: float = 0.0
    range_rate: float = 0.0
    fire: int = 0
    state_command: int = 0
