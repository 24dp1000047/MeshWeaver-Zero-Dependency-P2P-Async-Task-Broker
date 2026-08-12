"""
tests/test_node_id.py — Tests for SHA-256 based node ID generation.

Scope (Commit 1):
    - generate_node_id()
    - node_id_to_hex()
    - node_id_from_hex()
    - ID_BITS / ID_BYTES constants

Run with:
    python -m pytest tests/test_node_id.py -v
"""

import hashlib

import pytest

from meshweaver.kademlia.node_id import (
    ID_BITS,
    ID_BYTES,
    generate_node_id,
    node_id_from_hex,
    node_id_to_hex,
)


# ===========================================================================
# generate_node_id
# ===========================================================================


class TestGenerateNodeId:
    def test_returns_bytes(self):
        nid = generate_node_id("127.0.0.1:5000")
        assert isinstance(nid, bytes)

    def test_length_is_32_bytes(self):
        nid = generate_node_id("any seed")
        assert len(nid) == 32

    def test_id_bits_and_id_bytes_constants(self):
        """ID_BITS must be 256 and ID_BYTES must be 32."""
        assert ID_BITS == 256
        assert ID_BYTES == 32

    def test_deterministic_same_seed(self):
        """Calling generate_node_id twice with the same seed yields the same ID."""
        seed = "192.168.1.10:6000"
        assert generate_node_id(seed) == generate_node_id(seed)

    def test_matches_hashlib_sha256(self):
        """Output must equal hashlib.sha256(seed.encode('utf-8')).digest()."""
        seed = "test-node"
        expected = hashlib.sha256(seed.encode("utf-8")).digest()
        assert generate_node_id(seed) == expected

    def test_different_seeds_produce_different_ids(self):
        assert generate_node_id("node-a") != generate_node_id("node-b")

    def test_empty_seed_raises_value_error(self):
        with pytest.raises(ValueError, match="non-empty"):
            generate_node_id("")

    def test_unicode_seed_accepted(self):
        """Non-ASCII seeds are valid and produce a 32-byte ID."""
        nid = generate_node_id("nœud-α:9000")
        assert len(nid) == ID_BYTES

    def test_host_port_style_seed(self):
        """A 'host:port' seed — the primary intended use case — works correctly."""
        nid = generate_node_id("10.0.0.1:4000")
        assert len(nid) == ID_BYTES
        assert isinstance(nid, bytes)

    def test_whitespace_only_seed_is_accepted(self):
        """A non-empty whitespace seed is technically valid (not empty)."""
        nid = generate_node_id("   ")
        assert len(nid) == ID_BYTES


# ===========================================================================
# node_id_to_hex
# ===========================================================================


class TestNodeIdToHex:
    def test_hex_string_is_64_chars(self):
        nid = generate_node_id("127.0.0.1:5000")
        assert len(node_id_to_hex(nid)) == 64

    def test_hex_string_is_lowercase(self):
        nid = generate_node_id("127.0.0.1:5000")
        h = node_id_to_hex(nid)
        assert h == h.lower()

    def test_hex_string_is_valid_hex(self):
        nid = generate_node_id("127.0.0.1:5000")
        h = node_id_to_hex(nid)
        # Must not raise
        int(h, 16)

    def test_wrong_length_raises_value_error(self):
        with pytest.raises(ValueError):
            node_id_to_hex(b"\x00" * 10)

    def test_empty_bytes_raises_value_error(self):
        with pytest.raises(ValueError):
            node_id_to_hex(b"")


# ===========================================================================
# node_id_from_hex
# ===========================================================================


class TestNodeIdFromHex:
    def test_roundtrip_to_hex_and_back(self):
        nid = generate_node_id("127.0.0.1:7777")
        assert node_id_from_hex(node_id_to_hex(nid)) == nid

    def test_returns_bytes(self):
        nid = generate_node_id("some-node")
        result = node_id_from_hex(node_id_to_hex(nid))
        assert isinstance(result, bytes)

    def test_returns_32_bytes(self):
        nid = generate_node_id("some-node")
        result = node_id_from_hex(node_id_to_hex(nid))
        assert len(result) == ID_BYTES

    def test_wrong_length_hex_raises_value_error(self):
        # 10 bytes → 20 hex chars, not 64
        with pytest.raises(ValueError):
            node_id_from_hex("aa" * 10)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            node_id_from_hex("")
