import pytest
import time
from meshweaver.monitoring import ResourceMonitor, ResourceStatus


def test_resource_status_serialization():
    status = ResourceStatus("test-node", 15.5, 42.0, time.time())
    data = status.to_dict()
    
    assert data["node_id"] == "test-node"
    assert data["cpu_percent"] == 15.5

    reconstructed = ResourceStatus.from_dict(data)
    assert reconstructed.node_id == status.node_id
    assert reconstructed.ram_percent == status.ram_percent


def test_resource_monitor_collect():
    monitor = ResourceMonitor("node-01")
    res = monitor.collect()
    
    assert res.node_id == "node-01"
    assert isinstance(res.cpu_percent, float)
    assert isinstance(res.ram_percent, float)
