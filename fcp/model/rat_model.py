from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Rat:
    rat_id: str
    zone: int
    az_value: float
    el_value: float
    range_value: float
    az_rate: float
    el_rate: float
    range_rate: float

    def __init__(self, data: Dict[str, Any]):
        self.rat_id = data.get('rat_id', '')
        self.zone = data.get('zone', 0)
        values = data.get('values', {}) or {}
        rates = data.get('rates', {}) or {}
        self.az_value = values.get('az_value', 0.0)
        self.el_value = values.get('el_value', 0.0)
        self.range_value = values.get('range_value', 0.0)
        self.az_rate = rates.get('az_rate', 0.0)
        self.el_rate = rates.get('el_rate', 0.0)
        self.range_rate = rates.get('range_rate', 0.0)