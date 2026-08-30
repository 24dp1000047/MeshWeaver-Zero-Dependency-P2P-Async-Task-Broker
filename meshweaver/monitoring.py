import time
import psutil
from dataclasses import dataclass, asdict


@dataclass
class ResourceStatus:
    node_id: str
    cpu_percent: float
    ram_percent: float
    timestamp: float

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            node_id=data["node_id"],
            cpu_percent=float(data["cpu_percent"]),
            ram_percent=float(data["ram_percent"]),
            timestamp=float(data["timestamp"])
        )


class ResourceMonitor:
    def __init__(self, node_id):
        self.node_id = node_id

    def collect(self):
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        return ResourceStatus(
            node_id=self.node_id,
            cpu_percent=cpu,
            ram_percent=ram,
            timestamp=time.time()
        )
