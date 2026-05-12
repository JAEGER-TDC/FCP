from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Node:
    battery_percent: float
    temperature_c: float
    error_code: int
    status_flag: str

    def __init__(self, data: Dict[str, Any]):
        health = data.get('health', {}) or {}
        self.battery_percent = health.get('battery_percent', 0)
        self.temperature_c = health.get('temperature_c', 0.0)
        self.error_code = health.get('error_code', 0)
        self.status_flag = health.get('status_flag', '')