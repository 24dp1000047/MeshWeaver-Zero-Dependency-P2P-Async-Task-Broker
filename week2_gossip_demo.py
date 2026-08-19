import asyncio
from meshweaver.gossip import GossipManager

async def run_week2_demo():
    print("==========================================================")
    print(" MeshWeaver - Week 2 Multi-Node Gossip & Load Table Demo")
    print("==========================================================\n")

    # 1. Create two simulated nodes (2-second interval for fast demo)
    node1 = GossipManager(node_id="Node-101", gossip_interval=2.0)
    node2 = GossipManager(node_id="Node-102", gossip_interval=2.0)

    # 2. Connect networking callbacks (simulates network sending/receiving)
    node1.register_network_callback(lambda msg: node2.process_incoming_gossip(msg))
    node2.register_network_callback(lambda msg: node1.process_incoming_gossip(msg))

    # 3. Start async gossip loops
    task1 = asyncio.create_task(node1.start_gossip_loop())
    task2 = asyncio.create_task(node2.start_gossip_loop())

    # 4. Run gossip exchange for 5 seconds
    await asyncio.sleep(5.0)

    print("\n--- Peer Load Table at Node-101 ---")
    for nid, status in node1.peer_load_table.items():
        print(f"Peer: {nid} | CPU: {status.cpu_percent}% | RAM: {status.ram_percent}%")

    print("\n--- Peer Load Table at Node-102 ---")
    for nid, status in node2.peer_load_table.items():
        print(f"Peer: {nid} | CPU: {status.cpu_percent}% | RAM: {status.ram_percent}%")

    # Clean stop
    node1.stop()
    node2.stop()
    task1.cancel()
    task2.cancel()

if __name__ == "__main__":
    asyncio.run(run_week2_demo())
