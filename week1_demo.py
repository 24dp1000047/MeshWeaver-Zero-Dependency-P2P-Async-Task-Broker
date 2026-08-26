import asyncio
from meshweaver.monitoring import ResourceMonitor
from meshweaver.gossip import BackgroundMonitorLoop


def print_metrics(status):
    print(f"[{status.node_id}] CPU: {status.cpu_percent}% | RAM: {status.ram_percent}%")


async def main():
    monitor = ResourceMonitor("node-demo-01")
    loop = BackgroundMonitorLoop(monitor, interval=2.0)
    
    print("Starting local resource monitoring demo (Ctrl+C to stop)...")
    
    try:
        await loop.start(callback=print_metrics)
    except KeyboardInterrupt:
        loop.stop()
        print("\nMonitoring stopped.")


if __name__ == "__main__":
    asyncio.run(main())
