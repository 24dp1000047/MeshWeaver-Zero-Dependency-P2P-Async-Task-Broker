import asyncio
import time
import logging
from typing import Dict, Callable, Optional, Any
from meshweaver.monitoring import ResourceStatus, ResourceMonitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class GossipMessageBuilder:
    """
    [Week 1 & 2 Track]
    Defines network message formats for resource updates.
    """
    @staticmethod
    def build_resource_message(status: ResourceStatus) -> Dict[str, Any]:
        return {
            "message_type": "GOSSIP_RESOURCE_METRICS",
            "sender_id": status.node_id,
            "payload": status.to_dict()
        }


class BackgroundMonitorLoop:
    """
    [Week 1 Track]
    Asyncio background loop that collects local metrics at regular intervals.
    """
    def __init__(self, node_id: str, interval: float = 2.0):
        self.node_id = node_id
        self.interval = interval
        self.monitor = ResourceMonitor(node_id)
        self.latest_status: Optional[ResourceStatus] = None
        self._is_running = False

    async def start(self):
        self._is_running = True
        logging.info(f"[Week 1] Started Resource Monitor for Node: {self.node_id}")

        while self._is_running:
            try:
                # 1. Collect local metrics
                self.latest_status = self.monitor.collect_metrics()
                
                # 2. Build gossip message payload
                msg = GossipMessageBuilder.build_resource_message(self.latest_status)
                
                logging.info(
                    f"[Week 1] Collected Metrics -> CPU: {self.latest_status.cpu_percent}% | "
                    f"RAM: {self.latest_status.ram_percent}%"
                )
            except Exception as e:
                logging.error(f"Error in background monitoring loop: {e}")

            await asyncio.sleep(self.interval)

    def stop(self):
        self._is_running = False
        logging.info(f"[Week 1] Stopped Resource Monitor for Node: {self.node_id}")


class GossipManager:
    """
    [Week 2 Track]
    Manages periodic gossip broadcasting of CPU/RAM metrics (~5s interval),
    maintains the Peer Load Table, and removes stale peer resource entries.
    """
    def __init__(self, node_id: str, gossip_interval: float = 5.0, ttl_seconds: float = 15.0):
        self.node_id = node_id
        self.gossip_interval = gossip_interval
        self.ttl_seconds = ttl_seconds  # Peer data older than this gets removed
        self.monitor = ResourceMonitor(node_id)
        
        # Peer Load Table: {node_id: ResourceStatus}
        self.peer_load_table: Dict[str, ResourceStatus] = {}
        self._is_running = False
        
        # Network callback function (provided by networking module)
        self.network_send_cb: Optional[Callable[[dict], None]] = None

    def register_network_callback(self, callback: Callable[[dict], None]):
        """
        Connects gossip manager to the underlying network transport layer.
        """
        self.network_send_cb = callback

    def process_incoming_gossip(self, message: dict):
        """
        Receives and stores peer resource information in the local load table.
        """
        if message.get("message_type") != "GOSSIP_RESOURCE_METRICS":
            return

        payload = message.get("payload", {})
        if not payload:
            return

        status = ResourceStatus.from_dict(payload)
        
        # Store or update peer metrics into local peer load table
        self.peer_load_table[status.node_id] = status
        logging.info(
            f"[Week 2] Updated Load Table for Peer [{status.node_id}] -> "
            f"CPU: {status.cpu_percent}% | RAM: {status.ram_percent}%"
        )

    def clean_stale_entries(self):
        """
        Removes stale peer entries from load table if last timestamp update > ttl_seconds.
        """
        current_time = time.time()
        stale_nodes = [
            node_id for node_id, status in self.peer_load_table.items()
            if (current_time - status.timestamp) > self.ttl_seconds
        ]
        for node_id in stale_nodes:
            del self.peer_load_table[node_id]
            logging.warning(f"[Week 2] Removed stale peer [{node_id}] (No updates for > {self.ttl_seconds}s).")

    async def start_gossip_loop(self):
        """
        Asyncio background loop running every ~5 seconds.
        """
        self._is_running = True
        logging.info(f"[Week 2] Started Gossip Loop for Node [{self.node_id}] (Interval: {self.gossip_interval}s)")

        while self._is_running:
            try:
                # 1. Update own status in local peer load table
                local_status = self.monitor.collect_metrics()
                self.peer_load_table[self.node_id] = local_status

                # 2. Build gossip message
                gossip_msg = GossipMessageBuilder.build_resource_message(local_status)

                # 3. Broadcast to network via callback
                if self.network_send_cb:
                    self.network_send_cb(gossip_msg)

                # 4. Clean stale entries
                self.clean_stale_entries()

            except Exception as e:
                logging.error(f"Error in gossip loop for Node [{self.node_id}]: {e}")

            await asyncio.sleep(self.gossip_interval)

    def stop(self):
        """Stops the gossip loop."""
        self._is_running = False
        logging.info(f"[Week 2] Stopped Gossip Loop for Node [{self.node_id}]")
