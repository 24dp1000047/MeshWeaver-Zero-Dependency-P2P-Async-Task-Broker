import asyncio
import os
import time

try:
    from rich.live import Live
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def snapshot(nodes, tasks=None):
    tasks = tasks or {}
    return {
        "nodes": [
            {"node_id": n.node_id, "state": n.state, "cpu": n.cpu_load,
             "ram": n.ram_percent, "last_seen": round(time.time() - n.last_seen, 2)}
            for n in nodes
        ],
        "tasks": tasks,
    }


def render(nodes, tasks=None):
    data = snapshot(nodes, tasks)
    if not RICH_AVAILABLE:
        lines = ["MeshWeaver Network"]
        for n in data["nodes"]:
            lines.append(f"{n['node_id']:<16} {n['state']:<10} CPU {n['cpu']:>5.1f}% RAM {n['ram']:>5.1f}%")
        return "\n".join(lines)
    table = Table(title="MeshWeaver Network")
    for col in ("Node", "State", "CPU", "RAM", "Last Seen"):
        table.add_column(col)
    for n in data["nodes"]:
        table.add_row(n["node_id"], n["state"], f"{n['cpu']:.1f}%", f"{n['ram']:.1f}%", f"{n['last_seen']:.2f}s")
    return table


async def live_dashboard(nodes_provider, tasks_provider=None, refresh=1.0):
    if not RICH_AVAILABLE:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(render(nodes_provider(), tasks_provider() if tasks_provider else {}))
            await asyncio.sleep(refresh)
    else:
        with Live(render(nodes_provider(), tasks_provider() if tasks_provider else {}), refresh_per_second=max(1, int(1 / refresh))) as live:
            while True:
                live.update(render(nodes_provider(), tasks_provider() if tasks_provider else {}))
                await asyncio.sleep(refresh)
