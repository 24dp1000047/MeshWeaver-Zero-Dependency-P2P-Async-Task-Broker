import time
import asyncio
import logging
from enum import Enum

logger = logging.getLogger("meshweaver.heartbeat")


class NodeState(Enum):
    ALIVE = "ALIVE"
    SUSPECTED = "SUSPECTED"
    OFFLINE = "OFFLINE"


class HeartbeatManager:
    def __init__(self, node_id, heartbeat_interval=2.0, suspect_timeout=6.0, offline_timeout=10.0):
        self.node_id = node_id
        self.interval = heartbeat_interval
        self.suspect_t = suspect_timeout
        self.offline_t = offline_timeout
        
        self.last_seen = {}
        self.peer_states = {}
        
        self.active = False
        self.offline_cb_list = []
        self.net_send = None

    def register_network_callback(self, cb):
        self.net_send = cb

    def register_offline_callback(self, cb):
        self.offline_cb_list.append(cb)

    def process_incoming_heartbeat(self, msg):
        if not isinstance(msg, dict) or msg.get("message_type") != "HEARTBEAT_PING":
            return

        sender = msg.get("sender_id")
        if not sender or sender == self.node_id:
            return

        now = time.time()
        self.last_seen[sender] = now
        
        prev = self.peer_states.get(sender)
        self.peer_states[sender] = NodeState.ALIVE
        
        if prev and prev != NodeState.ALIVE:
            logger.info(f"Node {sender} recovered to ALIVE state")

    def check_node_health(self):
        now = time.time()
        
        for peer, ts in list(self.last_seen.items()):
            delta = now - ts
            st = self.peer_states.get(peer, NodeState.ALIVE)

            if delta >= self.offline_t:
                if st != NodeState.OFFLINE:
                    self.peer_states[peer] = NodeState.OFFLINE
                    logger.error(f"Node {peer} unreachable. Marking OFFLINE after {round(delta, 1)}s")
                    
                    for fn in self.offline_cb_list:
                        try:
                            fn(peer)
                        except Exception as err:
                            logger.exception(f"Callback error for node {peer}: {err}")

            elif delta >= self.suspect_t:
                if st == NodeState.ALIVE:
                    self.peer_states[peer] = NodeState.SUSPECTED
                    logger.warning(f"Missed heartbeats from {peer}. State changed to SUSPECTED")

    async def start_heartbeat_loop(self):
        self.active = True
        logger.info(f"Heartbeat loop started for {self.node_id}")

        while self.active:
            try:
                if self.net_send:
                    payload = {
                        "message_type": "HEARTBEAT_PING",
                        "sender_id": self.node_id,
                        "timestamp": time.time()
                    }
                    self.net_send(payload)

                self.check_node_health()
            except Exception as e:
                logger.error(f"Unexpected error in heartbeat loop: {e}")

            await asyncio.sleep(self.interval)

    def stop(self):
        self.active = False
        logger.info(f"Heartbeat loop stopped for {self.node_id}")
