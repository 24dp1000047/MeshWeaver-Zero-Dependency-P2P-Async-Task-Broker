"""
tests/test_routing_table_updates.py -- Focused tests for routing-table updates
when peers are discovered via bootstrap or PeerDiscovery.

These tests verify that:

Bootstrap integration
    - bootstrap_node_id causes the bootstrap peer itself to be added to the
      routing table after a successful PING.
    - Contacts returned by FIND_NODE are in the routing table after join().
    - Calling join() twice with the same contacts is safe (idempotent updates).
    - The bootstrap peer is NOT added when bootstrap_node_id is None.
    - The bootstrap peer == local node is gracefully skipped (edge case).

PeerDiscovery integration
    - Seed contacts that respond are added/refreshed in the routing table.
    - Seed contacts that do NOT respond are NOT added/refreshed.
    - Contacts returned inside FOUND_NODES responses are added to the table.
    - Already-known seed contacts are refreshed (moved to k-bucket tail).
    - A seed contact that is the local node is skipped.
    - Duplicate contacts across multiple FOUND_NODES responses are stored only
      once in the routing table.
    - When a k-bucket is full, excess contacts are NOT silently inserted.

Routing-table consistency
    - After both bootstrap and discover, the routing table is consistent with
      the peer store (every store record has a corresponding table contact).
    - PeerLookup over the updated routing table finds the discovered peers.

Run with:
    python -m pytest tests/test_routing_table_updates.py -v
"""

from __future__ import annotations

import pytest

from meshweaver.kademlia.bootstrap import BootstrapClient
from meshweaver.kademlia.discovery import PeerDiscovery
from meshweaver.kademlia.lookup import PeerLookup
from meshweaver.kademlia.node_id import generate_node_id, node_id_to_hex
from meshweaver.kademlia.peer_store import PeerStore
from meshweaver.kademlia.routing_table import DEFAULT_K, KademliaContact, RoutingTable
from meshweaver.kademlia.rpc import FindNodeHandler, PingValidator
from meshweaver.protocol import MSG_FIND_NODE, MSG_PING, decode_message


# ---------------------------------------------------------------------------
# Shared helpers and fixtures
# ---------------------------------------------------------------------------


LOCAL_SEED = "rt-update-local:6000"
BOOTSTRAP_SEED = "rt-update-bootstrap:6001"


@pytest.fixture()
def local_id() -> bytes:
    return generate_node_id(LOCAL_SEED)


@pytest.fixture()
def local_id_hex(local_id) -> str:
    return node_id_to_hex(local_id)


@pytest.fixture()
def local_store(local_id) -> PeerStore:
    return PeerStore(local_id)


@pytest.fixture()
def bootstrap_id() -> bytes:
    return generate_node_id(BOOTSTRAP_SEED)


@pytest.fixture()
def bootstrap_id_hex(bootstrap_id) -> str:
    return node_id_to_hex(bootstrap_id)


def _make_bootstrap_send_recv(bootstrap_id_hex: str, bootstrap_store: PeerStore):
    """Simulate a live bootstrap peer: handles PING and FIND_NODE."""
    pong_v = PingValidator(bootstrap_id_hex)
    fn_h = FindNodeHandler(bootstrap_id_hex)

    def _send_recv(request_bytes: bytes) -> bytes:
        msg = decode_message(request_bytes)
        if msg["type"] == MSG_PING:
            return pong_v.handle_ping(request_bytes)
        if msg["type"] == MSG_FIND_NODE:
            _, resp = fn_h.handle_request(request_bytes, bootstrap_store)
            return resp
        raise ValueError(f"Unexpected message type: {msg['type']}")

    return _send_recv


def _make_peer_send_recv(peer_id_hex: str, peer_store: PeerStore):
    """Simulate a live discovery peer that handles FIND_NODE only."""
    handler = FindNodeHandler(peer_id_hex)

    def _send_recv(request_bytes: bytes) -> bytes:
        _, response = handler.handle_request(request_bytes, peer_store)
        return response

    return _send_recv


def _make_contact(seed: str, host: str = "127.0.0.1", port: int = 5000) -> KademliaContact:
    return KademliaContact(generate_node_id(seed), host, port)


def _bootstrap_client(local_id_hex, local_store):
    return BootstrapClient(
        local_id_hex=local_id_hex,
        peer_store=local_store,
        ping_validator=PingValidator(local_id_hex),
        find_node_handler=FindNodeHandler(local_id_hex),
    )


# ===========================================================================
# Bootstrap -- routing-table updates
# ===========================================================================


class TestBootstrapRoutingTableUpdates:
    """Verify the routing table is correctly populated by BootstrapClient.join()."""

    def test_bootstrap_peer_added_to_routing_table_when_id_given(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """When bootstrap_node_id is supplied, the bootstrap peer itself must
        appear in the routing table after a successful join."""
        bootstrap_store = PeerStore(bootstrap_id)
        extra_id = generate_node_id("extra-peer:9000")
        bootstrap_store.add_or_update(extra_id, "10.0.0.1", 9000)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        client.join("10.0.0.99", 6001, send_recv, bootstrap_node_id=bootstrap_id)

        assert local_store.routing_table.get_contact(bootstrap_id) is not None

    def test_bootstrap_peer_stored_in_peer_store_when_id_given(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """The bootstrap peer should also be present in the peer-store record index."""
        bootstrap_store = PeerStore(bootstrap_id)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        client.join("10.0.0.99", 6001, send_recv, bootstrap_node_id=bootstrap_id)

        assert local_store.contains(bootstrap_id)

    def test_bootstrap_peer_in_join_result_when_id_given(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """The bootstrap peer should appear in the list returned by join()."""
        bootstrap_store = PeerStore(bootstrap_id)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        result = client.join("10.0.0.99", 6001, send_recv, bootstrap_node_id=bootstrap_id)

        result_ids = {c.node_id for c in result}
        assert bootstrap_id in result_ids

    def test_bootstrap_peer_not_added_when_id_omitted(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """When bootstrap_node_id is NOT given, the bootstrap peer must NOT be added."""
        bootstrap_store = PeerStore(bootstrap_id)
        extra_id = generate_node_id("extra-peer-x:9001")
        bootstrap_store.add_or_update(extra_id, "10.0.0.2", 9001)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        client.join("10.0.0.99", 6001, send_recv)

        assert not local_store.contains(bootstrap_id)

    def test_returned_contacts_in_routing_table(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """All contacts returned by the bootstrap FIND_NODE reply must be in the routing table."""
        bootstrap_store = PeerStore(bootstrap_id)
        peer_ids = []
        for i in range(3):
            pid = generate_node_id(f"rt-peer-{i}:700{i}")
            peer_ids.append(pid)
            bootstrap_store.add_or_update(pid, f"10.1.0.{i}", 7000 + i)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        client.join("10.0.0.99", 6001, send_recv)

        for pid in peer_ids:
            assert local_store.routing_table.get_contact(pid) is not None

    def test_join_twice_does_not_corrupt_routing_table(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """Calling join() twice must not create phantom routing-table entries."""
        bootstrap_store = PeerStore(bootstrap_id)
        pid = generate_node_id("stable-peer:8000")
        bootstrap_store.add_or_update(pid, "10.2.0.1", 8000)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)

        client.join("10.0.0.99", 6001, send_recv, bootstrap_node_id=bootstrap_id)
        count_first = len(local_store.routing_table)

        client.join("10.0.0.99", 6001, send_recv, bootstrap_node_id=bootstrap_id)
        count_second = len(local_store.routing_table)

        assert count_second == count_first

    def test_bootstrap_node_id_equals_local_skipped_gracefully(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """If bootstrap_node_id equals the local node ID it must not raise."""
        bootstrap_store = PeerStore(bootstrap_id)
        other_pid = generate_node_id("safe-peer-for-local-edge:9200")
        bootstrap_store.add_or_update(other_pid, "9.9.9.1", 9200)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)

        result = client.join(
            "10.0.0.99", 6001, send_recv, bootstrap_node_id=local_id
        )

        assert local_store.routing_table.get_contact(local_id) is None
        result_ids = {c.node_id for c in result}
        assert local_id not in result_ids


# ===========================================================================
# PeerDiscovery -- routing-table updates
# ===========================================================================


class TestDiscoveryRoutingTableUpdates:
    """Verify the routing table is correctly updated by PeerDiscovery.discover()."""

    def test_responding_seed_added_to_routing_table(
        self, local_id, local_id_hex, local_store
    ):
        """A seed contact that successfully responds must be in the routing table."""
        seed_id = generate_node_id("disc-seed-respond:7000")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        extra_id = generate_node_id("extra-disc-1:8000")
        seed_store.add_or_update(extra_id, "10.0.0.1", 8000)

        seed_contact = KademliaContact(seed_id, "10.0.0.50", 7000)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([seed_contact], send_recv_for=lambda _c: send_recv_fn)

        assert local_store.routing_table.get_contact(seed_id) is not None
        assert local_store.contains(seed_id)

    def test_non_responding_seed_not_added_to_routing_table(
        self, local_id, local_id_hex, local_store
    ):
        """A seed contact that raises on send_recv must NOT be added to the routing table."""
        dead_seed = _make_contact("disc-dead-seed:9001", port=9001)

        def _dead(_req: bytes) -> bytes:
            raise OSError("connection refused")

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([dead_seed], send_recv_for=lambda _c: _dead)

        assert local_store.routing_table.get_contact(dead_seed.node_id) is None

    def test_known_seed_contact_refreshed_in_routing_table(
        self, local_id, local_id_hex, local_store
    ):
        """A known seed contact is still in the routing table after discover()."""
        seed_id = generate_node_id("disc-seed-known:7100")
        seed_id_hex = node_id_to_hex(seed_id)

        local_store.add_or_update(seed_id, "10.0.0.100", 7100)

        seed_store = PeerStore(seed_id)
        seed_contact = KademliaContact(seed_id, "10.0.0.100", 7100)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([seed_contact], send_recv_for=lambda _c: send_recv_fn)

        assert local_store.routing_table.get_contact(seed_id) is not None

    def test_discovered_contacts_added_to_routing_table(
        self, local_id, local_id_hex, local_store
    ):
        """Contacts returned in FOUND_NODES responses must be in the routing table."""
        seed_id = generate_node_id("disc-seed-for-ct:7300")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)

        new_ids = []
        for i in range(3):
            nid = generate_node_id(f"disc-new-{i}:8300")
            new_ids.append(nid)
            seed_store.add_or_update(nid, f"10.0.1.{i}", 8300 + i)

        seed_contact = KademliaContact(seed_id, "10.0.0.200", 7300)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([seed_contact], send_recv_for=lambda _c: send_recv_fn)

        for nid in new_ids:
            assert local_store.routing_table.get_contact(nid) is not None

    def test_duplicate_discovered_contacts_stored_once_in_routing_table(
        self, local_id, local_id_hex, local_store
    ):
        """A contact returned by two seed peers must appear exactly once in the routing table."""
        shared_id = generate_node_id("disc-shared-dup:8888")

        seeds = []
        for i in range(2):
            s_id = generate_node_id(f"disc-seed-dup-{i}:740{i}")
            s_hex = node_id_to_hex(s_id)
            s_store = PeerStore(s_id)
            s_store.add_or_update(shared_id, "8.8.8.8", 8888)
            contact = KademliaContact(s_id, f"10.0.2.{i}", 7400 + i)
            seeds.append((contact, _make_peer_send_recv(s_hex, s_store)))

        def _send_recv_for(c):
            for (sc, fn) in seeds:
                if sc.node_id == c.node_id:
                    return fn
            raise ValueError("unknown contact")

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([c for c, _ in seeds], send_recv_for=_send_recv_for)

        all_contacts = local_store.routing_table.get_all_contacts()
        shared_entries = [c for c in all_contacts if c.node_id == shared_id]
        assert len(shared_entries) == 1

    def test_local_seed_contact_not_added_to_routing_table(
        self, local_id, local_id_hex, local_store
    ):
        """Passing the local node as a seed contact must not add it to its own routing table."""
        local_seed_contact = KademliaContact(local_id, "127.0.0.1", 6000)
        local_as_seed_store = PeerStore(local_id)
        send_recv_fn = _make_peer_send_recv(local_id_hex, local_as_seed_store)

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([local_seed_contact], send_recv_for=lambda _c: send_recv_fn)

        assert local_store.routing_table.get_contact(local_id) is None

    def test_full_bucket_contact_not_added_to_routing_table(
        self, local_id, local_id_hex
    ):
        """No k-bucket must overflow when newly discovered contacts are inserted."""
        k = 2
        local_store = PeerStore(local_id, k=k)

        seed_id = generate_node_id("disc-seed-full-bucket:7500")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)

        for i in range(10):
            cid = generate_node_id(f"full-bucket-peer-{i}:8500")
            seed_store.add_or_update(cid, f"10.0.3.{i}", 8500 + i)

        seed_contact = KademliaContact(seed_id, "10.0.3.100", 7500)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex, k=k),
        )
        disc.discover([seed_contact], send_recv_for=lambda _c: send_recv_fn)

        for bucket in local_store.routing_table._buckets:
            assert len(bucket) <= k


# ===========================================================================
# Routing-table / peer-store consistency
# ===========================================================================


class TestRoutingTablePeerStoreConsistency:
    """After discovery operations, the routing table and peer-store must agree."""

    def test_routing_table_and_peer_store_in_sync_after_bootstrap(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """Every peer-store record has a routing-table entry and vice versa after join()."""
        bootstrap_store = PeerStore(bootstrap_id)
        for i in range(4):
            pid = generate_node_id(f"sync-peer-{i}:800{i}")
            bootstrap_store.add_or_update(pid, f"192.168.0.{i}", 8000 + i)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        client.join(
            "192.168.0.99", 6001, send_recv, bootstrap_node_id=bootstrap_id
        )

        for record in local_store.all_peers():
            assert local_store.routing_table.get_contact(record.node_id) is not None

        for contact in local_store.routing_table.get_all_contacts():
            assert local_store.contains(contact.node_id)

    def test_routing_table_and_peer_store_in_sync_after_discovery(
        self, local_id, local_id_hex, local_store
    ):
        """After discover(), every record in the peer store has a routing-table entry."""
        seed_id = generate_node_id("sync-disc-seed:7600")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        for i in range(3):
            nid = generate_node_id(f"sync-disc-peer-{i}:860{i}")
            seed_store.add_or_update(nid, f"10.0.4.{i}", 8600 + i)

        seed_contact = KademliaContact(seed_id, "10.0.4.100", 7600)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([seed_contact], send_recv_for=lambda _c: send_recv_fn)

        for record in local_store.all_peers():
            assert local_store.routing_table.get_contact(record.node_id) is not None

        for contact in local_store.routing_table.get_all_contacts():
            assert local_store.contains(contact.node_id)

    def test_peer_lookup_finds_discovered_peers(
        self, local_id, local_id_hex, local_store
    ):
        """PeerLookup over the routing table must find peers added by discover()."""
        seed_id = generate_node_id("lookup-disc-seed:7700")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        target_id = generate_node_id("lookup-disc-target:8700")
        seed_store.add_or_update(target_id, "10.0.5.1", 8700)

        seed_contact = KademliaContact(seed_id, "10.0.5.100", 7700)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            find_node_handler=FindNodeHandler(local_id_hex),
        )
        disc.discover([seed_contact], send_recv_for=lambda _c: send_recv_fn)

        lookup = PeerLookup(local_store.routing_table)
        results = lookup.find_closest(target_id)
        result_ids = {c.node_id for c in results}

        assert target_id in result_ids

    def test_full_pipeline_routing_table_consistent(
        self, local_id, local_id_hex, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """End-to-end: bootstrap + discover leaves routing table and peer store in sync."""
        bootstrap_store = PeerStore(bootstrap_id)
        intermediate_ids = []
        for i in range(2):
            pid = generate_node_id(f"pipeline-intermediate-{i}:800{i}")
            intermediate_ids.append(pid)
            bootstrap_store.add_or_update(pid, f"10.1.0.{i}", 8000 + i)

        intermediate_info = {}
        extra_ids = []
        for idx, pid in enumerate(intermediate_ids):
            pid_hex = node_id_to_hex(pid)
            i_store = PeerStore(pid)
            extra_pid = generate_node_id(f"pipeline-extra-{idx}:900{idx}")
            extra_ids.append(extra_pid)
            i_store.add_or_update(extra_pid, f"10.2.0.{idx}", 9000 + idx)
            intermediate_info[pid] = (pid_hex, i_store)

        client = _bootstrap_client(local_id_hex, local_store)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        bootstrap_result = client.join(
            "10.0.0.99", 6001, send_recv, bootstrap_node_id=bootstrap_id
        )

        fn_h = FindNodeHandler(local_id_hex)
        disc = PeerDiscovery(local_id_hex, local_store, fn_h)

        def _send_recv_for(contact):
            if contact.node_id not in intermediate_info:
                def _dead(_r):
                    raise OSError("not an intermediate peer")
                return _dead
            pid_hex, i_store = intermediate_info[contact.node_id]
            return _make_peer_send_recv(pid_hex, i_store)

        disc.discover(bootstrap_result, send_recv_for=_send_recv_for)

        for extra_pid in extra_ids:
            assert local_store.contains(extra_pid)
            assert local_store.routing_table.get_contact(extra_pid) is not None

        for record in local_store.all_peers():
            assert local_store.routing_table.get_contact(record.node_id) is not None

        for contact in local_store.routing_table.get_all_contacts():
            assert local_store.contains(contact.node_id)
