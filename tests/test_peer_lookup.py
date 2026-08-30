"""
tests/test_peer_lookup.py - Focused tests for Commit 6: Peer Lookup.

Covers:
    - PeerLookup construction (happy path and invalid k).
    - find_closest() with empty table, single peer, multiple peers.
    - Results are sorted by XOR distance (closest first).
    - k cap is respected.
    - target_id == local_node_id still works (returns known peers sorted by
      distance to that ID).
    - Short target_id raises ValueError.
    - find_closest_hex() convenience wrapper (round-trip with raw bytes).
    - k and routing_table properties.

Run with:
    python -m pytest tests/test_peer_lookup.py -v
"""

import pytest

from meshweaver.kademlia.node_id import (
    generate_node_id,
    node_id_to_hex,
    xor_distance,
)
from meshweaver.kademlia.routing_table import KademliaContact, RoutingTable
from meshweaver.kademlia.lookup import PeerLookup


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LOCAL_SEED = "lookup-local:5000"
TARGET_SEED = "lookup-target:9999"


@pytest.fixture()
def local_id() -> bytes:
    return generate_node_id(LOCAL_SEED)


@pytest.fixture()
def target_id() -> bytes:
    return generate_node_id(TARGET_SEED)


@pytest.fixture()
def target_id_hex(target_id) -> str:
    return node_id_to_hex(target_id)


@pytest.fixture()
def empty_rt(local_id) -> RoutingTable:
    """A RoutingTable with no contacts."""
    return RoutingTable(local_id)


@pytest.fixture()
def single_peer_rt(local_id) -> RoutingTable:
    """A RoutingTable with exactly one peer."""
    rt = RoutingTable(local_id)
    peer_id = generate_node_id("127.0.0.1:5001")
    rt.add_contact(KademliaContact(peer_id, "127.0.0.1", 5001))
    return rt


def _make_rt_with_peers(local_id: bytes, count: int) -> RoutingTable:
    """Return a RoutingTable populated with *count* distinct peers."""
    rt = RoutingTable(local_id)
    for i in range(count):
        nid = generate_node_id(f"peer-seed-{i}:600{i}")
        rt.add_contact(KademliaContact(nid, f"10.0.0.{i}", 6000 + i))
    return rt


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestPeerLookupConstruction:
    def test_default_k_is_twenty(self, empty_rt):
        lookup = PeerLookup(empty_rt)
        assert lookup.k == 20

    def test_custom_k_stored(self, empty_rt):
        lookup = PeerLookup(empty_rt, k=5)
        assert lookup.k == 5

    def test_k_zero_raises(self, empty_rt):
        with pytest.raises(ValueError, match="k must be at least 1"):
            PeerLookup(empty_rt, k=0)

    def test_k_negative_raises(self, empty_rt):
        with pytest.raises(ValueError):
            PeerLookup(empty_rt, k=-1)

    def test_routing_table_property(self, empty_rt):
        lookup = PeerLookup(empty_rt)
        assert lookup.routing_table is empty_rt


# ---------------------------------------------------------------------------
# find_closest - basic behaviour
# ---------------------------------------------------------------------------


class TestFindClosestBasic:
    def test_empty_table_returns_empty_list(self, empty_rt, target_id):
        lookup = PeerLookup(empty_rt)
        result = lookup.find_closest(target_id)
        assert result == []

    def test_returns_list(self, single_peer_rt, target_id):
        lookup = PeerLookup(single_peer_rt)
        result = lookup.find_closest(target_id)
        assert isinstance(result, list)

    def test_single_peer_found(self, local_id, single_peer_rt, target_id):
        lookup = PeerLookup(single_peer_rt)
        result = lookup.find_closest(target_id)
        assert len(result) == 1

    def test_single_peer_is_kademlia_contact(self, single_peer_rt, target_id):
        lookup = PeerLookup(single_peer_rt)
        result = lookup.find_closest(target_id)
        assert isinstance(result[0], KademliaContact)

    def test_local_node_never_in_results(self, local_id, empty_rt, target_id):
        """The local node is never stored in the routing table, so it
        must never appear in results."""
        lookup = PeerLookup(empty_rt)
        results = lookup.find_closest(target_id)
        for c in results:
            assert c.node_id != local_id

    def test_short_target_id_raises(self, empty_rt):
        with pytest.raises(ValueError):
            PeerLookup(empty_rt).find_closest(b"\x00" * 16)  # too short

    def test_empty_target_id_raises(self, empty_rt):
        with pytest.raises(ValueError):
            PeerLookup(empty_rt).find_closest(b"")

    def test_target_equals_known_peer(self, local_id):
        """Lookup with the target == a stored peer's ID returns that peer first."""
        rt = RoutingTable(local_id)
        peer_id = generate_node_id("exact-match-peer:7000")
        rt.add_contact(KademliaContact(peer_id, "1.2.3.4", 7000))
        lookup = PeerLookup(rt)
        results = lookup.find_closest(peer_id)
        assert len(results) == 1
        assert results[0].node_id == peer_id


# ---------------------------------------------------------------------------
# find_closest - k cap
# ---------------------------------------------------------------------------


class TestFindClosestKCap:
    def test_k_cap_respected(self, local_id, target_id):
        rt = _make_rt_with_peers(local_id, count=10)
        lookup = PeerLookup(rt, k=3)
        result = lookup.find_closest(target_id)
        assert len(result) <= 3

    def test_k_larger_than_peers_returns_all(self, local_id, target_id):
        rt = _make_rt_with_peers(local_id, count=4)
        lookup = PeerLookup(rt, k=20)
        result = lookup.find_closest(target_id)
        assert len(result) == 4

    def test_k_one_returns_single_closest(self, local_id, target_id):
        rt = _make_rt_with_peers(local_id, count=6)
        lookup = PeerLookup(rt, k=1)
        result = lookup.find_closest(target_id)
        assert len(result) == 1

    def test_k_equals_peer_count(self, local_id, target_id):
        rt = _make_rt_with_peers(local_id, count=5)
        lookup = PeerLookup(rt, k=5)
        result = lookup.find_closest(target_id)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# find_closest - XOR ordering
# ---------------------------------------------------------------------------


class TestFindClosestOrdering:
    def test_sorted_closest_first(self, local_id, target_id):
        rt = _make_rt_with_peers(local_id, count=8)
        lookup = PeerLookup(rt, k=8)
        results = lookup.find_closest(target_id)

        distances = [xor_distance(c.node_id, target_id) for c in results]
        assert distances == sorted(distances), \
            "Results must be sorted by XOR distance (ascending)"

    def test_closest_is_genuinely_closest(self, local_id, target_id):
        """The first result must be the globally closest contact."""
        rt = _make_rt_with_peers(local_id, count=10)
        all_contacts = rt.get_all_contacts()
        expected_closest = min(
            all_contacts, key=lambda c: xor_distance(c.node_id, target_id)
        )
        lookup = PeerLookup(rt, k=10)
        results = lookup.find_closest(target_id)
        assert results[0].node_id == expected_closest.node_id

    def test_two_peers_ordered_by_distance(self, local_id, target_id):
        """With two peers, the closer one must come first."""
        rt = RoutingTable(local_id)
        id_a = generate_node_id("peer-alpha:6000")
        id_b = generate_node_id("peer-beta:6001")
        rt.add_contact(KademliaContact(id_a, "10.0.0.1", 6000))
        rt.add_contact(KademliaContact(id_b, "10.0.0.2", 6001))

        lookup = PeerLookup(rt, k=2)
        results = lookup.find_closest(target_id)
        assert len(results) == 2

        d0 = xor_distance(results[0].node_id, target_id)
        d1 = xor_distance(results[1].node_id, target_id)
        assert d0 <= d1

    def test_k_truncation_keeps_closest(self, local_id, target_id):
        """When k < total peers, the returned contacts are the k closest."""
        rt = _make_rt_with_peers(local_id, count=10)
        all_contacts = rt.get_all_contacts()
        all_contacts.sort(key=lambda c: xor_distance(c.node_id, target_id))
        expected_ids = {c.node_id for c in all_contacts[:3]}

        lookup = PeerLookup(rt, k=3)
        results = lookup.find_closest(target_id)
        result_ids = {c.node_id for c in results}
        assert result_ids == expected_ids


# ---------------------------------------------------------------------------
# find_closest_hex - convenience wrapper
# ---------------------------------------------------------------------------


class TestFindClosestHex:
    def test_empty_table_returns_empty_list(self, empty_rt, target_id_hex):
        lookup = PeerLookup(empty_rt)
        assert lookup.find_closest_hex(target_id_hex) == []

    def test_same_result_as_find_closest(self, local_id, target_id, target_id_hex):
        rt = _make_rt_with_peers(local_id, count=6)
        lookup = PeerLookup(rt, k=6)
        by_bytes = lookup.find_closest(target_id)
        by_hex = lookup.find_closest_hex(target_id_hex)
        assert [c.node_id for c in by_bytes] == [c.node_id for c in by_hex]

    def test_bad_hex_raises(self, empty_rt):
        with pytest.raises(ValueError):
            PeerLookup(empty_rt).find_closest_hex("not-valid-hex!!!")

    def test_short_hex_raises(self, empty_rt):
        # Only 8 hex chars (4 bytes) — too short
        with pytest.raises(ValueError):
            PeerLookup(empty_rt).find_closest_hex("deadbeef")

    def test_sorted_closest_first_hex(self, local_id, target_id, target_id_hex):
        rt = _make_rt_with_peers(local_id, count=8)
        lookup = PeerLookup(rt, k=8)
        results = lookup.find_closest_hex(target_id_hex)
        distances = [xor_distance(c.node_id, target_id) for c in results]
        assert distances == sorted(distances)


# ---------------------------------------------------------------------------
# Integration: PeerLookup with PeerStore routing table
# ---------------------------------------------------------------------------


class TestPeerLookupWithPeerStore:
    """Verify PeerLookup works when handed PeerStore.routing_table."""

    def test_lookup_via_peer_store_routing_table(self, local_id, target_id):
        from meshweaver.kademlia.peer_store import PeerStore

        store = PeerStore(local_id)
        for i in range(5):
            nid = generate_node_id(f"store-peer-{i}:700{i}")
            store.add_or_update(nid, f"192.168.1.{i}", 7000 + i)

        lookup = PeerLookup(store.routing_table, k=3)
        results = lookup.find_closest(target_id)
        assert len(results) <= 3

    def test_lookup_reflects_store_contents(self, local_id, target_id):
        from meshweaver.kademlia.peer_store import PeerStore

        store = PeerStore(local_id)
        specific_id = generate_node_id("specific-peer:8888")
        store.add_or_update(specific_id, "172.16.0.1", 8888)

        lookup = PeerLookup(store.routing_table)
        results = lookup.find_closest(target_id)
        result_ids = [c.node_id for c in results]
        assert specific_id in result_ids

    def test_removed_peer_not_in_lookup(self, local_id, target_id):
        from meshweaver.kademlia.peer_store import PeerStore

        store = PeerStore(local_id)
        nid = generate_node_id("removable-peer:9000")
        store.add_or_update(nid, "172.16.0.2", 9000)
        store.remove(nid)

        lookup = PeerLookup(store.routing_table)
        results = lookup.find_closest(target_id)
        result_ids = [c.node_id for c in results]
        assert nid not in result_ids
