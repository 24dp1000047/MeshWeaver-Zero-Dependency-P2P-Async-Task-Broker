"""End-to-end local demo for the Week 3/4 MeshWeaver flow."""
import asyncio
import time

from .dht import PeerInfo, PeerTable
from .execution import TaskManager
from .monitoring import HeartbeatMonitor
from .network import NetworkProtocol
from .node import Node
from .protocol import TASK_ROUTE_REQUEST
from .security import NodeIdentity


async def run_demo():
    nodes = [Node(f"node-{i}", "127.0.0.1", 0, cpu_load=load) for i, load in enumerate((42, 12, 27, 8, 19), 1)]
    transports, networks = [], []
    try:
        for node in nodes:
            loop = asyncio.get_running_loop()
            network = NetworkProtocol(node)
            transport, _ = await loop.create_datagram_endpoint(lambda n=network: n, local_addr=(node.host, 0))
            transports.append(transport)
            networks.append(network)

        table = PeerTable()
        for n in nodes:
            table.upsert(PeerInfo(n.node_id, n.host, n.port, n.cpu_load, n.ram_percent, n.state, time.time()))
        selected = table.lowest_load(source_node="node-1")
        print(f"Selected lowest-load node: {selected.node_id} ({selected.cpu_load:.1f}% CPU)")

        source = networks[0]
        candidate_index = nodes.index(next(n for n in nodes if n.node_id == selected.node_id))
        response = await source.send_task_route_request(
            selected.host, selected.port, task_id="demo-task-001", candidates=[n.node_id for n in nodes], timeout=2
        )
        print("Route response:", response["type"], response["payload"]["candidate_node"])

        # HMAC identity demonstration: invalid/tampered requests are rejected by verification.
        secret = b"demo-shared-secret-change-me"
        identity = NodeIdentity("node-1", secret)
        signed = identity.sign({"type": TASK_ROUTE_REQUEST, "sender_id": "node-1", "payload": {"task_id": "demo-task-001"}})
        print("Signed request verified:", identity.verify(signed))
        signed["payload"]["task_id"] = "tampered"
        print("Tampered request verified:", identity.verify(signed))

        manager = TaskManager(selected.node_id)
        manager.register("add", lambda a, b: a + b)
        task = manager.create("add", (2, 3), task_id="demo-task-001")
        result = await manager.execute(task)
        print("Task result:", result)

        monitor = HeartbeatMonitor(nodes[0], timeout=0.5)
        monitor.update(selected.node_id, selected.cpu_load, selected.ram_percent, (selected.host, selected.port))
        await asyncio.sleep(0.6)
        print("Failure check:", monitor.check_once())
    finally:
        for transport in transports:
            transport.close()
        await asyncio.sleep(0.05)


if __name__ == "__main__":
    asyncio.run(run_demo())
