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
        def process_incoming_heartbeat(self, message: dict):
        """Receives heartbeat ping from peer node and updates timestamp."""
        if message.get("message_type") != "HEARTBEAT_PING":
            return

        sender_id = message.get("sender_id")
        if not sender_id or sender_id == self.node_id:
            return

        current_time = time.time()
        self.last_seen[sender_id] = current_time
        
        prev_state = self.peer_states.get(sender_id)
        self.peer_states[sender_id] = NodeState.ALIVE
        
        if prev_state and prev_state != NodeState.ALIVE:
            logging.info(f"[Week 3] Node [{sender_id}] recovered back to ALIVE.")

    def check_node_health(self):
        """Audits status of all peers based on missed heartbeats."""
        current_time = time.time()
        
        for peer_id, last_ts in list(self.last_seen.items()):
            elapsed = current_time - last_ts
            current_state = self.peer_states.get(peer_id, NodeState.ALIVE)

            if elapsed >= self.offline_timeout:
                if current_state != NodeState.OFFLINE:
                    self.peer_states[peer_id] = NodeState.OFFLINE
                    logging.error(f"[Week 3] Node [{peer_id}] marked OFFLINE (No heartbeat for {elapsed:.1f}s).")
                    
                    for cb in self.on_node_offline_callbacks:
                        cb(peer_id)

            elif elapsed >= self.suspect_timeout:
                if current_state == NodeState.ALIVE:
                    self.peer_states[peer_id] = NodeState.SUSPECTED
                    logging.warning(f"[Week 3] Node [{peer_id}] marked SUSPECTED (Missed heartbeats for {elapsed:.1f}s).")

async def start_heartbeat_loop(self):
        self._is_running = True
        logging.info(f"[Week 3] Started Heartbeat Monitor for [{self.node_id}]")

        while self._is_running:
            try:
                hb_message = {
                    "message_type": "HEARTBEAT_PING",
                    "sender_id": self.node_id,
                    "timestamp": time.time()
                }
                if self.network_send_cb:
                    self.network_send_cb(hb_message)

                self.check_node_health()

            except Exception as e:
                logging.error(f"Error in heartbeat loop: {e}")

            await asyncio.sleep(self.heartbeat_interval)

    def stop(self):
        self._is_running = False
        logging.info(f"[Week 3] Stopped Heartbeat Monitor for [{self.node_id}]")
