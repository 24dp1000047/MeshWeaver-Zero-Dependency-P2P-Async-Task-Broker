import pytest
import time
from meshweaver.heartbeat import HeartbeatManager, NodeState


def test_heartbeat_ingestion():
    hb = HeartbeatManager("node-main", suspect_timeout=1.0, offline_timeout=2.0)
    msg = {
        "message_type": "HEARTBEAT_PING",
        "sender_id": "node-worker",
        "timestamp": time.time()
    }
    
    hb.process_incoming_heartbeat(msg)
    
    assert "node-worker" in hb.last_seen
    assert hb.peer_states["node-worker"] == NodeState.ALIVE


def test_offline_state_transition():
    hb = HeartbeatManager("node-main", suspect_timeout=0.2, offline_timeout=0.5)
    failed = []
    hb.register_offline_callback(lambda nid: failed.append(nid))

    hb.last_seen["node-dead"] = time.time() - 0.6
    hb.peer_states["node-dead"] = NodeState.ALIVE

    hb.check_node_health()

    assert hb.peer_states["node-dead"] == NodeState.OFFLINE
    assert "node-dead" in failed
