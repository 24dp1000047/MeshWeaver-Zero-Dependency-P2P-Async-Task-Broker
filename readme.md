# MeshWeaver

## Zero-Dependency P2P Async Task Broker

MeshWeaver is a decentralized, pure-Python peer-to-peer task broker built around `asyncio`. The current implementation now covers the Week 3–4 development plan: intelligent routing, load-aware node selection, authenticated task requests, heartbeat failure detection, task recovery, TLS transport, and a live dashboard with a terminal fallback.

## Architecture

```text
Gossip / Peer Table
       |
       v
Lowest CPU Selection
       |
       v
TASK_ROUTE_REQUEST <----> ROUTE_CANDIDATE_RESPONSE
       |
       v
TLS-secured peer transport
       |
       v
Signed / validated task
       |
       v
Task execution + result
       |
       +---- heartbeat failure ----> RETRY ----> select replacement
                                      |
                                      v
                                  CLI dashboard
```

## Completed Week 3–4 Features

### Prateek — Async Networking & Security Transport
- `TASK_ROUTE_REQUEST`, `ROUTE_CANDIDATE_RESPONSE`, and `ROUTE_DECISION`
- UUID request/response correlation
- configurable routing timeouts
- asyncio UDP control-plane networking
- heartbeat messages on the async transport
- TLS 1.2+ TCP transport in `meshweaver/secure_network.py`
- certificate/key configuration helpers

### Varad — DHT / Node Selection
- peer/load table
- stale/offline filtering
- lowest-CPU selection
- deterministic tie-breaking
- Kademlia-style XOR-distance closest-peer lookup
- authenticated node identity using HMAC-SHA256 (zero external dependencies)

### Tejas — Execution & Fault Tolerance
- task lifecycle: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `RETRY`
- task tracking and executing-node ownership
- async/sync task execution
- duplicate result protection
- signed task validation before execution
- malformed task metadata rejection

### Sahil — Monitoring & CLI
- `ALIVE` / `SUSPECTED` / `OFFLINE` health model
- heartbeat timestamps and stale-peer detection
- CPU/RAM fields with optional `psutil` enhancement
- Rich dashboard when Rich is installed
- zero-dependency text dashboard fallback

## Run Tests

```bash
python -m pytest -q
```

The current test suite covers protocol metadata, encode/decode, request correlation, UDP routing, timeouts, load selection, DHT lookup, signatures/tampering, secure task validation, task execution, duplicate-result prevention, and heartbeat failure detection.

## Run the 5-node integration demo

```bash
python examples/full_stack_demo.py
```

The demo shows:

1. lowest-load node selection,
2. task creation,
3. request signing and verification,
4. selected-worker failure detection,
5. retry state,
6. replacement-node selection,
7. successful re-execution.

## TLS Setup

TLS is implemented separately from the UDP discovery/control plane because TLS is a stream transport. Generate development certificates with:

Windows PowerShell:

```powershell
.\scripts\generate_certs.ps1
```

Linux/macOS:

```bash
./scripts/generate_certs.sh
```

Then create contexts with `create_server_context()` and `create_client_context()` from `meshweaver.secure_network` and use `start_tls_server()` / `SecureNetworkProtocol.connect()`.

**Development certificates are for local testing only.** For deployment, use certificates issued by a trusted CA and keep private keys outside the repository.

## Zero-dependency policy

The core implementation uses Python's standard library. `Rich` and `psutil` are optional: the dashboard falls back to plain terminal output and resource values fall back to `0.0` when those packages are unavailable.

## 📊 Sahil — Gossip & Monitoring Track Progress

### Completed Features (Week 1 & Week 2)
- **Resource Monitoring:** System CPU and RAM metrics collection using `psutil` inside `monitoring.py`.
- **Resource Data Schema:** Standardized `ResourceStatus` dataclass with JSON serialization/deserialization.
- **Background Async Loop:** Non-blocking `BackgroundMonitorLoop` collecting system metrics periodically.
- **Gossip Protocol & Load Table:** Periodic (~5s) broadcast management via `GossipManager` in `gossip.py`.
- **Peer Load Tracking:** Maintenance of local `peer_load_table` mapping active peers to their latest resource metrics.
- **Stale Node Cleanup:** TTL-based expiration for inactive peers (auto-removal if update > TTL threshold).
- **Network Integration:** Callback hook `register_network_callback()` connecting gossip manager to network transport.

### Running Track Demos
```bash
# Week 1 Demo (Local Resource Collection)
python examples/week1_demo.py

# Week 2 Demo (Multi-Node Gossip & Peer Load Table Exchange)
python examples/week2_gossip_demo.py
```
