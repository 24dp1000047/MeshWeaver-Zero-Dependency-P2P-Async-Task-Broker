import pytest
import time
from meshweaver.monitoring import ResourceMonitor, ResourceStatus
from meshweaver.gossip import GossipMessageBuilder

def test_resource_status_serialization():
    status = ResourceStatus(node_id="test-node-1", cpu_percent=12.5, ram_percent=40.0, timestamp=time.time())
    data = status.to_dict()
    assert data["node_id"] == "test-node-1"
    
    reconstructed = ResourceStatus.from_dict(data)
    assert reconstructed.cpu_percent == 12.5

def test_resource_monitor_collection():
    monitor = ResourceMonitor(node_id="test-node-1")
    status = monitor.collect_metrics()
    assert status.node_id == "test-node-1"
    assert 0.0 <= status.ram_percent <= 100.0

def test_gossip_message_builder():
    status = ResourceStatus(node_id="test-node-1", cpu_percent=15.0, ram_percent=50.0, timestamp=time.time())
    msg = GossipMessageBuilder.build_resource_message(status)
    assert msg["message_type"] == "GOSSIP_RESOURCE_METRICS"
    assert msg["sender_id"] == "test-node-1"
