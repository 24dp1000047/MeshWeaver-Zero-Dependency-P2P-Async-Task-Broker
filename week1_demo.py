import asyncio
from meshweaver.gossip import BackgroundMonitorLoop

async def run_week1_demo():
    print("=== MeshWeaver Week 1 Monitoring Demo ===")
    monitor_loop = BackgroundMonitorLoop(node_id="Node-Sahil-01", interval=1.5)
    task = asyncio.create_task(monitor_loop.start())
    
    await asyncio.sleep(5.0)
    
    monitor_loop.stop()
    task.cancel()

if __name__ == "__main__":
    asyncio.run(run_week1_demo())
