import time
import logging
from enum import Enum
from typing import Dict, Optional, Callable, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class NodeState(Enum):
    """[Week 3 Track] Node liveness states"""
    ALIVE = "ALIVE"
    SUSPECTED = "SUSPECTED"
    OFFLINE = "OFFLINE"


class HeartbeatManager:
    """
    [Week 3 Track - Sahil]
    Tracks heartbeats, manages node liveness state (ALIVE, SUSPECTED, OFFLINE).
    """
    def __init__(
        self, 
        node_id: str, 
        heartbeat_interval: float = 2.0, 
        suspect_timeout: float = 6.0, 
        offline_timeout: float = 10.0
    ):
        self.node_id = node_id
        self.heartbeat_interval = heartbeat_interval
        self.suspect_timeout = suspect_timeout
        self.offline_timeout = offline_timeout
        
        # {peer_id: last_seen_timestamp}
        self.last_seen: Dict[str, float] = {}
        # {peer_id: NodeState}
        self.peer_states: Dict[str, NodeState] = {}
        
        self._is_running = False
        self.on_node_offline_callbacks: List[Callable[[str], None]] = []
        self.network_send_cb: Optional[Callable[[dict], None]] = None

    def register_network_callback(self, callback: Callable[[dict], None]):
        self.network_send_cb = callback

    def register_offline_callback(self, callback: Callable[[str], None]):
        self.on_node_offline_callbacks.append(callback)
