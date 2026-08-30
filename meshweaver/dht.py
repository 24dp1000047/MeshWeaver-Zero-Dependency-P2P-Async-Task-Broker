import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, Optional
from .routing import PeerLoad, select_lowest_load


@dataclass
class PeerInfo:
    node_id: str
    host: str
    port: int
    cpu_load: float = 0.0
    ram_percent: float = 0.0
    state: str = "ALIVE"
    last_seen: float = 0.0


class PeerTable:
    """Lightweight Kademlia-style peer table backed by gossip/load information."""
    def __init__(self):
        self.peers: Dict[str, PeerInfo] = {}

    def upsert(self, peer: PeerInfo) -> None:
        self.peers[peer.node_id] = peer

    def remove(self, node_id: str) -> None:
        self.peers.pop(node_id, None)

    def available(self, source_node: Optional[str] = None) -> Iterable[PeerInfo]:
        for peer in self.peers.values():
            if peer.state == "ALIVE" and peer.node_id != source_node:
                yield peer

    def lowest_load(self, source_node: Optional[str] = None) -> Optional[PeerInfo]:
        return select_lowest_load(
            (PeerLoad(p.node_id, p.cpu_load, p.host, p.port, p.state, p.last_seen) for p in self.peers.values()),
            source_node,
        )

    @staticmethod
    def node_hash(node_id: str) -> int:
        return int.from_bytes(hashlib.sha256(node_id.encode()).digest(), "big")

    def find_closest(self, target_node_id: str, k: int = 3) -> list[PeerInfo]:
        target = self.node_hash(target_node_id)
        return sorted(self.peers.values(), key=lambda p: self.node_hash(p.node_id) ^ target)[:k]
