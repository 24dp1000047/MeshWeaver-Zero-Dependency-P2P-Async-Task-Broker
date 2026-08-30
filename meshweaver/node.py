from dataclasses import dataclass, field
from time import time
from typing import Dict, Optional, Tuple


@dataclass
class Node:
    node_id: str
    host: str
    port: int
    cpu_load: float = 0.0
    ram_percent: float = 0.0
    state: str = "ALIVE"
    last_seen: float = field(default_factory=time)
    peers: Dict[str, Tuple[str, int]] = field(default_factory=dict)

    def touch(self, cpu_load: Optional[float] = None, ram_percent: Optional[float] = None) -> None:
        self.last_seen = time()
        self.state = "ALIVE"
        if cpu_load is not None:
            self.cpu_load = float(cpu_load)
        if ram_percent is not None:
            self.ram_percent = float(ram_percent)

    def add_peer(self, node_id: str, host: str, port: int) -> None:
        self.peers[node_id] = (host, port)

    @property
    def address(self) -> Tuple[str, int]:
        return self.host, self.port
