# MeshWeaver

## Zero-Dependency P2P Async Task Broker

MeshWeaver is a decentralized, pure-Python P2P task broker designed for distributed systems and edge-computing environments.

The project aims to allow independent nodes to communicate directly without depending on a central broker such as Redis or RabbitMQ.

## Current Development Status

### Day 1 — Async Networking Foundation

The initial project structure and basic networking-related components have been created.

### Completed

- Project repository structure
- Python package structure
- Basic `Node` class
- Common message protocol foundation
- JSON message encoding and decoding

## Current Project Structure

```text
MeshWeaver-Zero-Dependency-P2P-Async-Task-Broker/
│
├── meshweaver/
│   ├── __init__.py
│   ├── node.py
│   └── protocol.py
│
├── tests/
├── examples/
├── requirements.txt
├── readme.md
└── .gitignore
```

## Node

The basic `Node` class stores the identity and network address of a peer.

```python
class Node:
    def __init__(self, node_id, host, port):
        self.node_id = node_id
        self.host = host
        self.port = port
```

A node currently contains:

- `node_id` — identifier of the node
- `host` — network host/address
- `port` — network port

## Message Protocol

A common message format has been prepared so that MeshWeaver modules can communicate using a consistent structure.

Example:

```json
{
  "type": "PING",
  "sender_id": "node_a"
}
```

The protocol currently provides functions for:

- Creating messages
- Encoding messages into bytes
- Decoding received bytes into Python objects

Initial message types:

- `PING`
- `PONG`

Additional message types such as `FIND_NODE`, `TASK`, `TASK_RESULT`, and `GOSSIP` will be added during later development.

## Planned Architecture

MeshWeaver will use:

- **asyncio** — asynchronous networking
- **UDP/TCP** — peer-to-peer communication
- **Kademlia/DHT** — decentralized peer discovery
- **cloudpickle** — Python function serialization
- **Gossip protocol** — CPU/RAM information sharing

## Two-Week Development Plan

### Week 1

**Prateek — Async Networking**
- Asyncio UDP server/client
- Node communication
- PING/PONG handling
- Common message protocol
- Multi-node networking tests

**Varad — Kademlia/DHT**
- Node IDs
- Routing table
- Known peers
- FIND_NODE
- Peer discovery

**Tejas — Task Execution**
- cloudpickle
- Function and argument serialization
- Task messages
- Remote task execution
- Task results and errors

**Sahil — Gossip & Monitoring**
- CPU/RAM monitoring
- psutil
- Resource messages
- Gossip protocol
- Peer load information

### Week 2

The four modules will be completed and tested together.

Target:

1. Discover peers
2. Share CPU/RAM information
3. Send serialized Python tasks
4. Execute tasks remotely
5. Return task results
6. Demonstrate the system with approximately 5–10 local nodes

## Git Workflow

Each team member works on a separate feature branch.

```text
main
├── feature/prateek-async-networking
├── feature/varad-dht
├── feature/tejas-task-execution
└── feature/sahil-gossip
```

The `main` branch will contain the stable merged project.

### Current Branch

```text
feature/prateek-async-networking
```

### Current Commit

```text
Add basic node and message protocol
```

## Future Scope

The following features are planned for later stages and are not part of the current Day 1 implementation:

- Lowest-CPU task routing
- Heartbeat-based failure detection
- Automatic task reassignment
- TLS/SSL communication
- Cryptographic task signatures
- Rich CLI dashboard
