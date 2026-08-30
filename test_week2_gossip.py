import pytest
import time
from meshweaver.gossip import GossipManager


def test_gossip_ingestion_and_stale_cleanup():
    mgr = GossipManager("node-main", ttl=1.0)
    
    # 1. Simulate incoming gossip from remote node
    msg = {
        "type": "GOSSIP_RESOURCE_UPDATE",
        "data": {
            "node_id": "node-peer-1",
            "cpu_percent": 25.0,
            "ram_percent": 60.0,
            "timestamp": time.time()
        }
    }
    
    mgr.handle_incoming_gossip(msg)
    assert "node-peer-1" in mgr.peer_table
    assert mgr.peer_table["node-peer-1"]["cpu_percent"] == 25.0

    # 2. Simulate stale timestamp and cleanup
    mgr.peer_table["node-peer-1"]["timestamp"] = time.time() - 2.0
    mgr.cleanup_stale_peers()
    
    assert "node-peer-1" not in mgr.peer_table
