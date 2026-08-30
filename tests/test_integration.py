"""
tests/test_integration.py — Multi-node integration tests for the Kademlia DHT layer.

These tests spin up 5-10 fully in-process simulated nodes, wire them together
using injected send_recv callables (no real sockets), and verify:

* Multi-node discovery / connectivity
    - A new node can join a ring of existing nodes and discover remote peers.
    - Discovered contacts are reachable via PeerLookup on the joining node.
    - Two independent nodes can bootstrap from the same peer and see each other.

* Routing / lookup behaviour
    - After multi-hop discovery, PeerLookup returns contacts sorted by XOR
      distance (closest first).
    - A node that is the lookup target appears in the closest-contacts list.
    - PeerLookup results are bounded by k across all tested topologies.

* Routing-table / PeerStore consistency across nodes
    - After a full bootstrap + discovery pass every peer-store record in every
      node has a corresponding routing-table entry and vice versa.
    - No k-bucket ever exceeds its capacity k.

* Failure / inactive-peer scenarios
    - Contacts that fail to respond during discover() are NOT inserted into the
      routing table.
    - After a peer is explicitly removed (PeerStore.remove), it is absent
      from both the routing table and the peer-store record index.
    - Replacing a dead bootstrap peer with a live one completes the join
      successfully.
    - A full discovery round that encounters a mix of live and dead contacts
      adds only the live ones.

Run with:
    python -m pytest tests/test_integration.py -v
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pytest

from meshweaver.kademlia.bootstrap import BootstrapClient, BootstrapError
from meshweaver.kademlia.discovery import PeerDiscovery
from meshweaver.kademlia.lookup import PeerLookup
from meshweaver.kademlia.node_id import generate_node_id, node_id_to_hex, xor_distance
from meshweaver.kademlia.peer_store import PeerStore
from meshweaver.kademlia.routing_table import KademliaContact
from meshweaver.kademlia.rpc import FindNodeHandler, PingValidator
from meshweaver.protocol import MSG_FIND_NODE, MSG_PING, decode_message


# ---------------------------------------------------------------------------
# Helpers — simulated in-process nodes
# ---------------------------------------------------------------------------


class SimNode:
    """A fully simulated Kademlia node with no real networking.

    Each node owns a PeerStore, a PingValidator, and a FindNodeHandler.
    The handle() method acts as the "network endpoint": callers pass encoded
    request bytes and get encoded reply bytes back, exactly as a real network
    transport would.
    """

    def __init__(self, seed: str, host: str = "127.0.0.1", port: int = 5000) -> None:
        self.node_id: bytes = generate_node_id(seed)
        self.node_id_hex: str = node_id_to_hex(self.node_id)
        self.host = host
        self.port = port
        self.peer_store = PeerStore(self.node_id)
        self._ping_validator = PingValidator(self.node_id_hex)
        self._find_node_handler = FindNodeHandler(self.node_id_hex)

    # ------------------------------------------------------------------
    # Simulated network endpoint
    # ------------------------------------------------------------------

    def handle(self, request_bytes: bytes) -> bytes:
        """Dispatch an encoded request and return the encoded reply."""
        msg = decode_message(request_bytes)
        if msg["type"] == MSG_PING:
            return self._ping_validator.handle_ping(request_bytes)
        if msg["type"] == MSG_FIND_NODE:
            _, response = self._find_node_handler.handle_request(
                request_bytes, self.peer_store
            )
            return response
        raise ValueError(f"SimNode: unknown message type {msg['type']!r}")

    # ------------------------------------------------------------------
    # Convenience wrappers mirroring BootstrapClient / PeerDiscovery API
    # ------------------------------------------------------------------

    def bootstrap_join(
        self,
        bootstrap_node: "SimNode",
        provide_id: bool = True,
    ) -> List[KademliaContact]:
        """Join the DHT by contacting bootstrap_node directly."""
        client = BootstrapClient(
            local_id_hex=self.node_id_hex,
            peer_store=self.peer_store,
            ping_validator=PingValidator(self.node_id_hex),
            find_node_handler=FindNodeHandler(self.node_id_hex),
        )
        bs_id = bootstrap_node.node_id if provide_id else None
        return client.join(
            bootstrap_host=bootstrap_node.host,
            bootstrap_port=bootstrap_node.port,
            send_recv=bootstrap_node.handle,
            bootstrap_node_id=bs_id,
        )

    def discover_from(
        self,
        contacts: List[KademliaContact],
        network: "Dict[bytes, SimNode]",
    ) -> List[KademliaContact]:
        """Fan-out FIND_NODE queries to contacts using network for routing."""

        def _send_recv_for(c: KademliaContact) -> Callable[[bytes], bytes]:
            node = network.get(c.node_id)
            if node is None:
                def _dead(_r: bytes) -> bytes:
                    raise OSError("peer not in network")
                return _dead
            return node.handle

        disc = PeerDiscovery(
            local_id_hex=self.node_id_hex,
            peer_store=self.peer_store,
            find_node_handler=FindNodeHandler(self.node_id_hex),
        )
        return disc.discover(contacts, send_recv_for=_send_recv_for)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def as_contact(self) -> KademliaContact:
        return KademliaContact(self.node_id, self.host, self.port)

    def lookup(self, target_id: bytes, k: int = 20) -> List[KademliaContact]:
        return PeerLookup(self.peer_store.routing_table, k=k).find_closest(target_id)

    def knows(self, node: "SimNode") -> bool:
        return self.peer_store.contains(node.node_id)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"SimNode({self.node_id_hex[:8]}, peers={self.peer_store.peer_count()})"
        )


def _make_network(*seeds: str) -> Dict[bytes, SimNode]:
    """Create a dict of SimNodes keyed by node_id from seed strings."""
    nodes: Dict[bytes, SimNode] = {}
    for i, seed in enumerate(seeds):
        n = SimNode(seed, host="127.0.0.1", port=5000 + i)
        nodes[n.node_id] = n
    return nodes


def _assert_store_table_consistent(node: SimNode) -> None:
    """Assert that the PeerStore and RoutingTable of node are fully in sync."""
    for record in node.peer_store.all_peers():
        assert node.peer_store.routing_table.get_contact(record.node_id) is not None, (
            f"Node {node.node_id_hex[:8]}: peer-store record "
            f"{record.node_id.hex()[:8]} has no routing-table entry"
        )
    for contact in node.peer_store.routing_table.get_all_contacts():
        assert node.peer_store.contains(contact.node_id), (
            f"Node {node.node_id_hex[:8]}: routing-table contact "
            f"{contact.node_id.hex()[:8]} not in peer-store"
        )


def _assert_no_bucket_overflow(node: SimNode) -> None:
    """Assert no k-bucket exceeds its capacity."""
    k = node.peer_store.routing_table.k
    for bucket in node.peer_store.routing_table._buckets:
        assert len(bucket) <= k, (
            f"Bucket overflow: {len(bucket)} > {k}"
        )


# ===========================================================================
# Test class 1: 5-node star topology
# ===========================================================================


class TestFiveNodeStarTopology:
    """A hub node knows 4 spokes; a fresh node bootstraps from the hub and
    then fans out FIND_NODE queries to discover all spokes."""

    SEEDS = [
        "integ-hub:6000",
        "integ-spoke-0:6001",
        "integ-spoke-1:6002",
        "integ-spoke-2:6003",
        "integ-spoke-3:6004",
    ]

    @pytest.fixture()
    def hub_and_spokes(self):
        network = _make_network(*self.SEEDS)
        nodes = list(network.values())
        hub = nodes[0]
        spokes = nodes[1:]
        # Pre-populate hub with all spoke contacts.
        for spoke in spokes:
            hub.peer_store.add_or_update(spoke.node_id, spoke.host, spoke.port)
        return hub, spokes, network

    @pytest.fixture()
    def new_node(self):
        return SimNode("integ-new-node:7000", port=7000)

    def test_new_node_knows_hub_after_bootstrap(self, hub_and_spokes, new_node):
        """Bootstrapping from the hub must add the hub to the new node's store."""
        hub, spokes, network = hub_and_spokes
        new_node.bootstrap_join(hub)
        assert new_node.knows(hub)

    def test_new_node_receives_spoke_contacts_after_bootstrap(
        self, hub_and_spokes, new_node
    ):
        """All spoke contacts in hub's store must appear in the join() result."""
        hub, spokes, network = hub_and_spokes
        bootstrap_result = new_node.bootstrap_join(hub)
        result_ids = {c.node_id for c in bootstrap_result}
        for spoke in spokes:
            assert spoke.node_id in result_ids, (
                f"Spoke {spoke.node_id_hex[:8]} should be in bootstrap result"
            )

    def test_new_node_discovers_spokes_after_discovery_round(
        self, hub_and_spokes, new_node
    ):
        """After bootstrap + discover(), the new node must know all spokes."""
        hub, spokes, network = hub_and_spokes
        bootstrap_result = new_node.bootstrap_join(hub)
        network[new_node.node_id] = new_node
        new_node.discover_from(bootstrap_result, network)
        for spoke in spokes:
            assert new_node.knows(spoke), (
                f"New node should know spoke {spoke.node_id_hex[:8]} after discovery"
            )

    def test_peer_store_and_routing_table_consistent_after_full_pipeline(
        self, hub_and_spokes, new_node
    ):
        """After bootstrap + discover(), peer store and routing table must be in sync."""
        hub, spokes, network = hub_and_spokes
        bootstrap_result = new_node.bootstrap_join(hub)
        network[new_node.node_id] = new_node
        new_node.discover_from(bootstrap_result, network)
        _assert_store_table_consistent(new_node)

    def test_no_bucket_overflow_after_full_pipeline(self, hub_and_spokes, new_node):
        """No k-bucket must overflow after bootstrap + discover()."""
        hub, spokes, network = hub_and_spokes
        bootstrap_result = new_node.bootstrap_join(hub)
        network[new_node.node_id] = new_node
        new_node.discover_from(bootstrap_result, network)
        _assert_no_bucket_overflow(new_node)

    def test_lookup_finds_exact_spoke_by_id(self, hub_and_spokes, new_node):
        """PeerLookup targeting a spoke's exact ID must include that spoke."""
        hub, spokes, network = hub_and_spokes
        bootstrap_result = new_node.bootstrap_join(hub)
        network[new_node.node_id] = new_node
        new_node.discover_from(bootstrap_result, network)
        target_id = spokes[0].node_id
        results = new_node.lookup(target_id, k=20)
        result_ids = {c.node_id for c in results}
        assert target_id in result_ids, (
            "PeerLookup should return the spoke when searched by its exact ID"
        )

    def test_lookup_results_sorted_by_xor_distance(self, hub_and_spokes, new_node):
        """Contacts returned by PeerLookup must be in ascending XOR-distance order."""
        hub, spokes, network = hub_and_spokes
        bootstrap_result = new_node.bootstrap_join(hub)
        network[new_node.node_id] = new_node
        new_node.discover_from(bootstrap_result, network)
        target_id = spokes[1].node_id
        results = new_node.lookup(target_id, k=20)
        distances = [xor_distance(c.node_id, target_id) for c in results]
        assert distances == sorted(distances), (
            "Lookup results must be sorted by ascending XOR distance"
        )


# ===========================================================================
# Test class 2: Two nodes bootstrap from the same hub
# ===========================================================================


class TestTwoNodesBootstrapFromSameHub:
    """Node A and Node B independently bootstrap from a common hub; after
    both have joined and the hub knows both, B can discover A."""

    @pytest.fixture()
    def hub(self):
        return SimNode("integ-shared-hub:6100", port=6100)

    @pytest.fixture()
    def node_a(self):
        return SimNode("integ-node-a:6101", port=6101)

    @pytest.fixture()
    def node_b(self):
        return SimNode("integ-node-b:6102", port=6102)

    def test_node_b_discovers_node_a_via_hub(self, hub, node_a, node_b):
        """After A joins and hub records A, B's discovery round must find A."""
        # A joins first.
        node_a.bootstrap_join(hub)
        # Explicitly register A in hub so hub returns A to later joiners.
        hub.peer_store.add_or_update(node_a.node_id, node_a.host, node_a.port)
        # B joins; hub returns A as a close contact.
        bs_result_b = node_b.bootstrap_join(hub)
        assert node_b.knows(hub)
        network: Dict[bytes, SimNode] = {
            hub.node_id: hub,
            node_a.node_id: node_a,
            node_b.node_id: node_b,
        }
        node_b.discover_from(bs_result_b, network)
        assert node_b.knows(node_a), (
            "Node B should know Node A after discovery from hub that knows A"
        )

    def test_consistency_after_mutual_bootstrap(self, hub, node_a, node_b):
        """Routing tables of both nodes must be consistent after each bootstraps."""
        hub.peer_store.add_or_update(node_a.node_id, node_a.host, node_a.port)
        hub.peer_store.add_or_update(node_b.node_id, node_b.host, node_b.port)
        node_a.bootstrap_join(hub)
        node_b.bootstrap_join(hub)
        _assert_store_table_consistent(node_a)
        _assert_store_table_consistent(node_b)


# ===========================================================================
# Test class 3: 8-node linear chain — multi-hop discovery
# ===========================================================================


class TestEightNodeLinearChain:
    """8 nodes in a chain: n[0] knows n[1], n[1] knows n[2], ..., n[6] knows n[7].
    A fresh node joins n[0] and fans out discover() to reach n[1]."""

    NUM_NODES = 8

    @pytest.fixture()
    def chain(self):
        seeds = [f"integ-chain-{i}:62{i:02d}" for i in range(self.NUM_NODES)]
        network = _make_network(*seeds)
        nodes = list(network.values())
        # Wire each node to know its right-hand neighbour only.
        for i in range(len(nodes) - 1):
            nodes[i].peer_store.add_or_update(
                nodes[i + 1].node_id, nodes[i + 1].host, nodes[i + 1].port
            )
        return nodes, network

    def test_new_node_learns_n1_via_n0_bootstrap_and_discovery(self, chain):
        """A new node bootstrapping from n[0] must know n[1] after one discover()."""
        nodes, network = chain
        new_node = SimNode("integ-chain-new:6300", port=6300)
        bootstrap_result = new_node.bootstrap_join(nodes[0])
        network[new_node.node_id] = new_node
        new_node.discover_from(bootstrap_result, network)
        # n[1] was in n[0]'s FIND_NODE response.
        assert new_node.knows(nodes[1]), (
            "New node should know n[1] after one bootstrap+discovery from n[0]"
        )

    def test_chain_nodes_have_consistent_routing_tables(self, chain):
        """Every pre-wired chain node must have a consistent store+table."""
        nodes, _ = chain
        for node in nodes:
            _assert_store_table_consistent(node)

    def test_peer_lookup_bounded_by_k_in_chain(self, chain):
        """PeerLookup(k=3) must never return more than 3 contacts."""
        nodes, network = chain
        new_node = SimNode("integ-chain-kbound:6301", port=6301)
        k = 3
        bootstrap_result = new_node.bootstrap_join(nodes[0])
        network[new_node.node_id] = new_node
        new_node.discover_from(bootstrap_result, network)
        target_id = nodes[-1].node_id
        results = PeerLookup(new_node.peer_store.routing_table, k=k).find_closest(
            target_id
        )
        assert len(results) <= k, (
            f"PeerLookup must return at most k={k} contacts, got {len(results)}"
        )


# ===========================================================================
# Test class 4: Failure and inactive-peer scenarios
# ===========================================================================


class TestFailureAndInactivePeerScenarios:
    """Verify correct behaviour when bootstrap peers are dead, contacts fail
    during discovery, or peers are explicitly removed."""

    @pytest.fixture()
    def local_node(self):
        return SimNode("integ-fail-local:6400", port=6400)

    @pytest.fixture()
    def live_hub(self):
        n = SimNode("integ-fail-hub-live:6401", port=6401)
        # Pre-populate hub so it returns contacts during FIND_NODE.
        for i in range(3):
            cid = generate_node_id(f"integ-fail-hub-peer-{i}:6500")
            n.peer_store.add_or_update(cid, "10.0.0.1", 6500 + i)
        return n

    def test_dead_bootstrap_peer_raises_bootstrap_error(self, local_node):
        """A dead bootstrap transport must raise BootstrapError immediately."""
        def _dead(_req: bytes) -> bytes:
            raise OSError("connection refused")

        client = BootstrapClient(
            local_id_hex=local_node.node_id_hex,
            peer_store=local_node.peer_store,
            ping_validator=PingValidator(local_node.node_id_hex),
            find_node_handler=FindNodeHandler(local_node.node_id_hex),
        )
        with pytest.raises(BootstrapError):
            client.join("dead.host", 9999, _dead)

    def test_dead_discovery_contact_not_inserted_into_routing_table(
        self, local_node, live_hub
    ):
        """A contact that raises during discover() must not appear in the table."""
        local_node.bootstrap_join(live_hub)
        dead_id = generate_node_id("integ-fail-dead-contact:9000")
        dead_contact = KademliaContact(dead_id, "10.99.99.99", 9000)

        def _send_recv_for(c: KademliaContact) -> Callable[[bytes], bytes]:
            def _dead(_r: bytes) -> bytes:
                raise OSError("unreachable")
            return _dead

        disc = PeerDiscovery(
            local_id_hex=local_node.node_id_hex,
            peer_store=local_node.peer_store,
            find_node_handler=FindNodeHandler(local_node.node_id_hex),
        )
        disc.discover([dead_contact], send_recv_for=_send_recv_for)
        assert local_node.peer_store.routing_table.get_contact(dead_id) is None
        assert not local_node.peer_store.contains(dead_id)

    def test_removed_peer_absent_from_store_and_table(self, local_node, live_hub):
        """After PeerStore.remove(), the peer must vanish from both data stores."""
        local_node.bootstrap_join(live_hub)
        hub_id = live_hub.node_id
        assert local_node.peer_store.contains(hub_id)
        local_node.peer_store.remove(hub_id)
        assert not local_node.peer_store.contains(hub_id)
        assert local_node.peer_store.routing_table.get_contact(hub_id) is None

    def test_mixed_live_dead_discover_adds_only_live_contacts(
        self, local_node, live_hub
    ):
        """Live contacts in a mixed discover() round must be stored; dead ones must not."""
        live_extra = SimNode("integ-fail-live-extra:6402", port=6402)
        dead_id = generate_node_id("integ-fail-dead-extra:9001")
        dead_contact = KademliaContact(dead_id, "10.88.88.88", 9001)

        network: Dict[bytes, SimNode] = {live_extra.node_id: live_extra}
        local_node.bootstrap_join(live_hub)

        def _send_recv_for(c: KademliaContact) -> Callable[[bytes], bytes]:
            if c.node_id == dead_id:
                def _dead(_r: bytes) -> bytes:
                    raise OSError("dead")
                return _dead
            node = network.get(c.node_id)
            if node:
                return node.handle
            def _fallback(_r: bytes) -> bytes:
                raise OSError("unknown")
            return _fallback

        disc = PeerDiscovery(
            local_id_hex=local_node.node_id_hex,
            peer_store=local_node.peer_store,
            find_node_handler=FindNodeHandler(local_node.node_id_hex),
        )
        disc.discover(
            [live_extra.as_contact(), dead_contact], send_recv_for=_send_recv_for
        )
        assert local_node.peer_store.contains(live_extra.node_id), (
            "Live extra contact should be in peer store after discover()"
        )
        assert not local_node.peer_store.contains(dead_id), (
            "Dead contact must NOT be in peer store after failed discover()"
        )

    def test_consistency_after_remove_then_readd(self, local_node, live_hub):
        """Remove a peer, re-add it; store+table must stay consistent throughout."""
        local_node.bootstrap_join(live_hub)
        hub_id = live_hub.node_id
        local_node.peer_store.remove(hub_id)
        _assert_store_table_consistent(local_node)
        local_node.peer_store.add_or_update(hub_id, live_hub.host, live_hub.port)
        _assert_store_table_consistent(local_node)
        assert local_node.peer_store.contains(hub_id)
        assert local_node.peer_store.routing_table.get_contact(hub_id) is not None

    def test_bootstrap_dead_then_live_peer_succeeds(self, local_node):
        """After a failed bootstrap attempt, a subsequent attempt with a live
        peer must complete and leave the store consistent."""
        live_node = SimNode("integ-fail-live-boot:6403", port=6403)

        def _dead(_req: bytes) -> bytes:
            raise OSError("first peer is dead")

        client = BootstrapClient(
            local_id_hex=local_node.node_id_hex,
            peer_store=local_node.peer_store,
            ping_validator=PingValidator(local_node.node_id_hex),
            find_node_handler=FindNodeHandler(local_node.node_id_hex),
        )
        # First attempt must fail with no side effects.
        with pytest.raises(BootstrapError):
            client.join("dead.host", 9998, _dead)
        assert local_node.peer_store.peer_count() == 0

        # Second attempt with a live peer must succeed.
        client.join(
            live_node.host,
            live_node.port,
            live_node.handle,
            bootstrap_node_id=live_node.node_id,
        )
        assert local_node.peer_store.contains(live_node.node_id)
        _assert_store_table_consistent(local_node)


# ===========================================================================
# Test class 5: 10-node full-mesh via central coordinator
# ===========================================================================


class TestTenNodeFullMeshViaCoordinator:
    """10 nodes all bootstrap from a coordinator that knows all of them.
    After the round, each peer must know the coordinator and have a consistent
    routing table; no bucket must overflow."""

    NUM_PEERS = 10

    @pytest.fixture()
    def coordinator_and_peers(self):
        coord = SimNode("integ-coord:6600", port=6600)
        peers = [
            SimNode(f"integ-mesh-peer-{i}:66{i + 1:02d}", port=6600 + i + 1)
            for i in range(self.NUM_PEERS)
        ]
        # Coordinator knows all peers upfront.
        for p in peers:
            coord.peer_store.add_or_update(p.node_id, p.host, p.port)
        return coord, peers

    def test_all_peers_know_coordinator_after_bootstrap(self, coordinator_and_peers):
        """Every peer must have the coordinator in its store after joining."""
        coord, peers = coordinator_and_peers
        for peer in peers:
            peer.bootstrap_join(coord)
        for peer in peers:
            assert peer.knows(coord), (
                f"Peer {peer.node_id_hex[:8]} should know coordinator after bootstrap"
            )

    def test_all_peers_have_consistent_routing_tables(self, coordinator_and_peers):
        """Every peer's routing table must be consistent with its peer store."""
        coord, peers = coordinator_and_peers
        for peer in peers:
            peer.bootstrap_join(coord)
        for peer in peers:
            _assert_store_table_consistent(peer)

    def test_no_bucket_overflow_in_ten_node_mesh(self, coordinator_and_peers):
        """No k-bucket must overflow when 10 nodes bootstrap from the coordinator."""
        coord, peers = coordinator_and_peers
        for peer in peers:
            peer.bootstrap_join(coord)
        for peer in peers:
            _assert_no_bucket_overflow(peer)

    def test_coordinator_lookup_bounded_by_k(self, coordinator_and_peers):
        """PeerLookup(k=5) on the coordinator must return at most 5 contacts."""
        coord, peers = coordinator_and_peers
        k = 5
        target_id = peers[0].node_id
        results = PeerLookup(coord.peer_store.routing_table, k=k).find_closest(
            target_id
        )
        assert len(results) <= k, (
            f"Coordinator lookup must be bounded by k={k}, got {len(results)}"
        )

    def test_coordinator_routing_table_consistent_throughout(
        self, coordinator_and_peers
    ):
        """Coordinator's own routing table must stay consistent as peers join."""
        coord, peers = coordinator_and_peers
        for peer in peers:
            peer.bootstrap_join(coord)
        _assert_store_table_consistent(coord)
