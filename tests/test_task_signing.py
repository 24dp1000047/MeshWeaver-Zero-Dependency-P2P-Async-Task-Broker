"""
tests/test_task_signing.py — Focused tests for Commit 13 (Days 15–16).

Covers:
    - build_task_request(): field presence, validation, types.
    - canonical_payload(): determinism, field coverage, exclusions.
    - TaskSigner.sign_request(): signature presence, format, determinism,
      sensitivity to payload changes, compatibility with build_task_request.

Run with:
    python -m pytest tests/test_task_signing.py -v
"""

import hashlib
import hmac
import json

import pytest

from meshweaver.kademlia.identity import generate_keypair, node_id_from_keypair
from meshweaver.kademlia.signer import TaskSigner, canonical_payload
from meshweaver.protocol import (
    MSG_TASK_REQUEST,
    build_task_request,
    decode_message,
    encode_message,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kp():
    """A fresh key pair for each test."""
    return generate_keypair()


@pytest.fixture()
def kp2():
    """A second independent key pair."""
    return generate_keypair()


@pytest.fixture()
def sender_id_hex(kp) -> str:
    return kp.public_key_hex()


@pytest.fixture()
def unsigned_msg(sender_id_hex) -> dict:
    return build_task_request(
        sender_id_hex=sender_id_hex,
        task_id="task-abc-123",
        payload={"fn": "compute", "args": [1, 2]},
    )


@pytest.fixture()
def signer(kp) -> TaskSigner:
    return TaskSigner(kp)


# ---------------------------------------------------------------------------
# build_task_request() — protocol builder
# ---------------------------------------------------------------------------


class TestBuildTaskRequest:
    """Tests for the build_task_request() protocol builder."""

    def test_type_is_task_request(self, sender_id_hex):
        msg = build_task_request(sender_id_hex, "t1", {})
        assert msg["type"] == MSG_TASK_REQUEST

    def test_sender_id_present(self, sender_id_hex):
        msg = build_task_request(sender_id_hex, "t1", {})
        assert msg["sender_id"] == sender_id_hex

    def test_task_id_present(self, sender_id_hex):
        msg = build_task_request(sender_id_hex, "my-task", {})
        assert msg["task_id"] == "my-task"

    def test_payload_present(self, sender_id_hex):
        pl = {"key": "value", "num": 42}
        msg = build_task_request(sender_id_hex, "t2", pl)
        assert msg["payload"] == pl

    def test_no_signature_field(self, sender_id_hex):
        """Unsigned message must NOT have a signature field."""
        msg = build_task_request(sender_id_hex, "t3", {})
        assert "signature" not in msg

    def test_empty_sender_raises(self):
        with pytest.raises(ValueError):
            build_task_request("", "task-1", {})

    def test_empty_task_id_raises(self, sender_id_hex):
        with pytest.raises(ValueError):
            build_task_request(sender_id_hex, "", {})

    def test_payload_not_dict_raises(self, sender_id_hex):
        with pytest.raises(TypeError):
            build_task_request(sender_id_hex, "t", "not-a-dict")  # type: ignore[arg-type]

    def test_returns_dict(self, sender_id_hex):
        msg = build_task_request(sender_id_hex, "t", {})
        assert isinstance(msg, dict)

    def test_encode_decode_roundtrip(self, sender_id_hex):
        msg = build_task_request(sender_id_hex, "rt", {"x": 1})
        assert decode_message(encode_message(msg)) == msg

    def test_empty_payload_allowed(self, sender_id_hex):
        msg = build_task_request(sender_id_hex, "t", {})
        assert msg["payload"] == {}

    def test_nested_payload_allowed(self, sender_id_hex):
        pl = {"nested": {"a": [1, 2, 3]}}
        msg = build_task_request(sender_id_hex, "t", pl)
        assert msg["payload"] == pl


# ---------------------------------------------------------------------------
# canonical_payload()
# ---------------------------------------------------------------------------


class TestCanonicalPayload:
    """Tests for the canonical_payload() helper."""

    def test_returns_bytes(self, unsigned_msg):
        assert isinstance(canonical_payload(unsigned_msg), bytes)

    def test_deterministic_same_message(self, unsigned_msg):
        b1 = canonical_payload(unsigned_msg)
        b2 = canonical_payload(unsigned_msg)
        assert b1 == b2

    def test_excludes_signature_field(self, signer, unsigned_msg):
        """Adding a signature field must not change the canonical payload."""
        signed = signer.sign_request(unsigned_msg)
        assert canonical_payload(unsigned_msg) == canonical_payload(signed)

    def test_covers_type_field(self, unsigned_msg):
        altered = dict(unsigned_msg)
        altered["type"] = "OTHER_TYPE"
        # Should raise because type != TASK_REQUEST
        with pytest.raises(ValueError):
            canonical_payload(altered)

    def test_covers_sender_id(self, unsigned_msg, kp2):
        altered = dict(unsigned_msg)
        altered["sender_id"] = kp2.public_key_hex()
        assert canonical_payload(unsigned_msg) != canonical_payload(altered)

    def test_covers_task_id(self, unsigned_msg):
        altered = dict(unsigned_msg)
        altered["task_id"] = "completely-different-id"
        assert canonical_payload(unsigned_msg) != canonical_payload(altered)

    def test_covers_payload(self, sender_id_hex):
        msg1 = build_task_request(sender_id_hex, "t", {"a": 1})
        msg2 = build_task_request(sender_id_hex, "t", {"a": 2})
        assert canonical_payload(msg1) != canonical_payload(msg2)

    def test_non_task_request_raises(self, sender_id_hex):
        bad = {"type": "PING", "sender_id": sender_id_hex, "token": "tok"}
        with pytest.raises(ValueError, match="TASK_REQUEST"):
            canonical_payload(bad)

    def test_is_valid_json(self, unsigned_msg):
        raw = canonical_payload(unsigned_msg).decode("utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_keys_are_sorted(self, unsigned_msg):
        raw = canonical_payload(unsigned_msg).decode("utf-8")
        parsed = json.loads(raw)
        assert list(parsed.keys()) == sorted(parsed.keys())

    def test_missing_required_field_raises(self, sender_id_hex):
        bad = {"type": MSG_TASK_REQUEST, "sender_id": sender_id_hex}
        with pytest.raises(KeyError):
            canonical_payload(bad)


# ---------------------------------------------------------------------------
# TaskSigner
# ---------------------------------------------------------------------------


class TestTaskSignerConstruction:
    """Construction and type-checking tests for TaskSigner."""

    def test_accepts_valid_keypair(self, kp):
        signer = TaskSigner(kp)
        assert signer is not None

    def test_wrong_type_raises(self):
        with pytest.raises(TypeError):
            TaskSigner("not-a-keypair")  # type: ignore[arg-type]

    def test_keypair_property(self, kp):
        signer = TaskSigner(kp)
        assert signer.keypair is kp


class TestTaskSignerSignRequest:
    """Tests for TaskSigner.sign_request()."""

    def test_returns_dict(self, signer, unsigned_msg):
        result = signer.sign_request(unsigned_msg)
        assert isinstance(result, dict)

    def test_signature_field_present(self, signer, unsigned_msg):
        signed = signer.sign_request(unsigned_msg)
        assert "signature" in signed

    def test_signature_is_string(self, signer, unsigned_msg):
        signed = signer.sign_request(unsigned_msg)
        assert isinstance(signed["signature"], str)

    def test_signature_is_64_chars(self, signer, unsigned_msg):
        """HMAC-SHA256 produces 32 bytes → 64 hex chars."""
        signed = signer.sign_request(unsigned_msg)
        assert len(signed["signature"]) == 64

    def test_signature_is_lowercase_hex(self, signer, unsigned_msg):
        signed = signer.sign_request(unsigned_msg)
        sig = signed["signature"]
        assert all(c in "0123456789abcdef" for c in sig)

    def test_original_message_not_mutated(self, signer, unsigned_msg):
        original_keys = set(unsigned_msg.keys())
        signer.sign_request(unsigned_msg)
        assert set(unsigned_msg.keys()) == original_keys
        assert "signature" not in unsigned_msg

    def test_deterministic_same_key_same_message(self, signer, unsigned_msg):
        """Signing the same message with the same key must produce the same
        signature (HMAC is deterministic)."""
        sig1 = signer.sign_request(unsigned_msg)["signature"]
        sig2 = signer.sign_request(unsigned_msg)["signature"]
        assert sig1 == sig2

    def test_different_payload_different_signature(self, kp, sender_id_hex):
        signer = TaskSigner(kp)
        msg1 = build_task_request(sender_id_hex, "t", {"a": 1})
        msg2 = build_task_request(sender_id_hex, "t", {"a": 2})
        sig1 = signer.sign_request(msg1)["signature"]
        sig2 = signer.sign_request(msg2)["signature"]
        assert sig1 != sig2

    def test_different_task_id_different_signature(self, kp, sender_id_hex):
        signer = TaskSigner(kp)
        msg1 = build_task_request(sender_id_hex, "task-A", {})
        msg2 = build_task_request(sender_id_hex, "task-B", {})
        assert signer.sign_request(msg1)["signature"] != \
               signer.sign_request(msg2)["signature"]

    def test_different_sender_id_different_signature(self, kp, kp2):
        signer = TaskSigner(kp)
        msg1 = build_task_request(kp.public_key_hex(), "t", {})
        msg2 = build_task_request(kp2.public_key_hex(), "t", {})
        assert signer.sign_request(msg1)["signature"] != \
               signer.sign_request(msg2)["signature"]

    def test_different_keys_different_signatures(self, kp, kp2, sender_id_hex):
        """Two signers with different key pairs must produce different signatures
        for the same message content."""
        s1 = TaskSigner(kp)
        s2 = TaskSigner(kp2)
        msg = build_task_request(sender_id_hex, "t", {"x": 1})
        assert s1.sign_request(msg)["signature"] != s2.sign_request(msg)["signature"]

    def test_other_fields_preserved(self, signer, unsigned_msg):
        signed = signer.sign_request(unsigned_msg)
        for key in ("type", "sender_id", "task_id", "payload"):
            assert signed[key] == unsigned_msg[key]

    def test_signature_matches_hmac_manually(self, kp, sender_id_hex):
        """Manually compute HMAC and confirm it matches sign_request output."""
        signer = TaskSigner(kp)
        msg = build_task_request(sender_id_hex, "manual-check", {"v": 99})
        signed = signer.sign_request(msg)

        payload_bytes = canonical_payload(msg)
        expected_sig = hmac.new(
            kp.public_key, payload_bytes, hashlib.sha256
        ).hexdigest()
        assert signed["signature"] == expected_sig

    def test_non_task_request_raises(self, signer, sender_id_hex):
        bad = {"type": "PING", "sender_id": sender_id_hex, "token": "t"}
        with pytest.raises(ValueError):
            signer.sign_request(bad)

    def test_signed_message_encode_decode_roundtrip(self, signer, unsigned_msg):
        signed = signer.sign_request(unsigned_msg)
        assert decode_message(encode_message(signed)) == signed
