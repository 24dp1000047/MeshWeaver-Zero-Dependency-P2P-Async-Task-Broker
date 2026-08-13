"""
tests/test_routing_table.py — Tests for the basic DHT routing-table structure.

Scope (Commit 2):
    - KademliaContact
    - KBucket
    - RoutingTable

Run with:
    python -m pytest tests/test_routing_table.py -v
"""

import pytest

from meshweaver.kademlia.node_id import generate_node_id
from meshweaver.kademlia.routing_table import (
    DEFAULT_K,
    KBucket,
    KademliaContact,
    RoutingTable,
)


# ===========================================================================
# Helpers
# ===========================================================================


def make_id(seed: str) -> bytes:
    """Shorthand: SHA-256 of *seed*."""
    return generate_node_id(seed)


def make_contact(seed: str, host: str = "127.0.0.1", port: int = 5000) -> KademliaContact:
    return KademliaContact(make_id(seed), host, port)


# ===========================================================================
# KademliaContact
# ===========================================================================


class TestKademliaContact:
    def test_construction(self):
        nid = make_id("node-a")
        c = KademliaContact(nid, "10.0.0.1", 4000)
        assert c.node_id == nid
        assert c.host == "10.0.0.1"
        assert c.port == 4000

    def test_invalid_node_id_length_raises(self):
        with pytest.raises(ValueError):
            KademliaContact(b"\x00" * 10, "localhost", 1234)

    def test_invalid_port_zero_raises(self):
        with pytest.raises(ValueError):
            KademliaContact(make_id("x"), "localhost", 0)

    def test_invalid_port_too_large_raises(self):
        with pytest.raises(ValueError):
            KademliaContact(make_id("x"), "localhost", 65536)

    def test_equality_by_node_id(self):
        nid = make_id("same")
        c1 = KademliaContact(nid, "host-a", 1000)
        c2 = KademliaContact(nid, "host-b", 2000)
        assert c1 == c2

    def test_inequality_different_ids(self):
        c1 = make_contact("alpha")
        c2 = make_contact("beta")
        assert c1 != c2

    def test_hashable(self):
        c = make_contact("hashable")
        s = {c}  # must not raise
        assert c in s


# ===========================================================================
# KBucket
# ===========================================================================


class TestKBucket:
    def test_starts_empty(self):
        b = KBucket()
        assert len(b) == 0
        assert not b.is_full

    def test_add_contact(self):
        b = KBucket()
        c = make_contact("p1")
        result = b.add_contact(c)
        assert result is True
        assert len(b) == 1

    def test_add_duplicate_moves_to_tail(self):
        b = KBucket()
        c1 = make_contact("p1")
        c2 = make_contact("p2")
        b.add_contact(c1)
        b.add_contact(c2)
        # Re-add c1 — should move to tail
        b.add_contact(c1)
        assert b.contacts[-1] == c1
        assert len(b) == 2  # no duplicate entries

    def test_is_full_when_k_reached(self):
        k = 3
        b = KBucket(k=k)
        for i in range(k):
            b.add_contact(make_contact(f"peer-{i}", port=5000 + i))
        assert b.is_full

    def test_add_contact_when_full_returns_false(self):
        k = 2
        b = KBucket(k=k)
        b.add_contact(make_contact("p1", port=5001))
        b.add_contact(make_contact("p2", port=5002))
        result = b.add_contact(make_contact("p3", port=5003))
        assert result is False
        assert len(b) == k

    def test_remove_contact_present(self):
        b = KBucket()
        c = make_contact("remove-me")
        b.add_contact(c)
        assert b.remove_contact(c.node_id) is True
        assert len(b) == 0

    def test_remove_contact_absent(self):
        b = KBucket()
        assert b.remove_contact(make_id("ghost")) is False

    def test_get_contact_found(self):
        b = KBucket()
        c = make_contact("found")
        b.add_contact(c)
        assert b.get_contact(c.node_id) == c

    def test_get_contact_not_found(self):
        b = KBucket()
        assert b.get_contact(make_id("missing")) is None


# ===========================================================================
# RoutingTable
# ===========================================================================


class TestRoutingTable:
    def setup_method(self):
        self.local_id = make_id("local-node")
        self.rt = RoutingTable(self.local_id)

    def test_initial_state_empty(self):
        assert len(self.rt) == 0
        assert self.rt.get_all_contacts() == []

    def test_add_and_retrieve_single_contact(self):
        c = make_contact("peer-1", port=5001)
        assert self.rt.add_contact(c) is True
        assert self.rt.get_contact(c.node_id) == c

    def test_multiple_peers_stored(self):
        contacts = [make_contact(f"peer-{i}", port=5000 + i) for i in range(5)]
        for c in contacts:
            self.rt.add_contact(c)
        assert len(self.rt) == 5

    def test_get_all_contacts(self):
        c1 = make_contact("a", port=5001)
        c2 = make_contact("b", port=5002)
        self.rt.add_contact(c1)
        self.rt.add_contact(c2)
        all_contacts = self.rt.get_all_contacts()
        assert c1 in all_contacts
        assert c2 in all_contacts

    def test_remove_contact(self):
        c = make_contact("to-remove", port=5005)
        self.rt.add_contact(c)
        assert self.rt.remove_contact(c.node_id) is True
        assert self.rt.get_contact(c.node_id) is None

    def test_remove_nonexistent_contact(self):
        assert self.rt.remove_contact(make_id("ghost")) is False

    def test_adding_local_node_raises(self):
        local_contact = KademliaContact(self.local_id, "127.0.0.1", 5000)
        with pytest.raises(ValueError, match="local node"):
            self.rt.add_contact(local_contact)

    def test_invalid_local_id_length_raises(self):
        with pytest.raises(ValueError):
            RoutingTable(b"\x00" * 10)

    def test_get_nonexistent_contact_returns_none(self):
        assert self.rt.get_contact(make_id("nobody")) is None

    def test_bucket_for_returns_correct_bucket(self):
        c = make_contact("bucket-test", port=5009)
        self.rt.add_contact(c)
        bucket = self.rt.bucket_for(c.node_id)
        assert isinstance(bucket, KBucket)
        assert c in bucket.contacts

    def test_routing_table_has_256_buckets(self):
        """Internal bucket list must have exactly 256 slots (one per ID bit)."""
        assert len(self.rt._buckets) == 256

    def test_contacts_land_in_valid_bucket_indices(self):
        """Bucket index for any peer must fall within [0, 255]."""
        c1 = make_contact("distinct-1", port=5001)
        c2 = make_contact("distinct-2", port=5002)
        self.rt.add_contact(c1)
        self.rt.add_contact(c2)
        assert 0 <= self.rt._bucket_index(c1.node_id) < 256
        assert 0 <= self.rt._bucket_index(c2.node_id) < 256

    def test_custom_k_is_respected(self):
        k = 3
        rt = RoutingTable(self.local_id, k=k)
        for i in range(50):
            rt.add_contact(make_contact(f"bulk-{i}", port=5000 + i))
        for bucket in rt._buckets:
            assert len(bucket) <= k

    def test_refresh_existing_contact(self):
        """Re-adding an existing contact returns True (refresh, not duplicate)."""
        c = make_contact("refresh-me", port=5010)
        self.rt.add_contact(c)
        assert self.rt.add_contact(c) is True
        assert len(self.rt) == 1  # still just one entry

    def test_len_reflects_total_contacts(self):
        n = 10
        for i in range(n):
            self.rt.add_contact(make_contact(f"cnt-{i}", port=5000 + i))
        assert len(self.rt) == n
