import asyncio
import time

from meshweaver.dht import PeerInfo, PeerTable
from meshweaver.execution import TaskManager, COMPLETED, RETRY
from meshweaver.monitoring import HeartbeatMonitor, OFFLINE
from meshweaver.protocol import create_task_route_request, sign_message, verify_message_signature
from meshweaver.routing import PeerLoad, select_lowest_load
from meshweaver.security import NodeIdentity


def test_lowest_load_ignores_offline_and_source():
    peers = [
        PeerLoad("source", 1, "127.0.0.1", 1, "ALIVE"),
        PeerLoad("offline", 2, "127.0.0.1", 2, "OFFLINE"),
        PeerLoad("node-b", 17, "127.0.0.1", 3, "ALIVE"),
        PeerLoad("node-c", 9, "127.0.0.1", 4, "ALIVE"),
    ]
    assert select_lowest_load(peers, "source").node_id == "node-c"


def test_peer_table_kademlia_closest():
    table = PeerTable()
    for i in range(5):
        table.upsert(PeerInfo(f"node-{i}", "127.0.0.1", i + 1))
    result = table.find_closest("node-2", 2)
    assert len(result) == 2


def test_hmac_identity_and_tamper_detection():
    identity = NodeIdentity("node-a", b"shared-secret")
    msg = create_task_route_request("node-a", "task-1")
    signed = identity.sign(msg)
    assert identity.verify(signed)
    signed["payload"]["task_id"] = "tampered"
    assert not identity.verify(signed)


def test_secure_task_validation():
    manager = TaskManager("node-b")
    identity = NodeIdentity("node-a", b"shared-secret")
    message = identity.sign({"type": "TASK_SUBMIT", "sender_id": "node-a", "payload": {"task_id": "t1"}})
    assert manager.validate_signed_task(message, b"shared-secret")["task_id"] == "t1"

    message["payload"]["task_id"] = "evil"
    try:
        manager.validate_signed_task(message, b"shared-secret")
        assert False, "tampered message must fail"
    except PermissionError:
        pass


def test_task_execution_and_duplicate_result_guard():
    async def run():
        manager = TaskManager("node-b")
        manager.register("add", lambda a, b: a + b)
        task = manager.create("add", (2, 5), task_id="t1")
        result = await manager.execute(task)
        assert result["result"] == 7
        assert manager.tasks["t1"].state == COMPLETED
        assert manager.accept_result("t1", 7)
        assert not manager.accept_result("t1", 7)
        manager.mark_for_retry("t1")
        assert manager.tasks["t1"].state == RETRY

    asyncio.run(run())


def test_heartbeat_marks_stale_peer_offline():
    monitor = HeartbeatMonitor(type("N", (), {})(), timeout=0.1)
    monitor.update("node-b", 20, 30, ("127.0.0.1", 1))
    monitor.peers["node-b"]["last_seen"] = time.time() - 1
    assert monitor.check_once()["node-b"] == OFFLINE
