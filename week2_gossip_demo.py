import asyncio
import time
from meshweaver.gossip import GossipManager


async def run_simulated_mesh():
    node1 = GossipManager("node-1", monitor_interval=1.0)
    node2 = GossipManager("node-2", monitor_interval=1.0)

    # Wire up direct peer message handling
    node1.set_transport(lambda msg: node2.handle_incoming_gossip(msg))
    node2.set_transport(lambda msg: node1.handle_incoming_gossip(msg))

    print("Starting Gossip Simulation between Node-1 and Node-2...")
    
    # Run short broadcast cycles
    t1 = asyncio.create_task(node1.broadcast_loop(broadcast_interval=1.0))
    t2 = asyncio.create_task(node2.broadcast_loop(broadcast_interval=1.0))

    await asyncio.sleep(2.5)

    print("\n--- Node-1 Peer Table View ---")
    print(node1.peer_table)

    print("\n--- Node-2 Peer Table View ---")
    print(node2.peer_table)

    t1.cancel()
    t2.cancel()


if __name__ == "__main__":
    asyncio.run(run_simulated_mesh())
