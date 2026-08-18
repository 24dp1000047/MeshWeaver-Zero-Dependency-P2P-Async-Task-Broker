import pytest
import time
from meshweaver.monitoring import ResourceStatus
from meshweaver.gossip import GossipManager, GossipMessageBuilder

def test_peer_load_table_ingestion():
    manager = GossipManager(node_id="Node-A")
    
    # Fake gossip update from Node-B
    status_b = ResourceStatus(node_id="Node-B", cpu_percent=25.0, ram_percent=60.0, timestamp=time.time())
    msg = GossipMessageBuilder.build_resource_message(status_b)
    
    manager.process_incoming_gossip(msg)
    
    assert "Node-B" in manager.peer_load_table
    assert manager.peer_load_table["Node-B"].cpu_percent == 25.0

def test_stale_peer_cleanup():
    manager = GossipManager(node_id="Node-A", ttl_seconds=2.0)
    
    # Old/stale entry (> 2.0s old)
    old_status = ResourceStatus(node_id="Node-Dead", cpu_percent=10.0, ram_percent=20.0, timestamp=time.time() - 5.0)
    manager.peer_load_table["Node-Dead"] = old_status

    # Trigger TTL cleanup
    manager.clean_stale_entries()
    
    assert "Node-Dead" not in manager.peer_load_table
