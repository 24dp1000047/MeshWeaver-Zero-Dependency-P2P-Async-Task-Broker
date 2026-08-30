"""
tests/test_signature_verification.py — Focused tests for Commit 14 (Days 17–18).

Covers:
    - SignatureVerifier.verify_request(): valid signatures, wrong public key,
      tampered fields (task_id, payload, sender_id, type), missing signature,
      truncated / garbage signature strings, wrong public key length.

Run with:
    python -m pytest tests/test_signature_verification.py -v
"""

import copy

import pytest

from meshweaver.kademlia.identity import generate_keypair
from meshweaver.kademlia.signer import TaskSigner
from meshweaver.kademlia.verifier import SignatureVerifier
from meshweaver.protocol import build_task_request


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kp():
    return generate_keypair()


@pytest.fixture()
def kp_other():
    """A different key pair — used to simulate a wrong/foreign public key."""
    return generate_keypair()


@pytest.fixture()
def signer(kp):
    return TaskSigner(kp)


@pytest.fixture()
def verifier():
    return SignatureVerifier()


@pytest.fixture()
def signed_msg(kp, signer):
    unsigned = build_task_request(
        sender_id_hex=kp.public_key_hex(),
        task_id="test-task-001",
        payload={"op": "sum", "values": [10, 20]},
    )
    return signer.sign_request(unsigned)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSignatureVerifierConstruction:
    def test_instantiates(self):
        v = SignatureVerifier()
        assert v is not None

    def test_stateless_reusable(self, kp, signed_msg):
        """A single verifier instance can verify multiple independent messages."""
        v = SignatureVerifier()
        assert v.verify_request(signed_msg, kp.public_key) is True
        assert v.verify_request(signed_msg, kp.public_key) is True


# ---------------------------------------------------------------------------
# Valid signature — must return True
# ---------------------------------------------------------------------------


class TestVerifyRequestValid:
    """verify_request() must return True for correctly signed messages."""

    def test_valid_signed_message_accepted(self, verifier, signed_msg, kp):
        assert verifier.verify_request(signed_msg, kp.public_key) is True

    def test_returns_bool(self, verifier, signed_msg, kp):
        result = verifier.verify_request(signed_msg, kp.public_key)
        assert isinstance(result, bool)

    def test_valid_with_empty_payload(self, kp, verifier):
        signer = TaskSigner(kp)
        msg = signer.sign_request(
            build_task_request(kp.public_key_hex(), "empty-payload", {})
        )
        assert verifier.verify_request(msg, kp.public_key) is True

    def test_valid_with_nested_payload(self, kp, verifier):
        signer = TaskSigner(kp)
        msg = signer.sign_request(
            build_task_request(
                kp.public_key_hex(),
                "nested",
                {"level1": {"level2": [1, 2, 3]}},
            )
        )
        assert verifier.verify_request(msg, kp.public_key) is True

    def test_valid_different_task_ids(self, kp, verifier):
        signer = TaskSigner(kp)
        for task_id in ("task-A", "task-B", "task-C"):
            msg = signer.sign_request(
                build_task_request(kp.public_key_hex(), task_id, {"n": 1})
            )
            assert verifier.verify_request(msg, kp.public_key) is True

    def test_multiple_independent_keypairs(self, verifier):
        """Each node's signed message verifies only with its own public key."""
        pairs = [(generate_keypair(),) for _ in range(3)]
        messages = []
        for (kp,) in pairs:
            signer = TaskSigner(kp)
            msg = signer.sign_request(
                build_task_request(kp.public_key_hex(), "t", {})
            )
            messages.append((kp, msg))

        for kp, msg in messages:
            assert verifier.verify_request(msg, kp.public_key) is True


# ---------------------------------------------------------------------------
# Wrong public key — must return False
# ---------------------------------------------------------------------------


class TestVerifyRequestWrongKey:
    """verify_request() must return False if the wrong public key is supplied."""

    def test_wrong_public_key_rejected(self, verifier, signed_msg, kp_other):
        assert verifier.verify_request(signed_msg, kp_other.public_key) is False

    def test_all_zeros_key_rejected(self, verifier, signed_msg):
        assert verifier.verify_request(signed_msg, b"\x00" * 32) is False

    def test_all_ones_key_rejected(self, verifier, signed_msg):
        assert verifier.verify_request(signed_msg, b"\xff" * 32) is False

    def test_wrong_length_key_rejected(self, verifier, signed_msg):
        assert verifier.verify_request(signed_msg, b"\x00" * 16) is False

    def test_empty_key_rejected(self, verifier, signed_msg):
        assert verifier.verify_request(signed_msg, b"") is False

    def test_key_off_by_one_byte_rejected(self, verifier, signed_msg, kp):
        """Flip one byte of the correct public key — must be rejected."""
        bad_key = bytearray(kp.public_key)
        bad_key[0] ^= 0xFF  # flip all bits of first byte
        assert verifier.verify_request(signed_msg, bytes(bad_key)) is False


# ---------------------------------------------------------------------------
# Tampered fields — must return False
# ---------------------------------------------------------------------------


class TestVerifyRequestTamperedFields:
    """verify_request() must detect any modification to signed fields."""

    def test_tampered_task_id(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["task_id"] = "evil-task-id"
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_tampered_payload_value(self, verifier, signed_msg, kp):
        tampered = copy.deepcopy(signed_msg)
        tampered["payload"]["op"] = "INJECTED"
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_tampered_payload_new_key(self, verifier, signed_msg, kp):
        tampered = copy.deepcopy(signed_msg)
        tampered["payload"]["extra"] = "injected"
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_tampered_sender_id(self, verifier, signed_msg, kp, kp_other):
        tampered = dict(signed_msg)
        tampered["sender_id"] = kp_other.public_key_hex()
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_tampered_type_field(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["type"] = "PING"  # wrong type → canonical_payload raises → False
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_tampered_signature_directly(self, verifier, signed_msg, kp):
        """Manually editing the signature hex string must be rejected."""
        tampered = dict(signed_msg)
        # Flip the last character
        original_sig = tampered["signature"]
        flip = "f" if original_sig[-1] != "f" else "0"
        tampered["signature"] = original_sig[:-1] + flip
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_tampered_payload_cleared(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["payload"] = {}
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_added_extra_field_does_not_affect_valid(self, verifier, signed_msg, kp):
        """Extra fields outside the canonical set must NOT invalidate the signature
        (canonical_payload only covers the 4 fixed fields)."""
        with_extra = dict(signed_msg)
        with_extra["extra_metadata"] = "ignored"
        assert verifier.verify_request(with_extra, kp.public_key) is True


# ---------------------------------------------------------------------------
# Missing / malformed signature
# ---------------------------------------------------------------------------


class TestVerifyRequestBadSignature:
    """verify_request() must return False when signature is absent or malformed."""

    def test_missing_signature_field(self, verifier, kp):
        unsigned = build_task_request(kp.public_key_hex(), "t", {})
        assert verifier.verify_request(unsigned, kp.public_key) is False

    def test_none_signature(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["signature"] = None
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_empty_string_signature(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["signature"] = ""
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_truncated_signature(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["signature"] = signed_msg["signature"][:32]  # half length
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_garbage_bytes_signature(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["signature"] = "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_non_string_signature(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["signature"] = 12345  # wrong type
        assert verifier.verify_request(tampered, kp.public_key) is False

    def test_all_zeros_signature(self, verifier, signed_msg, kp):
        tampered = dict(signed_msg)
        tampered["signature"] = "00" * 32
        assert verifier.verify_request(tampered, kp.public_key) is False


# ---------------------------------------------------------------------------
# Malformed message structures
# ---------------------------------------------------------------------------


class TestVerifyRequestMalformedMessage:
    """verify_request() must not raise for any input \u2014 always returns bool."""

    def test_non_dict_message(self, verifier, kp):
        assert verifier.verify_request("not-a-dict", kp.public_key) is False  # type: ignore[arg-type]

    def test_empty_dict(self, verifier, kp):
        assert verifier.verify_request({}, kp.public_key) is False

    def test_missing_required_fields(self, verifier, kp):
        minimal = {"type": "TASK_REQUEST", "signature": "ab" * 32}
        assert verifier.verify_request(minimal, kp.public_key) is False

    def test_non_bytes_public_key(self, verifier, signed_msg):
        assert verifier.verify_request(signed_msg, "not-bytes") is False  # type: ignore[arg-type]

    def test_none_public_key(self, verifier, signed_msg):
        assert verifier.verify_request(signed_msg, None) is False  # type: ignore[arg-type]
