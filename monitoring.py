import time
import psutil
from dataclasses import dataclass, asdict
from typing import Dict, Any

@dataclass
class ResourceStatus:
    node_id: str
    cpu_percent: float
    ram_percent: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceStatus":
        return cls(
            node_id=str(data["node_id"]),
            cpu_percent=float(data["cpu_percent"]),
            ram_percent=float(data["ram_percent"]),
            timestamp=float(data["timestamp"])
        )


class ResourceMonitor:
    def __init__(self, node_id: str):
        self.node_id = node_id

    def collect_metrics(self) -> ResourceStatus:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        return ResourceStatus(
            node_id=self.node_id,
            cpu_percent=cpu,
            ram_percent=ram,
            timestamp=time.time()
        )
