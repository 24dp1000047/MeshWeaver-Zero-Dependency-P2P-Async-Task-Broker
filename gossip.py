from typing import Dict, Any
from meshweaver.monitoring import ResourceStatus

class GossipMessageBuilder:
    """
    Defines network message formats for resource updates.
    """
    @staticmethod
    def build_resource_message(status: ResourceStatus) -> Dict[str, Any]:
        return {
            "message_type": "GOSSIP_RESOURCE_METRICS",
            "sender_id": status.node_id,
            "payload": status.to_dict()
        } 
import asyncio
import logging
from typing import Dict, Any, Optional
from meshweaver.monitoring import ResourceStatus, ResourceMonitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class GossipMessageBuilder:
    """
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
                self.latest_status = self.monitor.collect_metrics()
                msg = GossipMessageBuilder.build_resource_message(self.latest_status)
                logging.info(
                    f"Collected Metrics -> CPU: {self.latest_status.cpu_percent}% | "
                    f"RAM: {self.latest_status.ram_percent}%"
                )
            except Exception as e:
                logging.error(f"Error in background monitoring loop: {e}")

            await asyncio.sleep(self.interval)

    def stop(self):
        self._is_running = False
        logging.info(f"[Week 1] Stopped Resource Monitor for Node: {self.node_id}")
