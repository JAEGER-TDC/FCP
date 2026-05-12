from dataclasses import dataclass
from datetime import datetime
import json

@dataclass
class DNNSimRat:
    rat_id: str
    zone: int
    az_value: float
    el_value: float
    range_value: float
    az_rate: float
    el_rate: float
    range_rate: float

    def to_message(self) -> str:
        return json.dumps(self._to_dict())
    
    def _to_dict(self) -> dict:
        return {
            "msg_type": "positional",
            "rat_id": self.rat_id,
            "current_time": datetime.now().isoformat(),
            "zone": self.zone,
            "values": {
                "az_value": self.az_value,
                "el_value": self.el_value,
                "range_value": self.range_value
            },
            "rates": {
                "az_rate": self.az_rate,
                "el_rate": self.el_rate,
                "range_rate": self.range_rate
            }
        }