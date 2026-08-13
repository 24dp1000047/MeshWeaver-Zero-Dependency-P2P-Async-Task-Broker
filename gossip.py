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
