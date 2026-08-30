"""
tests/test_rpc_protocol.py — Focused tests for Commit 5.

Covers:
    - Protocol message builders  (build_ping, build_pong, build_find_node,
      build_found_nodes) and encode/decode round-trips.
    - validate_message() structural checker.
    - PingValidator  (build_ping_request, handle_ping, validate_pong, ping).
    - FindNodeHandler (build_request, parse_response, handle_request).
    - contacts_to_dicts / dicts_to_contacts wire-format helpers.

Run with:
    python -m pytest tests/test_rpc_protocol.py -v
"""

import pytest

from meshweaver.kademlia.node_id import (
    generate_node_id,
    node_id_to_hex,
    node_id_from_hex,
)
from meshweaver.kademlia.peer_store import PeerStore
from meshweaver.kademlia.routing_table import KademliaContact
from meshweaver.kademlia.rpc import (
    PingValidator,
    FindNodeHandler,
    contacts_to_dicts,
    dicts_to_contacts,
)
from meshweaver.protocol import (
    MSG_PING,
    MSG_PONG,
    MSG_FIND_NODE,
    MSG_FOUND_NODES,
    build_ping,
    build_pong,
    build_find_node,
    build_found_nodes,
    encode_message,
    decode_message,
    validate_message,
    create_message,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LOCAL_SEED = "127.0.0.1:5000"
PEER_SEED = "127.0.0.1:5001"
TARGET_SEED = "127.0.0.1:9999"


@pytest.fixture()
def local_id() -> bytes:
    return generate_node_id(LOCAL_SEED)


@pytest.fixture()
def local_id_hex(local_id) -> str:
    return node_id_to_hex(local_id)


@pytest.fixture()
def peer_id() -> bytes:
    return generate_node_id(PEER_SEED)


@pytest.fixture()
def peer_id_hex(peer_id) -> str:
    return node_id_to_hex(peer_id)


@pytest.fixture()
def target_id() -> bytes:
    return generate_node_id(TARGET_SEED)


@pytest.fixture()
def target_id_hex(target_id) -> str:
    return node_id_to_hex(target_id)


@pytest.fixture()
def populated_store(local_id, peer_id):
    """A PeerStore with one known peer inserted."""
    store = PeerStore(local_id)
    store.add_or_update(peer_id, "127.0.0.1", 5001)
    return store


# ---------------------------------------------------------------------------
# Protocol — legacy create_message (backward-compat)
# ---------------------------------------------------------------------------


class TestCreateMessage:
    def test_type_and_sender_present(self, local_id_hex):
        msg = create_message("HELLO", local_id_hex)
        assert msg["type"] == "HELLO"
        assert msg["sender_id"] == local_id_hex


# ---------------------------------------------------------------------------
# Protocol — build_ping / build_pong
# ---------------------------------------------------------------------------


class TestBuildPing:
    def test_type_is_ping(self, local_id_hex):
        msg = build_ping(local_id_hex, "tok-1")
        assert msg["type"] == MSG_PING

    def test_sender_id_present(self, local_id_hex):
        msg = build_ping(local_id_hex, "tok-1")
        assert msg["sender_id"] == local_id_hex

    def test_token_present(self, local_id_hex):
        msg = build_ping(local_id_hex, "my-token")
        assert msg["token"] == "my-token"

    def test_empty_sender_raises(self):
        with pytest.raises(ValueError):
            build_ping("", "tok")

    def test_empty_token_raises(self, local_id_hex):
        with pytest.raises(ValueError):
            build_ping(local_id_hex, "")


class TestBuildPong:
    def test_type_is_pong(self, local_id_hex):
        msg = build_pong(local_id_hex, "tok-1")
        assert msg["type"] == MSG_PONG

    def test_token_echoed(self, local_id_hex):
        msg = build_pong(local_id_hex, "echo-me")
        assert msg["token"] == "echo-me"

    def test_empty_sender_raises(self):
        with pytest.raises(ValueError):
            build_pong("", "tok")

    def test_empty_token_raises(self, local_id_hex):
        with pytest.raises(ValueError):
            build_pong(local_id_hex, "")


# ---------------------------------------------------------------------------
# Protocol — build_find_node / build_found_nodes
# ---------------------------------------------------------------------------


class TestBuildFindNode:
    def test_type_is_find_node(self, local_id_hex, target_id_hex):
        msg = build_find_node(local_id_hex, target_id_hex)
        assert msg["type"] == MSG_FIND_NODE

    def test_target_id_present(self, local_id_hex, target_id_hex):
        msg = build_find_node(local_id_hex, target_id_hex)
        assert msg["target_id"] == target_id_hex

    def test_empty_sender_raises(self, target_id_hex):
        with pytest.raises(ValueError):
            build_find_node("", target_id_hex)

    def test_empty_target_raises(self, local_id_hex):
        with pytest.raises(ValueError):
            build_find_node(local_id_hex, "")


class TestBuildFoundNodes:
    def test_type_is_found_nodes(self, local_id_hex, target_id_hex):
        msg = build_found_nodes(local_id_hex, target_id_hex, [])
        assert msg["type"] == MSG_FOUND_NODES

    def test_contacts_list_preserved(self, local_id_hex, target_id_hex, peer_id_hex):
        contacts = [{"node_id": peer_id_hex, "host": "127.0.0.1", "port": 5001}]
        msg = build_found_nodes(local_id_hex, target_id_hex, contacts)
        assert msg["contacts"] == contacts

    def test_target_id_echoed(self, local_id_hex, target_id_hex):
        msg = build_found_nodes(local_id_hex, target_id_hex, [])
        assert msg["target_id"] == target_id_hex

    def test_empty_contacts_allowed(self, local_id_hex, target_id_hex):
        msg = build_found_nodes(local_id_hex, target_id_hex, [])
        assert msg["contacts"] == []

    def test_contacts_not_list_raises(self, local_id_hex, target_id_hex):
        with pytest.raises(TypeError):
            build_found_nodes(local_id_hex, target_id_hex, "bad")


# ---------------------------------------------------------------------------
# Protocol — encode_message / decode_message round-trip
# ---------------------------------------------------------------------------


class TestEncodeDecodeRoundTrip:
    def test_ping_roundtrip(self, local_id_hex):
        original = build_ping(local_id_hex, "t1")
        assert decode_message(encode_message(original)) == original

    def test_pong_roundtrip(self, local_id_hex):
        original = build_pong(local_id_hex, "t2")
        assert decode_message(encode_message(original)) == original

    def test_find_node_roundtrip(self, local_id_hex, target_id_hex):
        original = build_find_node(local_id_hex, target_id_hex)
        assert decode_message(encode_message(original)) == original

    def test_found_nodes_roundtrip(self, local_id_hex, target_id_hex, peer_id_hex):
        contacts = [{"node_id": peer_id_hex, "host": "127.0.0.1", "port": 5001}]
        original = build_found_nodes(local_id_hex, target_id_hex, contacts)
        assert decode_message(encode_message(original)) == original

    def test_result_is_bytes(self, local_id_hex):
        assert isinstance(encode_message(build_ping(local_id_hex, "x")), bytes)

    def test_result_is_dict(self, local_id_hex):
        raw = encode_message(build_ping(local_id_hex, "x"))
        assert isinstance(decode_message(raw), dict)


# ---------------------------------------------------------------------------
# Protocol — validate_message
# ---------------------------------------------------------------------------


class TestValidateMessage:
    def test_valid_ping_passes(self, local_id_hex):
        msg = build_ping(local_id_hex, "tok")
        validate_message(msg, MSG_PING)  # must not raise

    def test_wrong_type_raises(self, local_id_hex):
        msg = build_ping(local_id_hex, "tok")
        with pytest.raises(ValueError, match="expected type"):
            validate_message(msg, MSG_PONG)

    def test_missing_sender_id_raises(self):
        with pytest.raises(ValueError):
            validate_message({"type": MSG_PING}, MSG_PING)

    def test_non_dict_raises(self):
        with pytest.raises(ValueError):
            validate_message("not a dict", MSG_PING)  # type: ignore

    def test_valid_find_node_passes(self, local_id_hex, target_id_hex):
        msg = build_find_node(local_id_hex, target_id_hex)
        validate_message(msg, MSG_FIND_NODE)  # must not raise


# ---------------------------------------------------------------------------
# Wire-format helpers — contacts_to_dicts / dicts_to_contacts
# ---------------------------------------------------------------------------


class TestContactsToDict:
    def test_single_contact(self, peer_id, peer_id_hex):
        contact = KademliaContact(peer_id, "127.0.0.1", 5001)
        result = contacts_to_dicts([contact])
        assert len(result) == 1
        assert result[0]["node_id"] == peer_id_hex
        assert result[0]["host"] == "127.0.0.1"
        assert result[0]["port"] == 5001

    def test_empty_list(self):
        assert contacts_to_dicts([]) == []

    def test_multiple_contacts(self, local_id, peer_id):
        c1 = KademliaContact(peer_id, "10.0.0.1", 6000)
        c2_id = generate_node_id("10.0.0.2:6001")
        c2 = KademliaContact(c2_id, "10.0.0.2", 6001)
        result = contacts_to_dicts([c1, c2])
        assert len(result) == 2

    def test_node_id_is_hex_string(self, peer_id):
        contact = KademliaContact(peer_id, "host", 1234)
        result = contacts_to_dicts([contact])
        assert isinstance(result[0]["node_id"], str)
        assert len(result[0]["node_id"]) == 64


class TestDictsToContacts:
    def test_single_entry(self, peer_id, peer_id_hex):
        raw = [{"node_id": peer_id_hex, "host": "127.0.0.1", "port": 5001}]
        contacts = dicts_to_contacts(raw)
        assert len(contacts) == 1
        assert contacts[0].node_id == peer_id
        assert contacts[0].host == "127.0.0.1"
        assert contacts[0].port == 5001

    def test_empty_list(self):
        assert dicts_to_contacts([]) == []

    def test_roundtrip(self, peer_id):
        original = [KademliaContact(peer_id, "192.168.1.1", 7000)]
        assert dicts_to_contacts(contacts_to_dicts(original)) == original

    def test_bad_node_id_hex_raises(self):
        raw = [{"node_id": "not-valid-hex!!!", "host": "x", "port": 1}]
        with pytest.raises(ValueError):
            dicts_to_contacts(raw)

    def test_missing_key_raises(self, peer_id_hex):
        raw = [{"node_id": peer_id_hex, "host": "x"}]  # port missing
        with pytest.raises(KeyError):
            dicts_to_contacts(raw)


# ---------------------------------------------------------------------------
# PingValidator
# ---------------------------------------------------------------------------


class TestPingValidator:
    """Tests for the PingValidator class."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def test_empty_local_id_raises(self):
        with pytest.raises(ValueError):
            PingValidator("")

    # ------------------------------------------------------------------
    # build_ping_request
    # ------------------------------------------------------------------

    def test_build_ping_request_returns_bytes(self, local_id_hex):
        v = PingValidator(local_id_hex)
        req = v.build_ping_request("tok-1")
        assert isinstance(req, bytes)

    def test_build_ping_request_is_valid_ping(self, local_id_hex):
        v = PingValidator(local_id_hex)
        req = v.build_ping_request("tok-1")
        msg = decode_message(req)
        assert msg["type"] == MSG_PING
        assert msg["token"] == "tok-1"
        assert msg["sender_id"] == local_id_hex

    def test_build_ping_request_auto_token(self, local_id_hex):
        """Without explicit token, a non-empty UUID token is generated."""
        v = PingValidator(local_id_hex)
        req = v.build_ping_request()
        msg = decode_message(req)
        assert msg.get("token")  # non-empty

    def test_build_ping_request_auto_token_unique(self, local_id_hex):
        """Two calls without a token should produce different tokens."""
        v = PingValidator(local_id_hex)
        t1 = decode_message(v.build_ping_request())["token"]
        t2 = decode_message(v.build_ping_request())["token"]
        assert t1 != t2

    # ------------------------------------------------------------------
    # handle_ping (responder side)
    # ------------------------------------------------------------------

    def test_handle_ping_returns_bytes(self, local_id_hex, peer_id_hex):
        requester = PingValidator(peer_id_hex)
        responder = PingValidator(local_id_hex)
        ping = requester.build_ping_request("tok-2")
        pong = responder.handle_ping(ping)
        assert isinstance(pong, bytes)

    def test_handle_ping_pong_type(self, local_id_hex, peer_id_hex):
        requester = PingValidator(peer_id_hex)
        responder = PingValidator(local_id_hex)
        ping = requester.build_ping_request("tok-3")
        pong_msg = decode_message(responder.handle_ping(ping))
        assert pong_msg["type"] == MSG_PONG

    def test_handle_ping_echoes_token(self, local_id_hex, peer_id_hex):
        requester = PingValidator(peer_id_hex)
        responder = PingValidator(local_id_hex)
        ping = requester.build_ping_request("echo-token")
        pong_msg = decode_message(responder.handle_ping(ping))
        assert pong_msg["token"] == "echo-token"

    def test_handle_ping_uses_responder_sender_id(self, local_id_hex, peer_id_hex):
        requester = PingValidator(peer_id_hex)
        responder = PingValidator(local_id_hex)
        ping = requester.build_ping_request("t")
        pong_msg = decode_message(responder.handle_ping(ping))
        assert pong_msg["sender_id"] == local_id_hex

    def test_handle_ping_non_ping_raises(self, local_id_hex, peer_id_hex):
        responder = PingValidator(local_id_hex)
        # Send a PONG instead of a PING — should raise
        fake = encode_message(build_pong(peer_id_hex, "t"))
        with pytest.raises(ValueError):
            responder.handle_ping(fake)

    def test_handle_ping_missing_token_raises(self, local_id_hex, peer_id_hex):
        responder = PingValidator(local_id_hex)
        bad = encode_message({"type": MSG_PING, "sender_id": peer_id_hex})
        with pytest.raises(ValueError, match="token"):
            responder.handle_ping(bad)

    # ------------------------------------------------------------------
    # validate_pong
    # ------------------------------------------------------------------

    def test_validate_pong_correct_token(self, local_id_hex, peer_id_hex):
        v = PingValidator(local_id_hex)
        pong = encode_message(build_pong(peer_id_hex, "tok"))
        assert v.validate_pong(pong, "tok") is True

    def test_validate_pong_wrong_token(self, local_id_hex, peer_id_hex):
        v = PingValidator(local_id_hex)
        pong = encode_message(build_pong(peer_id_hex, "tok"))
        assert v.validate_pong(pong, "OTHER") is False

    def test_validate_pong_wrong_type(self, local_id_hex, peer_id_hex):
        v = PingValidator(local_id_hex)
        ping = encode_message(build_ping(peer_id_hex, "tok"))
        assert v.validate_pong(ping, "tok") is False

    def test_validate_pong_garbage_bytes(self, local_id_hex):
        v = PingValidator(local_id_hex)
        assert v.validate_pong(b"this is not json", "tok") is False

    # ------------------------------------------------------------------
    # ping() — full round-trip
    # ------------------------------------------------------------------

    def test_ping_live_peer_returns_true(self, local_id_hex, peer_id_hex):
        """Simulate a live peer: send_recv returns a valid PONG."""
        requester = PingValidator(local_id_hex)
        responder = PingValidator(peer_id_hex)

        def _send_recv(req: bytes) -> bytes:
            return responder.handle_ping(req)

        assert requester.ping(_send_recv) is True

    def test_ping_dead_peer_returns_false(self, local_id_hex):
        """Simulate a dead peer: send_recv raises an exception."""
        requester = PingValidator(local_id_hex)

        def _send_recv(_req: bytes) -> bytes:
            raise OSError("connection refused")

        assert requester.ping(_send_recv) is False

    def test_ping_wrong_token_returns_false(self, local_id_hex, peer_id_hex):
        """Simulate a peer that replies with the wrong token."""
        requester = PingValidator(local_id_hex)

        def _send_recv(_req: bytes) -> bytes:
            # Reply with a PONG but a completely different token
            return encode_message(build_pong(peer_id_hex, "wrong-token"))

        assert requester.ping(_send_recv, token="my-token") is False

    def test_ping_fixed_token_used(self, local_id_hex, peer_id_hex):
        """The fixed token is round-tripped correctly."""
        requester = PingValidator(local_id_hex)
        responder = PingValidator(peer_id_hex)
        seen_token = []

        def _send_recv(req: bytes) -> bytes:
            seen_token.append(decode_message(req)["token"])
            return responder.handle_ping(req)

        result = requester.ping(_send_recv, token="fixed-tok")
        assert result is True
        assert seen_token == ["fixed-tok"]


# ---------------------------------------------------------------------------
# FindNodeHandler
# ---------------------------------------------------------------------------


class TestFindNodeHandler:
    """Tests for the FindNodeHandler class."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def test_empty_local_id_raises(self):
        with pytest.raises(ValueError):
            FindNodeHandler("")

    def test_k_less_than_one_raises(self, local_id_hex):
        with pytest.raises(ValueError):
            FindNodeHandler(local_id_hex, k=0)

    # ------------------------------------------------------------------
    # build_request (requester side)
    # ------------------------------------------------------------------

    def test_build_request_returns_bytes(self, local_id_hex, target_id_hex):
        h = FindNodeHandler(local_id_hex)
        assert isinstance(h.build_request(target_id_hex), bytes)

    def test_build_request_message_type(self, local_id_hex, target_id_hex):
        h = FindNodeHandler(local_id_hex)
        msg = decode_message(h.build_request(target_id_hex))
        assert msg["type"] == MSG_FIND_NODE

    def test_build_request_contains_target(self, local_id_hex, target_id_hex):
        h = FindNodeHandler(local_id_hex)
        msg = decode_message(h.build_request(target_id_hex))
        assert msg["target_id"] == target_id_hex

    def test_build_request_contains_sender(self, local_id_hex, target_id_hex):
        h = FindNodeHandler(local_id_hex)
        msg = decode_message(h.build_request(target_id_hex))
        assert msg["sender_id"] == local_id_hex

    # ------------------------------------------------------------------
    # handle_request (responder side)
    # ------------------------------------------------------------------

    def test_handle_request_returns_tuple(self, local_id_hex, peer_id_hex,
                                          target_id_hex, populated_store):
        h = FindNodeHandler(local_id_hex)
        request = encode_message(build_find_node(peer_id_hex, target_id_hex))
        result = h.handle_request(request, populated_store)
        assert isinstance(result, tuple) and len(result) == 2

    def test_handle_request_target_id_echoed(self, local_id_hex, peer_id_hex,
                                              target_id_hex, populated_store):
        h = FindNodeHandler(local_id_hex)
        request = encode_message(build_find_node(peer_id_hex, target_id_hex))
        returned_target, _ = h.handle_request(request, populated_store)
        assert returned_target == target_id_hex

    def test_handle_request_response_type(self, local_id_hex, peer_id_hex,
                                           target_id_hex, populated_store):
        h = FindNodeHandler(local_id_hex)
        request = encode_message(build_find_node(peer_id_hex, target_id_hex))
        _, response_bytes = h.handle_request(request, populated_store)
        msg = decode_message(response_bytes)
        assert msg["type"] == MSG_FOUND_NODES

    def test_handle_request_contains_known_peer(self, local_id_hex, peer_id_hex,
                                                 target_id_hex, populated_store):
        """The response contacts should include the peer we added to the store."""
        h = FindNodeHandler(local_id_hex)
        request = encode_message(build_find_node(peer_id_hex, target_id_hex))
        _, response_bytes = h.handle_request(request, populated_store)
        msg = decode_message(response_bytes)
        node_ids_in_response = [c["node_id"] for c in msg["contacts"]]
        assert peer_id_hex in node_ids_in_response

    def test_handle_request_empty_store(self, local_id_hex, peer_id_hex,
                                         target_id_hex, local_id):
        """Empty peer store returns an empty contacts list."""
        empty_store = PeerStore(local_id)
        h = FindNodeHandler(local_id_hex)
        request = encode_message(build_find_node(peer_id_hex, target_id_hex))
        _, response_bytes = h.handle_request(request, empty_store)
        msg = decode_message(response_bytes)
        assert msg["contacts"] == []

    def test_handle_request_respects_k_limit(self, local_id, local_id_hex,
                                              peer_id_hex, target_id_hex):
        """Only up to k contacts are returned."""
        store = PeerStore(local_id)
        # Add 5 peers
        for i in range(5):
            nid = generate_node_id(f"10.0.0.{i}:{7000 + i}")
            store.add_or_update(nid, f"10.0.0.{i}", 7000 + i)

        h = FindNodeHandler(local_id_hex, k=3)
        request = encode_message(build_find_node(peer_id_hex, target_id_hex))
        _, response_bytes = h.handle_request(request, store)
        msg = decode_message(response_bytes)
        assert len(msg["contacts"]) <= 3

    def test_handle_request_non_find_node_raises(self, local_id_hex, peer_id_hex,
                                                   populated_store):
        """A non-FIND_NODE message should raise ValueError."""
        h = FindNodeHandler(local_id_hex)
        bad = encode_message(build_ping(peer_id_hex, "tok"))
        with pytest.raises(ValueError):
            h.handle_request(bad, populated_store)

    # ------------------------------------------------------------------
    # parse_response (requester side)
    # ------------------------------------------------------------------

    def test_parse_response_returns_contacts(self, local_id_hex, peer_id_hex,
                                              target_id_hex, populated_store):
        """Full round-trip: build → handle → parse."""
        requester = FindNodeHandler(local_id_hex)
        responder = FindNodeHandler(peer_id_hex)

        request = requester.build_request(target_id_hex)
        _, response_bytes = responder.handle_request(request, populated_store)
        contacts = requester.parse_response(response_bytes, target_id_hex)
        assert isinstance(contacts, list)

    def test_parse_response_contacts_are_kademlia_contacts(
            self, local_id_hex, peer_id_hex, target_id_hex, populated_store):
        requester = FindNodeHandler(local_id_hex)
        responder = FindNodeHandler(peer_id_hex)
        request = requester.build_request(target_id_hex)
        _, response_bytes = responder.handle_request(request, populated_store)
        contacts = requester.parse_response(response_bytes, target_id_hex)
        for c in contacts:
            assert isinstance(c, KademliaContact)

    def test_parse_response_wrong_target_raises(self, local_id_hex, peer_id_hex,
                                                 target_id_hex, populated_store):
        requester = FindNodeHandler(local_id_hex)
        responder = FindNodeHandler(peer_id_hex)
        request = requester.build_request(target_id_hex)
        _, response_bytes = responder.handle_request(request, populated_store)

        wrong_target = node_id_to_hex(generate_node_id("wrong-target"))
        with pytest.raises(ValueError, match="target_id"):
            requester.parse_response(response_bytes, wrong_target)

    def test_parse_response_sorted_by_distance(self, local_id_hex, local_id,
                                                target_id, target_id_hex):
        """parse_response must return contacts sorted closest-to-target first."""
        from meshweaver.kademlia.node_id import xor_distance

        store = PeerStore(local_id)
        ids = [generate_node_id(f"peer-{i}") for i in range(5)]
        for i, nid in enumerate(ids):
            store.add_or_update(nid, "10.0.0.1", 6000 + i)

        requester = FindNodeHandler(local_id_hex)
        responder = FindNodeHandler(node_id_to_hex(generate_node_id("responder")))
        request = requester.build_request(target_id_hex)
        _, response_bytes = responder.handle_request(request, store)
        contacts = requester.parse_response(response_bytes, target_id_hex)

        distances = [xor_distance(c.node_id, target_id) for c in contacts]
        assert distances == sorted(distances), "contacts must be sorted by XOR distance"

    # ------------------------------------------------------------------
    # Full PING + FIND_NODE integration
    # ------------------------------------------------------------------

    def test_ping_then_find_node_flow(self, local_id_hex, peer_id_hex,
                                       target_id_hex, local_id):
        """A peer that passes PING is queried with FIND_NODE."""
        store = PeerStore(local_id)
        peer_id = generate_node_id(PEER_SEED)
        store.add_or_update(peer_id, "127.0.0.1", 5001)

        ping_v_local = PingValidator(local_id_hex)
        ping_v_peer = PingValidator(peer_id_hex)
        fn_requester = FindNodeHandler(local_id_hex)
        fn_responder = FindNodeHandler(peer_id_hex)

        # Step 1: PING the peer
        peer_alive = ping_v_local.ping(
            send_recv=lambda req: ping_v_peer.handle_ping(req)
        )
        assert peer_alive, "peer should respond to PING"

        # Step 2: FIND_NODE via the validated peer
        request = fn_requester.build_request(target_id_hex)
        _, response_bytes = fn_responder.handle_request(request, store)
        contacts = fn_requester.parse_response(response_bytes, target_id_hex)

        assert isinstance(contacts, list)
        # The store had the peer; it should appear in contacts
        contact_ids = [c.node_id for c in contacts]
        assert peer_id in contact_ids
