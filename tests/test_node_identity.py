"""
tests/test_node_identity.py — Focused tests for Commit 12 (Days 13–14).

Covers:
    - NodeKeyPair construction and validation.
    - generate_keypair(): key sizes, randomness, determinism of public key.
    - node_id_from_keypair(): size, format, consistency.
    - save_keypair() / load_keypair(): round-trip, file content, error cases.

Run with:
    python -m pytest tests/test_node_identity.py -v
"""

import hashlib
import os
import tempfile

import pytest

from meshweaver.kademlia.identity import (
    NodeKeyPair,
    generate_keypair,
    load_keypair,
    node_id_from_keypair,
    save_keypair,
)
from meshweaver.kademlia.node_id import ID_BYTES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def keypair() -> NodeKeyPair:
    """A fresh random key pair for each test."""
    return generate_keypair()


@pytest.fixture()
def keypair2() -> NodeKeyPair:
    """A second independent key pair — guaranteed different from ``keypair``."""
    return generate_keypair()


@pytest.fixture()
def tmp_key_file(tmp_path) -> str:
    """Path to a temporary file (not yet created) for key persistence tests."""
    return str(tmp_path / "node.key")


# ---------------------------------------------------------------------------
# NodeKeyPair — construction and invariants
# ---------------------------------------------------------------------------


class TestNodeKeyPair:
    """Unit tests for NodeKeyPair dataclass invariants."""

    def test_frozen_dataclass(self, keypair):
        """NodeKeyPair must be immutable."""
        with pytest.raises((AttributeError, TypeError)):
            keypair.private_key = b"\x00" * 32  # type: ignore[misc]

    def test_private_key_is_bytes(self, keypair):
        assert isinstance(keypair.private_key, bytes)

    def test_public_key_is_bytes(self, keypair):
        assert isinstance(keypair.public_key, bytes)

    def test_private_key_length(self, keypair):
        assert len(keypair.private_key) == 32

    def test_public_key_length(self, keypair):
        assert len(keypair.public_key) == 32

    def test_public_key_is_sha256_of_private(self, keypair):
        """Public key must equal SHA-256(private_key)."""
        expected = hashlib.sha256(keypair.private_key).digest()
        assert keypair.public_key == expected

    def test_wrong_length_private_key_raises(self):
        priv = b"\x01" * 16  # only 16 bytes
        with pytest.raises(ValueError, match="private_key"):
            NodeKeyPair(private_key=priv, public_key=b"\x00" * 32)

    def test_wrong_length_public_key_raises(self):
        priv = b"\x01" * 32
        pub = b"\x00" * 16  # too short
        with pytest.raises(ValueError, match="public_key"):
            NodeKeyPair(private_key=priv, public_key=pub)

    def test_mismatched_public_key_raises(self):
        """Constructing with a public key that doesn't match SHA-256(private)."""
        priv = b"\x01" * 32
        wrong_pub = b"\xff" * 32  # not SHA-256(priv)
        with pytest.raises(ValueError, match="SHA-256"):
            NodeKeyPair(private_key=priv, public_key=wrong_pub)

    def test_public_key_hex_is_64_chars(self, keypair):
        assert len(keypair.public_key_hex()) == 64

    def test_public_key_hex_is_lowercase_hex(self, keypair):
        hex_str = keypair.public_key_hex()
        assert all(c in "0123456789abcdef" for c in hex_str)

    def test_equality_same_private_key(self):
        """Two NodeKeyPairs built from the same private key must be equal."""
        priv = b"\x42" * 32
        pub = hashlib.sha256(priv).digest()
        kp1 = NodeKeyPair(private_key=priv, public_key=pub)
        kp2 = NodeKeyPair(private_key=priv, public_key=pub)
        assert kp1 == kp2

    def test_inequality_different_private_keys(self, keypair, keypair2):
        """Two independently generated key pairs are extremely unlikely to match."""
        assert keypair != keypair2


# ---------------------------------------------------------------------------
# generate_keypair()
# ---------------------------------------------------------------------------


class TestGenerateKeypair:
    """Tests for the generate_keypair() factory function."""

    def test_returns_node_key_pair(self):
        kp = generate_keypair()
        assert isinstance(kp, NodeKeyPair)

    def test_private_key_32_bytes(self):
        kp = generate_keypair()
        assert len(kp.private_key) == 32

    def test_public_key_32_bytes(self):
        kp = generate_keypair()
        assert len(kp.public_key) == 32

    def test_public_key_deterministic_from_private(self):
        kp = generate_keypair()
        assert kp.public_key == hashlib.sha256(kp.private_key).digest()

    def test_each_call_produces_unique_private_key(self):
        """Two independent calls should produce different private keys."""
        kp1 = generate_keypair()
        kp2 = generate_keypair()
        assert kp1.private_key != kp2.private_key

    def test_each_call_produces_unique_public_key(self):
        kp1 = generate_keypair()
        kp2 = generate_keypair()
        assert kp1.public_key != kp2.public_key

    def test_private_key_not_all_zeros(self):
        """Sanity: a random key must not be all-zero bytes."""
        kp = generate_keypair()
        assert kp.private_key != b"\x00" * 32

    def test_multiple_calls_all_unique(self):
        """Generate 20 key pairs; all private keys should be distinct."""
        private_keys = {generate_keypair().private_key for _ in range(20)}
        assert len(private_keys) == 20


# ---------------------------------------------------------------------------
# node_id_from_keypair()
# ---------------------------------------------------------------------------


class TestNodeIdFromKeypair:
    """Tests for the node_id_from_keypair() function."""

    def test_returns_bytes(self, keypair):
        nid = node_id_from_keypair(keypair)
        assert isinstance(nid, bytes)

    def test_length_is_id_bytes(self, keypair):
        nid = node_id_from_keypair(keypair)
        assert len(nid) == ID_BYTES  # 32

    def test_deterministic_for_same_keypair(self, keypair):
        """Same key pair → same node ID every time."""
        nid1 = node_id_from_keypair(keypair)
        nid2 = node_id_from_keypair(keypair)
        assert nid1 == nid2

    def test_different_keypairs_different_node_ids(self, keypair, keypair2):
        nid1 = node_id_from_keypair(keypair)
        nid2 = node_id_from_keypair(keypair2)
        assert nid1 != nid2

    def test_node_id_is_sha256_of_public_key(self, keypair):
        """node_id must equal SHA-256(public_key)."""
        expected = hashlib.sha256(keypair.public_key).digest()
        assert node_id_from_keypair(keypair) == expected

    def test_invalid_input_raises(self):
        with pytest.raises(TypeError):
            node_id_from_keypair("not-a-keypair")  # type: ignore[arg-type]

    def test_node_id_compatible_with_existing_id_format(self, keypair):
        """node_id_from_keypair output is the same 32-byte format as
        generate_node_id(), confirmed by ID_BYTES check."""
        nid = node_id_from_keypair(keypair)
        assert len(nid) == ID_BYTES

    def test_different_key_loaded_vs_generated(self, keypair, tmp_key_file):
        """Save → load round-trip must produce the same node ID."""
        save_keypair(keypair, tmp_key_file)
        loaded = load_keypair(tmp_key_file)
        assert node_id_from_keypair(keypair) == node_id_from_keypair(loaded)


# ---------------------------------------------------------------------------
# save_keypair() / load_keypair()
# ---------------------------------------------------------------------------


class TestSaveLoadKeypair:
    """Tests for key persistence helpers."""

    def test_save_creates_file(self, keypair, tmp_key_file):
        save_keypair(keypair, tmp_key_file)
        assert os.path.exists(tmp_key_file)

    def test_save_file_is_text(self, keypair, tmp_key_file):
        save_keypair(keypair, tmp_key_file)
        with open(tmp_key_file, "r", encoding="ascii") as fh:
            content = fh.read()
        assert isinstance(content, str)

    def test_save_file_contains_header(self, keypair, tmp_key_file):
        save_keypair(keypair, tmp_key_file)
        with open(tmp_key_file) as fh:
            content = fh.read()
        assert "-----BEGIN MESHWEAVER PRIVATE KEY-----" in content

    def test_save_file_contains_footer(self, keypair, tmp_key_file):
        save_keypair(keypair, tmp_key_file)
        with open(tmp_key_file) as fh:
            content = fh.read()
        assert "-----END MESHWEAVER PRIVATE KEY-----" in content

    def test_roundtrip_private_key_restored(self, keypair, tmp_key_file):
        save_keypair(keypair, tmp_key_file)
        loaded = load_keypair(tmp_key_file)
        assert loaded.private_key == keypair.private_key

    def test_roundtrip_public_key_restored(self, keypair, tmp_key_file):
        save_keypair(keypair, tmp_key_file)
        loaded = load_keypair(tmp_key_file)
        assert loaded.public_key == keypair.public_key

    def test_roundtrip_full_equality(self, keypair, tmp_key_file):
        save_keypair(keypair, tmp_key_file)
        loaded = load_keypair(tmp_key_file)
        assert loaded == keypair

    def test_load_missing_file_raises_file_not_found(self, tmp_key_file):
        with pytest.raises(FileNotFoundError):
            load_keypair(tmp_key_file)

    def test_load_malformed_no_header_raises(self, tmp_key_file):
        with open(tmp_key_file, "w") as fh:
            fh.write("just some random text\n")
        with pytest.raises(ValueError, match="malformed"):
            load_keypair(tmp_key_file)

    def test_load_missing_footer_raises(self, tmp_key_file):
        with open(tmp_key_file, "w") as fh:
            fh.write("-----BEGIN MESHWEAVER PRIVATE KEY-----\naGVsbG8=\n")
        with pytest.raises(ValueError, match="malformed"):
            load_keypair(tmp_key_file)

    def test_load_wrong_key_length_raises(self, tmp_key_file):
        import base64

        bad_key = base64.b64encode(b"\x01" * 16).decode("ascii")
        with open(tmp_key_file, "w") as fh:
            fh.write(
                "-----BEGIN MESHWEAVER PRIVATE KEY-----\n"
                f"{bad_key}\n"
                "-----END MESHWEAVER PRIVATE KEY-----\n"
            )
        with pytest.raises(ValueError, match="wrong key length"):
            load_keypair(tmp_key_file)

    def test_save_wrong_type_raises(self, tmp_key_file):
        with pytest.raises(TypeError):
            save_keypair("not-a-keypair", tmp_key_file)  # type: ignore[arg-type]

    def test_multiple_save_load_roundtrips(self, tmp_path):
        """Save and load three independent key pairs from separate files."""
        for i in range(3):
            kp = generate_keypair()
            p = str(tmp_path / f"node{i}.key")
            save_keypair(kp, p)
            loaded = load_keypair(p)
            assert loaded == kp

    def test_load_restores_correct_public_key(self, keypair, tmp_key_file):
        """After loading, public_key == SHA-256(private_key) invariant holds."""
        save_keypair(keypair, tmp_key_file)
        loaded = load_keypair(tmp_key_file)
        assert loaded.public_key == hashlib.sha256(loaded.private_key).digest()
