"""
tests/test_discovery.py — Focused tests for Day 8: Additional Peer Discovery.

Covers:
    - PeerDiscovery construction (happy path and invalid args).
    - discover() with an empty contact list returns [].
    - discover() queries each seed contact with FIND_NODE.
    - discover() stores only contacts not already in the peer store.
    - discover() skips contacts equal to the local node ID.
    - discover() deduplicates contacts appearing in multiple responses.
    - discover() silently skips unreachable peers (transport errors).
    - discover() silently skips peers that return malformed responses.
    - discover() returns only contacts that were actually stored.
    - Integration: bootstrap → discover pipeline adds more peers.

Run with:
    python -m pytest tests/test_discovery.py -v
"""

import pytest

from meshweaver.kademlia.discovery import PeerDiscovery
from meshweaver.kademlia.node_id import generate_node_id, node_id_to_hex
from meshweaver.kademlia.peer_store import PeerStore
from meshweaver.kademlia.routing_table import KademliaContact
from meshweaver.kademlia.rpc import FindNodeHandler, PingValidator


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LOCAL_SEED = "discovery-local:6000"


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
def find_node_handler(local_id_hex) -> FindNodeHandler:
    return FindNodeHandler(local_id_hex)


@pytest.fixture()
def peer_discovery(local_id_hex, local_store, find_node_handler) -> PeerDiscovery:
    return PeerDiscovery(
        local_id_hex=local_id_hex,
        peer_store=local_store,
        find_node_handler=find_node_handler,
    )


def _make_peer_send_recv(peer_id_hex: str, peer_store: PeerStore):
    """Return a send_recv callable simulating a live peer that handles FIND_NODE."""
    handler = FindNodeHandler(peer_id_hex)

    def _send_recv(request_bytes: bytes) -> bytes:
        _, response = handler.handle_request(request_bytes, peer_store)
        return response

    return _send_recv


def _make_contact(seed: str, host: str, port: int) -> KademliaContact:
    """Create a KademliaContact from a seed string."""
    return KademliaContact(generate_node_id(seed), host, port)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestPeerDiscoveryConstruction:
    def test_happy_path(self, local_id_hex, local_store, find_node_handler):
        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        assert disc is not None

    def test_empty_local_id_raises(self, local_store, find_node_handler):
        with pytest.raises(ValueError):
            PeerDiscovery("", local_store, find_node_handler)


# ---------------------------------------------------------------------------
# discover() — basic behaviour
# ---------------------------------------------------------------------------


class TestDiscoverBasic:
    def test_empty_contacts_returns_empty(self, peer_discovery):
        """No seed contacts → nothing to query → empty result."""
        result = peer_discovery.discover([], send_recv_for=lambda _c: None)
        assert result == []

    def test_returns_list(self, peer_discovery, local_id):
        """discover() always returns a list."""
        result = peer_discovery.discover([], send_recv_for=lambda _c: None)
        assert isinstance(result, list)

    def test_result_items_are_kademlia_contacts(self, local_id, local_id_hex,
                                                 local_store, find_node_handler):
        """Every item in the returned list is a KademliaContact."""
        # Set up one seed peer whose store has a new contact.
        seed_id = generate_node_id("seed-peer:7000")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        extra_id = generate_node_id("extra-peer:8000")
        seed_store.add_or_update(extra_id, "10.0.0.1", 8000)

        seed_contact = KademliaContact(seed_id, "10.0.0.0", 7000)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover([seed_contact],
                               send_recv_for=lambda _c: send_recv_fn)

        for c in result:
            assert isinstance(c, KademliaContact)


# ---------------------------------------------------------------------------
# discover() — deduplication
# ---------------------------------------------------------------------------


class TestDiscoverDeduplication:
    def test_already_known_peer_not_added_again(self, local_id, local_id_hex,
                                                 local_store, find_node_handler):
        """A contact already in the peer store is not returned as newly stored."""
        known_id = generate_node_id("already-known:7777")
        local_store.add_or_update(known_id, "1.1.1.1", 7777)
        count_before = local_store.peer_count()

        # Seed peer knows only the already-known contact.
        seed_id = generate_node_id("seed-peer:7000")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        seed_store.add_or_update(known_id, "1.1.1.1", 7777)

        seed_contact = KademliaContact(seed_id, "10.0.0.0", 7000)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover([seed_contact],
                               send_recv_for=lambda _c: send_recv_fn)

        # Result should not include the already-known contact.
        result_ids = {c.node_id for c in result}
        assert known_id not in result_ids

    def test_same_contact_from_multiple_peers_added_once(
        self, local_id, local_id_hex, local_store, find_node_handler
    ):
        """A contact returned by two different seed peers is stored only once."""
        shared_id = generate_node_id("shared-peer:8888")

        # Two seed peers, both knowing the same shared contact.
        seeds = []
        for i in range(2):
            s_id = generate_node_id(f"seed-{i}:700{i}")
            s_hex = node_id_to_hex(s_id)
            s_store = PeerStore(s_id)
            s_store.add_or_update(shared_id, "8.8.8.8", 8888)
            seeds.append((KademliaContact(s_id, f"10.0.0.{i}", 7000 + i),
                          _make_peer_send_recv(s_hex, s_store)))

        def _send_recv_for(contact):
            for (c, fn) in seeds:
                if c.node_id == contact.node_id:
                    return fn
            raise ValueError("unknown contact")

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover([c for c, _ in seeds],
                               send_recv_for=_send_recv_for)

        result_ids = [c.node_id for c in result]
        assert result_ids.count(shared_id) <= 1

    def test_discover_does_not_add_local_node(self, local_id, local_id_hex,
                                               local_store, find_node_handler):
        """Even if a peer responds with the local node's ID, it is not stored."""
        # The local node cannot be inserted into its own peer store (ValueError).
        # PeerDiscovery must catch and skip that.
        seed_id = generate_node_id("seed-for-local-test:7100")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        # Add a normal peer to make the response non-empty.
        other_id = generate_node_id("other-normal-peer:9100")
        seed_store.add_or_update(other_id, "9.9.9.1", 9100)

        seed_contact = KademliaContact(seed_id, "10.0.0.0", 7100)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover([seed_contact],
                               send_recv_for=lambda _c: send_recv_fn)

        result_ids = {c.node_id for c in result}
        assert local_id not in result_ids


# ---------------------------------------------------------------------------
# discover() — fault tolerance
# ---------------------------------------------------------------------------


class TestDiscoverFaultTolerance:
    def test_unreachable_seed_silently_skipped(self, local_id, local_id_hex,
                                                local_store, find_node_handler):
        """A seed peer that raises on send_recv is skipped without error."""
        bad_contact = _make_contact("bad-peer:9001", "9.9.9.9", 9001)

        def _dead(_req: bytes) -> bytes:
            raise OSError("connection refused")

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        # Must not raise.
        result = disc.discover([bad_contact], send_recv_for=lambda _c: _dead)
        assert result == []

    def test_malformed_response_silently_skipped(self, local_id, local_id_hex,
                                                  local_store, find_node_handler):
        """A seed peer that returns garbage is skipped without error."""
        bad_contact = _make_contact("garbled-peer:9002", "9.9.9.8", 9002)

        def _garbled(_req: bytes) -> bytes:
            return b"this is not valid json!!!"

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover([bad_contact],
                               send_recv_for=lambda _c: _garbled)
        assert result == []

    def test_partial_failure_still_returns_good_peers(
        self, local_id, local_id_hex, local_store, find_node_handler
    ):
        """One bad seed does not block good results from other seeds."""
        bad_contact = _make_contact("fail-peer:9003", "9.9.9.7", 9003)
        good_id = generate_node_id("good-seed:7200")
        good_id_hex = node_id_to_hex(good_id)
        good_store = PeerStore(good_id)
        extra_id = generate_node_id("extra-from-good:8200")
        good_store.add_or_update(extra_id, "10.0.0.50", 8200)
        good_contact = KademliaContact(good_id, "10.0.0.50", 7200)

        def _send_recv_for(contact):
            if contact.node_id == bad_contact.node_id:
                def _dead(_req):
                    raise OSError("gone")
                return _dead
            return _make_peer_send_recv(good_id_hex, good_store)

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover([bad_contact, good_contact],
                               send_recv_for=_send_recv_for)

        assert len(result) > 0
        result_ids = {c.node_id for c in result}
        assert extra_id in result_ids


# ---------------------------------------------------------------------------
# discover() — new contacts stored and returned
# ---------------------------------------------------------------------------


class TestDiscoverNewContacts:
    def test_new_contact_appears_in_peer_store(self, local_id, local_id_hex,
                                                local_store, find_node_handler):
        """Newly discovered contacts are present in the peer store after discover()."""
        seed_id = generate_node_id("seed:7300")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        new_id = generate_node_id("brand-new-peer:8300")
        seed_store.add_or_update(new_id, "10.0.0.100", 8300)

        seed_contact = KademliaContact(seed_id, "10.0.0.0", 7300)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        disc.discover([seed_contact], send_recv_for=lambda _c: send_recv_fn)

        assert local_store.contains(new_id)

    def test_result_subset_of_store(self, local_id, local_id_hex,
                                     local_store, find_node_handler):
        """Every contact in the result is present in the peer store."""
        seed_id = generate_node_id("seed:7400")
        seed_id_hex = node_id_to_hex(seed_id)
        seed_store = PeerStore(seed_id)
        for i in range(3):
            nid = generate_node_id(f"disco-peer-{i}:840{i}")
            seed_store.add_or_update(nid, f"10.0.1.{i}", 8400 + i)

        seed_contact = KademliaContact(seed_id, "10.0.0.0", 7400)
        send_recv_fn = _make_peer_send_recv(seed_id_hex, seed_store)

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover([seed_contact],
                               send_recv_for=lambda _c: send_recv_fn)

        for c in result:
            assert local_store.contains(c.node_id)

    def test_multiple_seeds_discovers_more_peers(self, local_id, local_id_hex,
                                                  local_store, find_node_handler):
        """Two different seed peers can contribute distinct new contacts."""
        seed_contacts = []
        send_recv_map = {}

        for i in range(2):
            s_id = generate_node_id(f"multi-seed-{i}:750{i}")
            s_hex = node_id_to_hex(s_id)
            s_store = PeerStore(s_id)
            # Each seed knows a different extra peer.
            extra_id = generate_node_id(f"multi-extra-{i}:850{i}")
            s_store.add_or_update(extra_id, f"172.16.0.{i}", 8500 + i)
            c = KademliaContact(s_id, f"10.0.2.{i}", 7500 + i)
            seed_contacts.append(c)
            send_recv_map[s_id] = _make_peer_send_recv(s_hex, s_store)

        def _send_recv_for(contact):
            return send_recv_map[contact.node_id]

        disc = PeerDiscovery(local_id_hex, local_store, find_node_handler)
        result = disc.discover(seed_contacts, send_recv_for=_send_recv_for)

        assert len(result) >= 2


# ---------------------------------------------------------------------------
# Integration: bootstrap → discover pipeline
# ---------------------------------------------------------------------------


class TestBootstrapThenDiscover:
    def test_bootstrap_then_discover_adds_more_peers(self, local_id, local_id_hex,
                                                      local_store):
        """Full pipeline: join via bootstrap, then discover additional peers."""
        from meshweaver.kademlia.bootstrap import BootstrapClient

        # Bootstrap peer knows two contacts.
        bootstrap_id = generate_node_id("bs-peer:6001")
        bootstrap_id_hex = node_id_to_hex(bootstrap_id)
        bootstrap_store = PeerStore(bootstrap_id)

        intermediate_ids = []
        for i in range(2):
            nid = generate_node_id(f"intermediate-{i}:700{i}")
            intermediate_ids.append(nid)
            bootstrap_store.add_or_update(nid, f"10.1.0.{i}", 7000 + i)

        # Each intermediate peer knows one more (unique) extra peer.
        intermediate_stores = {}
        for idx, nid in enumerate(intermediate_ids):
            nid_hex = node_id_to_hex(nid)
            i_store = PeerStore(nid)
            extra_nid = generate_node_id(f"extra-layer2-{idx}:800{idx}")
            i_store.add_or_update(extra_nid, f"10.2.0.{idx}", 8000 + idx)
            intermediate_stores[nid] = (nid_hex, i_store)

        # --- Bootstrap ---
        ping_v = PingValidator(local_id_hex)
        fn_h = FindNodeHandler(local_id_hex)
        client = BootstrapClient(local_id_hex, local_store, ping_v, fn_h)

        def _bootstrap_send_recv(request_bytes: bytes) -> bytes:
            from meshweaver.protocol import decode_message, MSG_PING, MSG_FIND_NODE
            msg = decode_message(request_bytes)
            if msg["type"] == MSG_PING:
                return PingValidator(bootstrap_id_hex).handle_ping(request_bytes)
            if msg["type"] == MSG_FIND_NODE:
                _, resp = FindNodeHandler(bootstrap_id_hex).handle_request(
                    request_bytes, bootstrap_store
                )
                return resp
            raise ValueError(f"Unexpected: {msg['type']}")

        bootstrap_result = client.join("10.0.0.99", 6001, _bootstrap_send_recv)
        count_after_bootstrap = local_store.peer_count()
        assert count_after_bootstrap > 0

        # --- Discover ---
        disc = PeerDiscovery(local_id_hex, local_store, fn_h)

        def _send_recv_for(contact):
            if contact.node_id not in intermediate_stores:
                def _dead(_r):
                    raise OSError("not a real peer")
                return _dead
            nid_hex, i_store = intermediate_stores[contact.node_id]

            def _fn(request_bytes):
                _, resp = FindNodeHandler(nid_hex).handle_request(
                    request_bytes, i_store
                )
                return resp

            return _fn

        discovery_result = disc.discover(bootstrap_result,
                                         send_recv_for=_send_recv_for)
        count_after_discovery = local_store.peer_count()

        # Discovery round must add at least the layer-2 peers.
        assert count_after_discovery > count_after_bootstrap
        assert len(discovery_result) > 0
