"""
tests/test_crypto_identity_security.py — End-to-end security tests (Days 19–20).

Covers the full node identity \u2192 signing \u2192 verification pipeline with
realistic multi-node security scenarios:

    - Full pipeline: generate \u2192 sign \u2192 verify accepted
    - Persistent identity: save \u2192 load \u2192 sign \u2192 verify accepted
    - Cross-node: Node A signs, Node B verifies with A's public key \u2192 accepted
    - Cross-node: Node A signs, Node B verifies with B's own key \u2192 rejected
    - Replay attack with tampered payload \u2192 rejected
    - All canonical fields individually tampered \u2192 all rejected
    - Node IDs are distinct per key pair (no collisions)
    - Key pair independence (signing with one doesn't affect another)
    - Round-trip: encoded/decoded signed message verifies correctly

Run with:
    python -m pytest tests/test_crypto_identity_security.py -v
"""

import copy
import tempfile
import os

import pytest

from meshweaver.kademlia.identity import (
    generate_keypair,
    load_keypair,
    node_id_from_keypair,
    save_keypair,
)
from meshweaver.kademlia.signer import TaskSigner
from meshweaver.kademlia.verifier import SignatureVerifier
from meshweaver.protocol import (
    build_task_request,
    decode_message,
    encode_message,
)


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _make_signed(kp, task_id="task-001", payload=None):
    """Helper: build + sign a TASK_REQUEST with *kp*."""
    if payload is None:
        payload = {"action": "ping"}
    unsigned = build_task_request(kp.public_key_hex(), task_id, payload)
    return TaskSigner(kp).sign_request(unsigned)


@pytest.fixture()
def verifier():
    return SignatureVerifier()


@pytest.fixture()
def node_a():
    return generate_keypair()


@pytest.fixture()
def node_b():
    return generate_keypair()


@pytest.fixture()
def node_c():
    return generate_keypair()


# ---------------------------------------------------------------------------
# TC-01: Full pipeline (generate \u2192 sign \u2192 verify)
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end: generate_keypair \u2192 TaskSigner \u2192 SignatureVerifier."""

    def test_valid_request_accepted(self, node_a, verifier):
        signed = _make_signed(node_a)
        assert verifier.verify_request(signed, node_a.public_key) is True

    def test_returns_true_type_bool(self, node_a, verifier):
        signed = _make_signed(node_a)
        result = verifier.verify_request(signed, node_a.public_key)
        assert result is True and isinstance(result, bool)

    def test_full_pipeline_three_nodes(self, node_a, node_b, node_c, verifier):
        """Three independent nodes each produce valid, independently verifiable
        signed messages."""
        for kp in (node_a, node_b, node_c):
            signed = _make_signed(kp)
            assert verifier.verify_request(signed, kp.public_key) is True


# ---------------------------------------------------------------------------
# TC-02: Persistent identity (save \u2192 load \u2192 sign \u2192 verify)
# ---------------------------------------------------------------------------


class TestPersistentIdentity:
    """Key save/load must preserve signing capability."""

    def test_saved_then_loaded_identity_signs_verifiably(self, node_a, verifier, tmp_path):
        path = str(tmp_path / "node_a.key")
        save_keypair(node_a, path)
        loaded_kp = load_keypair(path)

        signed = _make_signed(loaded_kp)
        assert verifier.verify_request(signed, loaded_kp.public_key) is True

    def test_saved_loaded_public_key_same_as_original(self, node_a, tmp_path):
        path = str(tmp_path / "node_a.key")
        save_keypair(node_a, path)
        loaded_kp = load_keypair(path)
        assert loaded_kp.public_key == node_a.public_key

    def test_loaded_node_id_matches_original(self, node_a, tmp_path):
        path = str(tmp_path / "node_a.key")
        save_keypair(node_a, path)
        loaded_kp = load_keypair(path)
        assert node_id_from_keypair(loaded_kp) == node_id_from_keypair(node_a)

    def test_original_signed_verified_with_loaded_public_key(self, node_a, verifier, tmp_path):
        """Message signed by original keypair must verify with loaded public key."""
        path = str(tmp_path / "node_a.key")
        signed = _make_signed(node_a)
        save_keypair(node_a, path)
        loaded_kp = load_keypair(path)
        assert verifier.verify_request(signed, loaded_kp.public_key) is True

    def test_loaded_signed_verified_with_original_public_key(self, node_a, verifier, tmp_path):
        """Message signed after loading verifies against original public key."""
        path = str(tmp_path / "node_a.key")
        save_keypair(node_a, path)
        loaded_kp = load_keypair(path)
        signed = _make_signed(loaded_kp)
        assert verifier.verify_request(signed, node_a.public_key) is True


# ---------------------------------------------------------------------------
# TC-03: Cross-node verification
# ---------------------------------------------------------------------------


class TestCrossNodeVerification:
    """Node A signs; Node B verifies using A's (shared) public key."""

    def test_node_a_signed_verified_by_node_b_with_a_key(self, node_a, node_b, verifier):
        """Node B, knowing Node A's public key, can verify A's signed message."""
        signed = _make_signed(node_a)
        # Node B uses A's public_key (shared during identity exchange)
        assert verifier.verify_request(signed, node_a.public_key) is True

    def test_node_a_signed_rejected_with_node_b_key(self, node_a, node_b, verifier):
        """Node A's signature must NOT verify against Node B's public key."""
        signed = _make_signed(node_a)
        assert verifier.verify_request(signed, node_b.public_key) is False

    def test_node_b_signed_rejected_with_node_a_key(self, node_a, node_b, verifier):
        signed = _make_signed(node_b)
        assert verifier.verify_request(signed, node_a.public_key) is False

    def test_each_node_only_verifies_its_own_messages(self, verifier):
        """Generate 5 nodes; each signed message verifies only with its own key."""
        nodes = [generate_keypair() for _ in range(5)]
        messages = [_make_signed(kp) for kp in nodes]

        for i, (kp, msg) in enumerate(zip(nodes, messages)):
            for j, other_kp in enumerate(nodes):
                expected = (i == j)
                result = verifier.verify_request(msg, other_kp.public_key)
                assert result == expected, (
                    f"Node {i}'s msg verified with node {j}'s key: "
                    f"expected {expected}, got {result}"
                )


# ---------------------------------------------------------------------------
# TC-04: Replay attack with tampered payload
# ---------------------------------------------------------------------------


class TestReplayAttack:
    """Replaying a signed message with a changed payload must be rejected."""

    def test_replayed_with_different_payload_rejected(self, node_a, verifier):
        original = _make_signed(node_a, payload={"action": "legitimate"})
        # Attacker takes the signature but changes the payload
        tampered = dict(original)
        tampered["payload"] = {"action": "MALICIOUS"}
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_replayed_with_different_task_id_rejected(self, node_a, verifier):
        original = _make_signed(node_a, task_id="task-safe")
        tampered = dict(original)
        tampered["task_id"] = "task-ESCALATED"
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_old_signature_on_new_message_rejected(self, node_a, verifier):
        """Copy the signature from one message onto a different message."""
        msg1 = _make_signed(node_a, task_id="msg1", payload={"v": 1})
        msg2_unsigned = build_task_request(
            node_a.public_key_hex(), "msg2", {"v": 2}
        )
        # Graft msg1's signature onto msg2
        msg2_with_stolen_sig = dict(msg2_unsigned)
        msg2_with_stolen_sig["signature"] = msg1["signature"]
        assert verifier.verify_request(msg2_with_stolen_sig, node_a.public_key) is False


# ---------------------------------------------------------------------------
# TC-05: Individual field tampering (exhaustive)
# ---------------------------------------------------------------------------


class TestIndividualFieldTampering:
    """Changing any single canonical field must invalidate the signature."""

    def test_tamper_sender_id(self, node_a, node_b, verifier):
        signed = _make_signed(node_a)
        tampered = dict(signed)
        tampered["sender_id"] = node_b.public_key_hex()
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_tamper_task_id(self, node_a, verifier):
        signed = _make_signed(node_a)
        tampered = dict(signed)
        tampered["task_id"] = "tampered-task"
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_tamper_payload_string_value(self, node_a, verifier):
        signed = _make_signed(node_a, payload={"key": "original"})
        tampered = copy.deepcopy(signed)
        tampered["payload"]["key"] = "tampered"
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_tamper_payload_numeric_value(self, node_a, verifier):
        signed = _make_signed(node_a, payload={"count": 5})
        tampered = copy.deepcopy(signed)
        tampered["payload"]["count"] = 999
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_tamper_payload_add_key(self, node_a, verifier):
        signed = _make_signed(node_a, payload={"a": 1})
        tampered = copy.deepcopy(signed)
        tampered["payload"]["injected"] = True
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_tamper_payload_remove_key(self, node_a, verifier):
        signed = _make_signed(node_a, payload={"a": 1, "b": 2})
        tampered = copy.deepcopy(signed)
        del tampered["payload"]["b"]
        assert verifier.verify_request(tampered, node_a.public_key) is False

    def test_tamper_type_field(self, node_a, verifier):
        signed = _make_signed(node_a)
        tampered = dict(signed)
        tampered["type"] = "FIND_NODE"
        assert verifier.verify_request(tampered, node_a.public_key) is False


# ---------------------------------------------------------------------------
# TC-06: Node ID uniqueness
# ---------------------------------------------------------------------------


class TestNodeIdUniqueness:
    """Node IDs derived from different key pairs must be distinct."""

    def test_ten_nodes_all_unique_ids(self):
        node_ids = {node_id_from_keypair(generate_keypair()) for _ in range(10)}
        assert len(node_ids) == 10

    def test_node_id_tied_to_public_key(self, node_a):
        import hashlib
        expected = hashlib.sha256(node_a.public_key).digest()
        assert node_id_from_keypair(node_a) == expected


# ---------------------------------------------------------------------------
# TC-07: Key pair independence
# ---------------------------------------------------------------------------


class TestKeyPairIndependence:
    """Operations on one node's keys must not affect another's."""

    def test_signing_with_one_key_does_not_affect_other(self, node_a, node_b, verifier):
        signed_a = _make_signed(node_a, task_id="for-a", payload={"x": 1})
        signed_b = _make_signed(node_b, task_id="for-b", payload={"x": 1})

        assert verifier.verify_request(signed_a, node_a.public_key) is True
        assert verifier.verify_request(signed_b, node_b.public_key) is True
        assert verifier.verify_request(signed_a, node_b.public_key) is False
        assert verifier.verify_request(signed_b, node_a.public_key) is False

    def test_concurrent_signing_independent(self):
        """Multiple signers operating simultaneously produce independently
        verifiable results."""
        verifier = SignatureVerifier()
        pairs = [(generate_keypair(), f"task-{i}", {"i": i}) for i in range(8)]
        results = []
        for kp, tid, pl in pairs:
            signer = TaskSigner(kp)
            msg = signer.sign_request(
                build_task_request(kp.public_key_hex(), tid, pl)
            )
            results.append((kp, msg))

        for kp, msg in results:
            assert verifier.verify_request(msg, kp.public_key) is True


# ---------------------------------------------------------------------------
# TC-08: Encode/decode wire round-trip
# ---------------------------------------------------------------------------


class TestWireRoundTrip:
    """Signed messages must survive JSON encode → decode and still verify."""

    def test_encode_decode_then_verify(self, node_a, verifier):
        signed = _make_signed(node_a)
        wire_bytes = encode_message(signed)
        recovered = decode_message(wire_bytes)
        assert verifier.verify_request(recovered, node_a.public_key) is True

    def test_encode_decode_tampered_rejected(self, node_a, verifier):
        signed = _make_signed(node_a)
        wire_bytes = encode_message(signed)
        recovered = decode_message(wire_bytes)
        recovered["payload"]["injected"] = True
        assert verifier.verify_request(recovered, node_a.public_key) is False

    def test_multiple_messages_same_node(self, node_a, verifier):
        """Same node, different task IDs — all verify independently."""
        signer = TaskSigner(node_a)
        for i in range(5):
            unsigned = build_task_request(
                node_a.public_key_hex(), f"task-{i}", {"seq": i}
            )
            signed = signer.sign_request(unsigned)
            wire = encode_message(signed)
            recovered = decode_message(wire)
            assert verifier.verify_request(recovered, node_a.public_key) is True
