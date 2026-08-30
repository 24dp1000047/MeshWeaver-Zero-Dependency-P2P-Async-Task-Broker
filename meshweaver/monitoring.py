import asyncio
import os
import time
from typing import Callable, Dict, Optional


ALIVE = "ALIVE"
SUSPECTED = "SUSPECTED"
OFFLINE = "OFFLINE"


def local_cpu_load() -> float:
    try:
        import psutil  # optional enhancement
        return float(psutil.cpu_percent(interval=None))
    except ImportError:
        return 0.0


def local_ram_percent() -> float:
    try:
        import psutil
        return float(psutil.virtual_memory().percent)
    except ImportError:
        return 0.0


class HeartbeatMonitor:
    def __init__(self, node, timeout: float = 3.0, interval: float = 1.0,
                 on_state_change: Optional[Callable] = None):
        self.node = node
        self.timeout = timeout
        self.interval = interval
        self.on_state_change = on_state_change
        self.peers: Dict[str, dict] = {}
        self._task = None
        self.running = False

    def update(self, node_id: str, cpu_load=0.0, ram_percent=0.0, address=None):
        item = self.peers.setdefault(node_id, {})
        item.update(last_seen=time.time(), state=ALIVE, cpu_load=float(cpu_load), ram_percent=float(ram_percent), address=address)

    def state(self, node_id: str) -> str:
        return self.peers.get(node_id, {}).get("state", OFFLINE)

    def check_once(self) -> Dict[str, str]:
        now = time.time()
        changed = {}
        for node_id, item in self.peers.items():
            age = now - item.get("last_seen", 0)
            if age <= self.timeout:
                new_state = ALIVE
            elif age <= self.timeout * 2:
                new_state = SUSPECTED
            else:
                new_state = OFFLINE
            if new_state != item.get("state"):
                item["state"] = new_state
                changed[node_id] = new_state
                if self.on_state_change:
                    self.on_state_change(node_id, new_state)
        return changed

    async def start(self):
        self.running = True
        while self.running:
            self.check_once()
            await asyncio.sleep(self.interval)

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None


# ---------------------------------------------------------------------------
# Sahil — Resource monitoring (ResourceStatus / ResourceMonitor)
# Restored from main-branch monitoring.py (was misplaced at project root).
# ---------------------------------------------------------------------------

from dataclasses import dataclass, asdict


@dataclass
class ResourceStatus:
    """Snapshot of a node's CPU and RAM utilisation at a point in time."""

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
            timestamp=float(data["timestamp"]),
        )


class ResourceMonitor:
    """Collect CPU and RAM metrics for a local node."""

    def __init__(self, node_id: str):
        self.node_id = node_id

    def collect(self) -> ResourceStatus:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
        except ImportError:
            cpu = 0.0
            ram = 0.0
        return ResourceStatus(
            node_id=self.node_id,
            cpu_percent=float(cpu),
            ram_percent=float(ram),
            timestamp=time.time(),
        )
