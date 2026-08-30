"""
tests/test_peer_store.py — Tests for known-peer management (Commit 3).

Scope:
    - PeerRecord construction and metadata (first_seen / last_seen / touch)
    - PeerStore.add_or_update  (new peers, refresh existing, bucket-full case)
    - PeerStore.get
    - PeerStore.remove
    - PeerStore.contains / __contains__
    - PeerStore.all_peers / peer_count / __len__
    - PeerStore.clear
    - PeerStore.routing_table property
    - Edge cases: local-node rejection, invalid inputs

Run with:
    python -m pytest tests/test_peer_store.py -v
"""

import time

import pytest

from meshweaver.kademlia.node_id import generate_node_id
from meshweaver.kademlia.peer_store import PeerRecord, PeerStore
from meshweaver.kademlia.routing_table import KademliaContact, RoutingTable


# ===========================================================================
# Helpers
# ===========================================================================


def make_id(seed: str) -> bytes:
    """Return the SHA-256 node ID for *seed*."""
    return generate_node_id(seed)


def make_contact(seed: str, host: str = "127.0.0.1", port: int = 5000) -> KademliaContact:
    return KademliaContact(make_id(seed), host, port)


LOCAL_SEED = "local-node"


def fresh_store() -> PeerStore:
    """Return a new PeerStore with a deterministic local ID."""
    return PeerStore(make_id(LOCAL_SEED))


# ===========================================================================
# PeerRecord
# ===========================================================================


class TestPeerRecord:
    def test_construction_sets_contact_and_timestamps(self):
        contact = make_contact("peer-a", port=6001)
        before = time.time()
        rec = PeerRecord(contact=contact)
        after = time.time()

        assert rec.contact is contact
        assert before <= rec.first_seen <= after
        assert before <= rec.last_seen <= after

    def test_convenience_properties(self):
        contact = make_contact("peer-b", host="10.0.0.1", port=7000)
        rec = PeerRecord(contact=contact)

        assert rec.node_id == contact.node_id
        assert rec.host == "10.0.0.1"
        assert rec.port == 7000

    def test_touch_updates_last_seen(self):
        contact = make_contact("peer-c", port=6002)
        rec = PeerRecord(contact=contact, first_seen=1_000_000.0, last_seen=1_000_000.0)
        time.sleep(0.01)
        rec.touch()

        assert rec.last_seen > 1_000_000.0
        assert rec.first_seen == 1_000_000.0  # first_seen is never mutated by touch

    def test_first_seen_is_independent_of_last_seen(self):
        t0 = 1_700_000_000.0
        t1 = t0 + 3600.0
        contact = make_contact("peer-d", port=6003)
        rec = PeerRecord(contact=contact, first_seen=t0, last_seen=t1)

        assert rec.first_seen == t0
        assert rec.last_seen == t1


# ===========================================================================
# PeerStore — construction
# ===========================================================================


class TestPeerStoreConstruction:
    def test_new_store_is_empty(self):
        store = fresh_store()
        assert store.peer_count() == 0
        assert len(store) == 0
        assert store.all_peers() == []

    def test_invalid_local_id_length_raises(self):
        with pytest.raises(ValueError):
            PeerStore(b"\x00" * 10)

    def test_routing_table_property_returns_routing_table(self):
        store = fresh_store()
        assert isinstance(store.routing_table, RoutingTable)


# ===========================================================================
# PeerStore — add_or_update
# ===========================================================================


class TestPeerStoreAddOrUpdate:
    def setup_method(self):
        self.store = fresh_store()
        self.local_id = make_id(LOCAL_SEED)

    def test_add_new_peer_returns_true(self):
        result = self.store.add_or_update(make_id("alpha"), "10.0.0.1", 4001)
        assert result is True

    def test_added_peer_is_stored(self):
        nid = make_id("bravo")
        self.store.add_or_update(nid, "10.0.0.2", 4002)
        rec = self.store.get(nid)

        assert rec is not None
        assert rec.node_id == nid
        assert rec.host == "10.0.0.2"
        assert rec.port == 4002

    def test_adding_local_node_raises(self):
        with pytest.raises(ValueError, match="local node"):
            self.store.add_or_update(self.local_id, "127.0.0.1", 5000)

    def test_add_multiple_distinct_peers(self):
        seeds = [f"peer-{i}" for i in range(5)]
        for i, seed in enumerate(seeds):
            self.store.add_or_update(make_id(seed), "127.0.0.1", 6000 + i)
        assert self.store.peer_count() == 5

    def test_update_existing_peer_host_and_port(self):
        nid = make_id("charlie")
        self.store.add_or_update(nid, "10.0.0.3", 4003)
        # Same node ID, different address
        result = self.store.add_or_update(nid, "192.168.1.1", 9999)

        assert result is True
        rec = self.store.get(nid)
        assert rec.host == "192.168.1.1"
        assert rec.port == 9999
        # Peer count must not increase on a refresh
        assert self.store.peer_count() == 1

    def test_refresh_updates_last_seen(self):
        nid = make_id("delta")
        self.store.add_or_update(nid, "10.0.0.4", 4004)
        rec_before = self.store.get(nid)
        t_first = rec_before.first_seen
        t_last_before = rec_before.last_seen

        time.sleep(0.02)
        self.store.add_or_update(nid, "10.0.0.4", 4004)

        rec_after = self.store.get(nid)
        assert rec_after.last_seen > t_last_before
        # first_seen must not change on refresh
        assert rec_after.first_seen == t_first

    def test_refresh_existing_also_refreshes_routing_table(self):
        nid = make_id("echo")
        self.store.add_or_update(nid, "10.0.0.5", 4005)
        # Refresh should not raise and routing table still has the contact.
        self.store.add_or_update(nid, "10.0.0.5", 4005)
        assert self.store.routing_table.get_contact(nid) is not None

    def test_invalid_port_propagates_value_error(self):
        with pytest.raises(ValueError):
            self.store.add_or_update(make_id("bad-port"), "127.0.0.1", 0)

    def test_invalid_node_id_length_propagates_value_error(self):
        with pytest.raises(ValueError):
            self.store.add_or_update(b"\x01" * 10, "127.0.0.1", 5001)


# ===========================================================================
# PeerStore — get
# ===========================================================================


class TestPeerStoreGet:
    def setup_method(self):
        self.store = fresh_store()

    def test_get_existing_peer_returns_record(self):
        nid = make_id("foxtrot")
        self.store.add_or_update(nid, "10.0.1.1", 5010)
        rec = self.store.get(nid)
        assert rec is not None
        assert rec.node_id == nid

    def test_get_unknown_peer_returns_none(self):
        assert self.store.get(make_id("ghost")) is None

    def test_get_local_id_returns_none(self):
        # Local ID is not in records; get should safely return None.
        assert self.store.get(make_id(LOCAL_SEED)) is None


# ===========================================================================
# PeerStore — remove
# ===========================================================================


class TestPeerStoreRemove:
    def setup_method(self):
        self.store = fresh_store()

    def test_remove_existing_peer_returns_true(self):
        nid = make_id("golf")
        self.store.add_or_update(nid, "10.0.2.1", 5020)
        result = self.store.remove(nid)
        assert result is True

    def test_removed_peer_is_no_longer_known(self):
        nid = make_id("hotel")
        self.store.add_or_update(nid, "10.0.2.2", 5021)
        self.store.remove(nid)
        assert self.store.get(nid) is None
        assert not self.store.contains(nid)

    def test_remove_also_purges_routing_table(self):
        nid = make_id("india")
        self.store.add_or_update(nid, "10.0.2.3", 5022)
        self.store.remove(nid)
        assert self.store.routing_table.get_contact(nid) is None

    def test_remove_unknown_peer_returns_false(self):
        result = self.store.remove(make_id("juliet"))
        assert result is False

    def test_remove_decrements_count(self):
        nid = make_id("kilo")
        self.store.add_or_update(nid, "10.0.2.4", 5023)
        assert self.store.peer_count() == 1
        self.store.remove(nid)
        assert self.store.peer_count() == 0


# ===========================================================================
# PeerStore — contains / __contains__
# ===========================================================================


class TestPeerStoreContains:
    def setup_method(self):
        self.store = fresh_store()

    def test_contains_returns_true_for_known_peer(self):
        nid = make_id("lima")
        self.store.add_or_update(nid, "10.0.3.1", 5030)
        assert self.store.contains(nid) is True
        assert nid in self.store

    def test_contains_returns_false_for_unknown_peer(self):
        nid = make_id("mike")
        assert self.store.contains(nid) is False
        assert nid not in self.store

    def test_contains_false_after_remove(self):
        nid = make_id("november")
        self.store.add_or_update(nid, "10.0.3.2", 5031)
        self.store.remove(nid)
        assert nid not in self.store


# ===========================================================================
# PeerStore — all_peers / peer_count / __len__
# ===========================================================================


class TestPeerStoreBulkQuery:
    def setup_method(self):
        self.store = fresh_store()

    def test_all_peers_empty_on_new_store(self):
        assert self.store.all_peers() == []

    def test_all_peers_returns_all_records(self):
        ids = [make_id(f"bulk-{i}") for i in range(4)]
        for i, nid in enumerate(ids):
            self.store.add_or_update(nid, "127.0.0.1", 7000 + i)
        peers = self.store.all_peers()
        peer_ids = {r.node_id for r in peers}
        assert peer_ids == set(ids)

    def test_peer_count_matches_len(self):
        for i in range(3):
            self.store.add_or_update(make_id(f"cnt-{i}"), "127.0.0.1", 8000 + i)
        assert self.store.peer_count() == len(self.store) == 3

    def test_all_peers_returns_independent_list(self):
        """Mutating the returned list must not affect the store."""
        self.store.add_or_update(make_id("oscar"), "127.0.0.1", 6100)
        peers = self.store.all_peers()
        peers.clear()
        assert self.store.peer_count() == 1


# ===========================================================================
# PeerStore — clear
# ===========================================================================


class TestPeerStoreClear:
    def setup_method(self):
        self.store = fresh_store()

    def test_clear_empties_store(self):
        for i in range(5):
            self.store.add_or_update(make_id(f"clr-{i}"), "127.0.0.1", 9000 + i)
        self.store.clear()
        assert self.store.peer_count() == 0
        assert self.store.all_peers() == []

    def test_clear_resets_routing_table(self):
        nid = make_id("papa")
        self.store.add_or_update(nid, "127.0.0.1", 9010)
        self.store.clear()
        assert self.store.routing_table.get_contact(nid) is None
        assert len(self.store.routing_table) == 0

    def test_store_is_usable_after_clear(self):
        self.store.add_or_update(make_id("quebec"), "127.0.0.1", 9020)
        self.store.clear()
        nid = make_id("romeo")
        result = self.store.add_or_update(nid, "127.0.0.1", 9030)
        assert result is True
        assert self.store.peer_count() == 1


# ===========================================================================
# PeerStore — routing table consistency
# ===========================================================================


class TestPeerStoreRoutingTableConsistency:
    """Ensure the record index and routing table stay in sync."""

    def setup_method(self):
        self.store = fresh_store()

    def test_routing_table_reflects_added_peers(self):
        nid = make_id("sierra")
        self.store.add_or_update(nid, "10.1.1.1", 6200)
        assert self.store.routing_table.get_contact(nid) is not None

    def test_routing_table_contact_matches_stored_record(self):
        nid = make_id("tango")
        self.store.add_or_update(nid, "10.1.1.2", 6201)
        rt_contact = self.store.routing_table.get_contact(nid)
        rec = self.store.get(nid)
        assert rt_contact == rec.contact

    def test_len_matches_routing_table_total(self):
        for i in range(6):
            self.store.add_or_update(make_id(f"sync-{i}"), "127.0.0.1", 7100 + i)
        assert len(self.store) == len(self.store.routing_table)
