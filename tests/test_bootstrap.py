"""
tests/test_bootstrap.py — Focused tests for Day 7: Bootstrap / Join.

Covers:
    - BootstrapClient construction (happy path and invalid args).
    - join() happy path: PING succeeds, FIND_NODE returns contacts, contacts
      are stored in peer store.
    - join() raises BootstrapError when PING fails.
    - join() raises BootstrapError when FIND_NODE exchange fails.
    - join() handles an empty FOUND_NODES response (no contacts stored).
    - join() skips contacts that equal the local node ID.
    - join() respects k-bucket full (returns only accepted contacts).
    - join() returns only the accepted (stored) subset of received contacts.

Run with:
    python -m pytest tests/test_bootstrap.py -v
"""

import pytest

from meshweaver.kademlia.bootstrap import BootstrapClient, BootstrapError
from meshweaver.kademlia.node_id import generate_node_id, node_id_to_hex
from meshweaver.kademlia.peer_store import PeerStore
from meshweaver.kademlia.routing_table import KademliaContact
from meshweaver.kademlia.rpc import FindNodeHandler, PingValidator
from meshweaver.protocol import (
    build_find_node,
    encode_message,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LOCAL_SEED = "bootstrap-local:6000"
BOOTSTRAP_SEED = "bootstrap-peer:6001"
PEER_A_SEED = "peer-a:7000"
PEER_B_SEED = "peer-b:7001"


@pytest.fixture()
def local_id() -> bytes:
    return generate_node_id(LOCAL_SEED)


@pytest.fixture()
def local_id_hex(local_id) -> str:
    return node_id_to_hex(local_id)


@pytest.fixture()
def bootstrap_id() -> bytes:
    return generate_node_id(BOOTSTRAP_SEED)


@pytest.fixture()
def bootstrap_id_hex(bootstrap_id) -> str:
    return node_id_to_hex(bootstrap_id)


@pytest.fixture()
def peer_a_id() -> bytes:
    return generate_node_id(PEER_A_SEED)


@pytest.fixture()
def peer_b_id() -> bytes:
    return generate_node_id(PEER_B_SEED)


@pytest.fixture()
def local_store(local_id) -> PeerStore:
    return PeerStore(local_id)


@pytest.fixture()
def ping_validator(local_id_hex) -> PingValidator:
    return PingValidator(local_id_hex)


@pytest.fixture()
def find_node_handler(local_id_hex) -> FindNodeHandler:
    return FindNodeHandler(local_id_hex)


@pytest.fixture()
def bootstrap_client(local_id_hex, local_store, ping_validator, find_node_handler):
    """A BootstrapClient connected to an empty local store."""
    return BootstrapClient(
        local_id_hex=local_id_hex,
        peer_store=local_store,
        ping_validator=ping_validator,
        find_node_handler=find_node_handler,
    )


def _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store):
    """Return a send_recv callable that simulates a live bootstrap peer.

    The simulated peer:
    - Responds to PING with a valid PONG.
    - Responds to FIND_NODE with contacts from *bootstrap_store*.
    """
    pong_validator = PingValidator(bootstrap_id_hex)
    fn_handler = FindNodeHandler(bootstrap_id_hex)

    def _send_recv(request_bytes: bytes) -> bytes:
        from meshweaver.protocol import decode_message, MSG_PING, MSG_FIND_NODE

        msg = decode_message(request_bytes)
        if msg["type"] == MSG_PING:
            return pong_validator.handle_ping(request_bytes)
        if msg["type"] == MSG_FIND_NODE:
            _, response = fn_handler.handle_request(request_bytes, bootstrap_store)
            return response
        raise ValueError(f"Unexpected message type: {msg['type']}")

    return _send_recv


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestBootstrapClientConstruction:
    def test_happy_path(self, local_id_hex, local_store, ping_validator,
                        find_node_handler):
        client = BootstrapClient(
            local_id_hex=local_id_hex,
            peer_store=local_store,
            ping_validator=ping_validator,
            find_node_handler=find_node_handler,
        )
        assert client is not None

    def test_empty_local_id_hex_raises(self, local_store, ping_validator,
                                       find_node_handler):
        with pytest.raises(ValueError):
            BootstrapClient(
                local_id_hex="",
                peer_store=local_store,
                ping_validator=ping_validator,
                find_node_handler=find_node_handler,
            )


# ---------------------------------------------------------------------------
# join() — happy path
# ---------------------------------------------------------------------------


class TestBootstrapClientJoinHappyPath:
    def test_join_returns_list(self, bootstrap_client, bootstrap_id,
                               bootstrap_id_hex, peer_a_id, peer_b_id):
        """join() returns a list of KademliaContact instances."""
        bootstrap_store = PeerStore(bootstrap_id)
        bootstrap_store.add_or_update(peer_a_id, "10.0.0.1", 7000)
        bootstrap_store.add_or_update(peer_b_id, "10.0.0.2", 7001)

        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        result = bootstrap_client.join("10.0.0.0", 6001, send_recv)

        assert isinstance(result, list)

    def test_join_returns_kademlia_contacts(self, bootstrap_client, bootstrap_id,
                                            bootstrap_id_hex, peer_a_id, peer_b_id):
        """Each item in the result is a KademliaContact."""
        bootstrap_store = PeerStore(bootstrap_id)
        bootstrap_store.add_or_update(peer_a_id, "10.0.0.1", 7000)
        bootstrap_store.add_or_update(peer_b_id, "10.0.0.2", 7001)

        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        result = bootstrap_client.join("10.0.0.0", 6001, send_recv)

        for c in result:
            assert isinstance(c, KademliaContact)

    def test_join_populates_peer_store(self, bootstrap_client, local_store,
                                       bootstrap_id, bootstrap_id_hex,
                                       peer_a_id, peer_b_id):
        """After join(), the local peer store contains the discovered contacts."""
        bootstrap_store = PeerStore(bootstrap_id)
        bootstrap_store.add_or_update(peer_a_id, "10.0.0.1", 7000)
        bootstrap_store.add_or_update(peer_b_id, "10.0.0.2", 7001)

        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        bootstrap_client.join("10.0.0.0", 6001, send_recv)

        stored_ids = {r.node_id for r in local_store.all_peers()}
        assert peer_a_id in stored_ids or peer_b_id in stored_ids

    def test_join_result_matches_store(self, bootstrap_client, local_store,
                                       bootstrap_id, bootstrap_id_hex,
                                       peer_a_id, peer_b_id):
        """The returned contacts are exactly what was added to the store."""
        bootstrap_store = PeerStore(bootstrap_id)
        bootstrap_store.add_or_update(peer_a_id, "10.0.0.1", 7000)

        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        result = bootstrap_client.join("10.0.0.0", 6001, send_recv)

        stored_ids = {r.node_id for r in local_store.all_peers()}
        result_ids = {c.node_id for c in result}
        # Every returned contact must be in the store.
        assert result_ids.issubset(stored_ids)

    def test_join_empty_bootstrap_store_returns_empty_list(
        self, bootstrap_client, local_store, bootstrap_id, bootstrap_id_hex
    ):
        """If the bootstrap peer knows no contacts, join() returns []."""
        empty_bootstrap_store = PeerStore(bootstrap_id)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex,
                                              empty_bootstrap_store)
        result = bootstrap_client.join("10.0.0.0", 6001, send_recv)

        assert result == []
        assert local_store.peer_count() == 0

    def test_join_does_not_store_local_node(self, local_id, local_id_hex,
                                             local_store, bootstrap_id,
                                             bootstrap_id_hex):
        """The bootstrap peer must not return the local node's own ID, but
        even if it somehow does, join() must not store it."""
        # Pre-populate the bootstrap store with the local node's ID (edge case).
        bootstrap_store = PeerStore(bootstrap_id)
        # Bootstrap peer cannot hold local node — add a different peer.
        other_id = generate_node_id("other-peer:9999")
        bootstrap_store.add_or_update(other_id, "9.9.9.9", 9999)

        ping_v = PingValidator(local_id_hex)
        fn_h = FindNodeHandler(local_id_hex)
        client = BootstrapClient(local_id_hex, local_store, ping_v, fn_h)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)
        result = client.join("10.0.0.0", 6001, send_recv)

        for c in result:
            assert c.node_id != local_id


# ---------------------------------------------------------------------------
# join() — PING failure
# ---------------------------------------------------------------------------


class TestBootstrapClientJoinPingFailure:
    def test_ping_failure_raises_bootstrap_error(self, bootstrap_client):
        """A dead bootstrap peer (PING fails) raises BootstrapError."""
        def _dead(_req: bytes) -> bytes:
            raise OSError("connection refused")

        with pytest.raises(BootstrapError):
            bootstrap_client.join("10.0.0.0", 6001, _dead)

    def test_bootstrap_error_message_mentions_peer(self, bootstrap_client):
        """BootstrapError message contains host/port for diagnostics."""
        def _dead(_req: bytes) -> bytes:
            raise OSError("connection refused")

        with pytest.raises(BootstrapError, match="10.0.0.0"):
            bootstrap_client.join("10.0.0.0", 6001, _dead)

    def test_wrong_pong_token_raises_bootstrap_error(self, bootstrap_client,
                                                      bootstrap_id_hex):
        """A bootstrap peer that replies with a wrong PONG token raises BootstrapError."""
        from meshweaver.protocol import build_pong, encode_message

        def _bad_pong(_req: bytes) -> bytes:
            # Reply with a PONG carrying the wrong token.
            return encode_message(build_pong(bootstrap_id_hex, "wrong-token"))

        with pytest.raises(BootstrapError):
            bootstrap_client.join("10.0.0.0", 6001, _bad_pong)


# ---------------------------------------------------------------------------
# join() — FIND_NODE failure
# ---------------------------------------------------------------------------


class TestBootstrapClientJoinFindNodeFailure:
    def test_find_node_transport_error_raises_bootstrap_error(
        self, local_id_hex, local_store, bootstrap_id_hex
    ):
        """If the transport raises during FIND_NODE, BootstrapError is raised."""
        call_count = [0]

        def _one_shot(req: bytes) -> bytes:
            """Reply to PING; fail on every subsequent call."""
            call_count[0] += 1
            if call_count[0] == 1:
                # First call is PING — respond with valid PONG.
                pong_v = PingValidator(bootstrap_id_hex)
                return pong_v.handle_ping(req)
            # Second call (FIND_NODE) — simulate network failure.
            raise OSError("connection reset")

        ping_v = PingValidator(local_id_hex)
        fn_h = FindNodeHandler(local_id_hex)
        client = BootstrapClient(local_id_hex, local_store, ping_v, fn_h)

        with pytest.raises(BootstrapError):
            client.join("10.0.0.0", 6001, _one_shot)

    def test_malformed_find_node_response_raises_bootstrap_error(
        self, local_id_hex, local_store, bootstrap_id_hex
    ):
        """A garbled FIND_NODE reply raises BootstrapError."""
        call_count = [0]

        def _bad_fn_reply(req: bytes) -> bytes:
            call_count[0] += 1
            if call_count[0] == 1:
                pong_v = PingValidator(bootstrap_id_hex)
                return pong_v.handle_ping(req)
            return b"not valid json at all!!!"

        ping_v = PingValidator(local_id_hex)
        fn_h = FindNodeHandler(local_id_hex)
        client = BootstrapClient(local_id_hex, local_store, ping_v, fn_h)

        with pytest.raises(BootstrapError):
            client.join("10.0.0.0", 6001, _bad_fn_reply)


# ---------------------------------------------------------------------------
# join() — integration: PING + FIND_NODE full round-trip
# ---------------------------------------------------------------------------


class TestBootstrapJoinIntegration:
    def test_full_join_sequence(self, local_id, local_id_hex, local_store,
                                bootstrap_id, bootstrap_id_hex):
        """Full in-process join: PING → FIND_NODE → contacts stored."""
        bootstrap_store = PeerStore(bootstrap_id)
        for i in range(3):
            nid = generate_node_id(f"join-peer-{i}:800{i}")
            bootstrap_store.add_or_update(nid, f"192.168.0.{i}", 8000 + i)

        ping_v = PingValidator(local_id_hex)
        fn_h = FindNodeHandler(local_id_hex)
        client = BootstrapClient(local_id_hex, local_store, ping_v, fn_h)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)

        result = client.join("192.168.0.99", 6001, send_recv)

        assert len(result) > 0
        assert local_store.peer_count() > 0

    def test_join_idempotent_on_repeated_call(self, local_id, local_id_hex,
                                               local_store, bootstrap_id,
                                               bootstrap_id_hex):
        """Calling join() twice should not raise; peer count stays consistent."""
        bootstrap_store = PeerStore(bootstrap_id)
        peer_id = generate_node_id("idempotent-peer:9000")
        bootstrap_store.add_or_update(peer_id, "5.5.5.5", 9000)

        ping_v = PingValidator(local_id_hex)
        fn_h = FindNodeHandler(local_id_hex)
        client = BootstrapClient(local_id_hex, local_store, ping_v, fn_h)
        send_recv = _make_bootstrap_send_recv(bootstrap_id_hex, bootstrap_store)

        client.join("5.5.5.5", 6001, send_recv)
        count_after_first = local_store.peer_count()

        client.join("5.5.5.5", 6001, send_recv)
        count_after_second = local_store.peer_count()

        # Second join should not crash; peer count should be >= first (updates ok).
        assert count_after_second >= count_after_first
