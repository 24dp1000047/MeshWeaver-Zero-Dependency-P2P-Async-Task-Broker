import time
import asyncio
import logging
from .monitoring import ResourceMonitor

logger = logging.getLogger("meshweaver.gossip")


class GossipMessageBuilder:
    @staticmethod
    def build_status_msg(status):
        return {
            "type": "GOSSIP_RESOURCE_UPDATE",
            "data": status.to_dict()
        }


class BackgroundMonitorLoop:
    def __init__(self, monitor, interval=3.0):
        self.monitor = monitor
        self.interval = interval
        self.running = False
        self.latest = None

    async def start(self, callback=None):
        self.running = True
        while self.running:
            try:
                self.latest = self.monitor.collect()
                if callback:
                    callback(self.latest)
            except Exception as e:
                logger.error(f"Error reading metrics: {e}")
            await asyncio.sleep(self.interval)

    def stop(self):
        self.running = False


class GossipManager:
    def __init__(self, node_id, monitor_interval=3.0, ttl=15.0):
        self.node_id = node_id
        self.ttl = ttl
        self.monitor = ResourceMonitor(node_id)
        self.loop_runner = BackgroundMonitorLoop(self.monitor, monitor_interval)
        
        self.peer_table = {}
        self.transport_cb = None

    def set_transport(self, cb):
        self.transport_cb = cb

    def handle_incoming_gossip(self, msg):
        if not isinstance(msg, dict) or msg.get("type") != "GOSSIP_RESOURCE_UPDATE":
            return

        payload = msg.get("data")
        if not payload or payload.get("node_id") == self.node_id:
            return

        peer_id = payload["node_id"]
        self.peer_table[peer_id] = payload

    def cleanup_stale_peers(self):
        now = time.time()
        expired = [
            pid for pid, info in self.peer_table.items()
            if now - info.get("timestamp", 0) > self.ttl
        ]
        for pid in expired:
            del self.peer_table[pid]

    async def broadcast_loop(self, broadcast_interval=5.0):
        asyncio.create_task(self.loop_runner.start(self._on_local_update))
        
        while True:
            self.cleanup_stale_peers()
            if self.loop_runner.latest and self.transport_cb:
                msg = GossipMessageBuilder.build_status_msg(self.loop_runner.latest)
                try:
                    self.transport_cb(msg)
                except Exception as err:
                    logger.warning(f"Broadcast failed: {err}")
            await asyncio.sleep(broadcast_interval)

    def _on_local_update(self, status):
        self.peer_table[self.node_id] = status.to_dict()
