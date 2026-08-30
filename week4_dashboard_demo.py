import asyncio
import random
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel

console = Console()


def make_nodes_table(nodes):
    t = Table(title="Topology & Node Metrics", expand=True)
    t.add_column("Node ID", style="cyan")
    t.add_column("State", style="bold")
    t.add_column("CPU %", justify="right")
    t.add_column("RAM %", justify="right")
    t.add_column("Details")

    for n in nodes:
        col = "green" if n["status"] == "ALIVE" else ("yellow" if n["status"] == "SUSPECTED" else "red")
        t.add_row(
            n["id"],
            f"[{col}]{n['status']}[/{col}]",
            f"{n['cpu']:.1f}",
            f"{n['ram']:.1f}",
            n["info"]
        )
    return t


def make_tasks_table(tasks):
    t = Table(title="Task Queue Status", expand=True)
    t.add_column("Task ID", style="yellow")
    t.add_column("Assigned Node", style="cyan")
    t.add_column("Status", style="bold")
    t.add_column("Message")

    for item in tasks:
        col = "green" if item["state"] == "COMPLETED" else ("red" if item["state"] == "FAILED" else "blue")
        t.add_row(
            item["id"],
            item["node"],
            f"[{col}]{item['state']}[/{col}]",
            item["msg"]
        )
    return t


async def main():
    nodes = [
        {"id": "node-101", "status": "ALIVE", "cpu": 12.0, "ram": 45.0, "info": "Leader"},
        {"id": "node-102", "status": "ALIVE", "cpu": 8.5, "ram": 32.0, "info": "Worker"},
        {"id": "node-103", "status": "ALIVE", "cpu": 75.0, "ram": 60.0, "info": "Worker"},
        {"id": "node-104", "status": "SUSPECTED", "cpu": 0.0, "ram": 0.0, "info": "Timeout"},
    ]

    tasks = [
        {"id": "task-01", "node": "node-102", "state": "RUNNING", "msg": "Processing payload..."},
        {"id": "task-02", "node": "node-103", "state": "COMPLETED", "msg": "Done in 1.2s"},
        {"id": "task-03", "node": "node-104", "state": "FAILED", "msg": "Node unreachable, re-routing"},
    ]

    view = Layout()
    view.split(
        Layout(name="head", size=3),
        Layout(name="body")
    )
    view["head"].update(Panel("[bold green]MeshWeaver - CLI Monitoring Dashboard[/bold green]", align="center"))

    with Live(view, refresh_per_second=2):
        for _ in range(8):
            for n in nodes:
                if n["status"] == "ALIVE":
                    n["cpu"] = random.uniform(5.0, 35.0)
                    n["ram"] = random.uniform(25.0, 50.0)
            
            content = Layout()
            content.split_row(
                Layout(make_nodes_table(nodes)),
                Layout(make_tasks_table(tasks))
            )
            view["body"].update(content)
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
