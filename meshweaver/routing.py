from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class PeerLoad:
    node_id: str
    cpu_load: float
    host: str
    port: int
    state: str = "ALIVE"
    last_seen: float = 0.0


def select_lowest_load(peers: Iterable[PeerLoad], source_node: Optional[str] = None) -> Optional[PeerLoad]:
    available = [
        p for p in peers
        if p.state == "ALIVE" and (source_node is None or p.node_id != source_node)
    ]
    return min(available, key=lambda p: (float(p.cpu_load), p.node_id), default=None)
