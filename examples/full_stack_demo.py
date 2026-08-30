"""Demonstrate the Week 3/4 integration path with 5 local nodes.

Run:
    python -m examples.full_stack_demo
"""
import asyncio
import time

from meshweaver.dht import PeerInfo, PeerTable
from meshweaver.execution import TaskManager
from meshweaver.monitoring import HeartbeatMonitor
from meshweaver.node import Node
from meshweaver.security import NodeIdentity


async def main():
    nodes = [
        Node("node-1", "127.0.0.1", 9001, cpu_load=31),
        Node("node-2", "127.0.0.1", 9002, cpu_load=18),
        Node("node-3", "127.0.0.1", 9003, cpu_load=9),
        Node("node-4", "127.0.0.1", 9004, cpu_load=24),
        Node("node-5", "127.0.0.1", 9005, cpu_load=14),
    ]
    table = PeerTable()
    for n in nodes:
        table.upsert(PeerInfo(n.node_id, n.host, n.port, n.cpu_load, n.ram_percent, n.state, time.time()))

    selected = table.lowest_load("node-1")
    print(f"1. Lowest-load selection: {selected.node_id} ({selected.cpu_load:.1f}% CPU)")

    manager = TaskManager(selected.node_id)
    manager.register("multiply", lambda a, b: a * b)
    task = manager.create("multiply", (6, 7), task_id="task-001")
    print("2. Task created: task-001")

    identity = NodeIdentity("node-1", b"meshweaver-demo-secret")
    signed_request = identity.sign({
        "type": "TASK_SUBMIT",
        "sender_id": "node-1",
        "payload": {"task_id": task["task_id"]},
    })
    print("3. Signature valid:", identity.verify(signed_request))

    monitor = HeartbeatMonitor(nodes[0], timeout=0.2)
    monitor.update(selected.node_id, selected.cpu_load, 0.0, (selected.host, selected.port))

    # Simulate the selected worker disappearing.
    table.peers[selected.node_id].state = "OFFLINE"
    monitor.peers[selected.node_id]["last_seen"] = time.time() - 1
    print("4. Worker stopped -> heartbeat:", monitor.check_once())

    manager.mark_for_retry(task["task_id"])
    replacement = table.lowest_load("node-1")
    if replacement is None:
        raise RuntimeError("No healthy replacement node available")
    manager.node_id = replacement.node_id
    result = await manager.execute(task)
    print(f"5. Re-routed to {replacement.node_id}: result={result['result']}")
    print("6. Final flow: detect failure -> retry -> select replacement -> execute")


if __name__ == "__main__":
    asyncio.run(main())
