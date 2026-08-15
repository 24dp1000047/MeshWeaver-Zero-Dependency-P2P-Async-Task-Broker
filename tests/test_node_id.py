"""
tests/test_node_id.py — Tests for SHA-256 based node ID generation.

Scope (Commit 1):
    - generate_node_id()
    - node_id_to_hex()
    - node_id_from_hex()
    - ID_BITS / ID_BYTES constants

Scope (Commit 4):
    - xor_distance()

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
    xor_distance,
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


# ===========================================================================
# xor_distance  (Commit 4)
# ===========================================================================


class TestXorDistance:
    """Tests for xor_distance(a, b) — the Kademlia XOR metric."""

    # ------------------------------------------------------------------
    # Basic type and value properties
    # ------------------------------------------------------------------

    def test_returns_int(self):
        """xor_distance must return a Python int."""
        a = generate_node_id("node-a")
        b = generate_node_id("node-b")
        assert isinstance(xor_distance(a, b), int)

    def test_distance_is_non_negative(self):
        """XOR of two unsigned values is always ≥ 0."""
        a = generate_node_id("127.0.0.1:5000")
        b = generate_node_id("127.0.0.1:5001")
        assert xor_distance(a, b) >= 0

    # ------------------------------------------------------------------
    # Identity: distance to itself is 0
    # ------------------------------------------------------------------

    def test_identity_same_id(self):
        """XOR(x, x) == 0 for any node ID."""
        nid = generate_node_id("127.0.0.1:5000")
        assert xor_distance(nid, nid) == 0

    def test_identity_zero_bytes(self):
        """All-zero ID XOR'd with itself is 0."""
        zero = b"\x00" * ID_BYTES
        assert xor_distance(zero, zero) == 0

    def test_identity_all_ones(self):
        """All-0xFF ID XOR'd with itself is 0."""
        ones = b"\xff" * ID_BYTES
        assert xor_distance(ones, ones) == 0

    # ------------------------------------------------------------------
    # Symmetry: distance(a, b) == distance(b, a)
    # ------------------------------------------------------------------

    def test_symmetry(self):
        """XOR distance must be symmetric."""
        a = generate_node_id("alpha")
        b = generate_node_id("beta")
        assert xor_distance(a, b) == xor_distance(b, a)

    def test_symmetry_distinct_ids(self):
        a = generate_node_id("10.0.0.1:4000")
        b = generate_node_id("10.0.0.2:4001")
        assert xor_distance(a, b) == xor_distance(b, a)

    # ------------------------------------------------------------------
    # Known-value correctness
    # ------------------------------------------------------------------

    def test_known_value_zero_and_one(self):
        """XOR of all-zeros and all-ones equals 2**256 - 1 (maximum distance)."""
        zero = b"\x00" * ID_BYTES
        ones = b"\xff" * ID_BYTES
        expected = (1 << ID_BITS) - 1  # 2**256 - 1
        assert xor_distance(zero, ones) == expected

    def test_known_value_single_bit_difference(self):
        """IDs differing in exactly one bit have a power-of-two XOR distance."""
        base = b"\x00" * ID_BYTES
        # Flip the least-significant bit of the last byte.
        flipped = b"\x00" * (ID_BYTES - 1) + b"\x01"
        assert xor_distance(base, flipped) == 1

    def test_known_value_msb_difference(self):
        """IDs differing only in the most-significant bit have distance 2**255."""
        base = b"\x00" * ID_BYTES
        msb = b"\x80" + b"\x00" * (ID_BYTES - 1)
        assert xor_distance(base, msb) == 2 ** (ID_BITS - 1)

    # ------------------------------------------------------------------
    # Ordering: closer ID has smaller distance
    # ------------------------------------------------------------------

    def test_ordering_closer_is_smaller(self):
        """A node with a single-bit difference is closer than one with many bits."""
        ref = b"\x00" * ID_BYTES
        close = b"\x00" * (ID_BYTES - 1) + b"\x01"   # differs by 1 bit
        far   = b"\xff" * ID_BYTES                     # differs in all bits
        assert xor_distance(ref, close) < xor_distance(ref, far)

    def test_ordering_three_nodes(self):
        """Distance ordering is consistent across three nodes."""
        a = generate_node_id("ref")
        b = generate_node_id("close-neighbour")
        c = generate_node_id("far-neighbour")
        d_ab = xor_distance(a, b)
        d_ac = xor_distance(a, c)
        d_bc = xor_distance(b, c)
        # Triangle inequality: d(a,c) <= d(a,b) + d(b,c)
        # XOR metric actually satisfies the stronger ultrametric inequality,
        # but we only assert the standard triangle inequality here.
        assert d_ac <= d_ab + d_bc

    # ------------------------------------------------------------------
    # Maximum distance fits within ID_BITS
    # ------------------------------------------------------------------

    def test_max_distance_within_id_bits(self):
        """No valid XOR distance can exceed 2**ID_BITS - 1."""
        a = generate_node_id("extremeA")
        b = generate_node_id("extremeB")
        assert xor_distance(a, b) < 2 ** ID_BITS

    # ------------------------------------------------------------------
    # Distinct IDs have non-zero distance
    # ------------------------------------------------------------------

    def test_distinct_ids_nonzero_distance(self):
        a = generate_node_id("node-x")
        b = generate_node_id("node-y")
        assert a != b, "pre-condition: IDs must differ"
        assert xor_distance(a, b) != 0

    # ------------------------------------------------------------------
    # Validation: wrong-length inputs raise ValueError
    # ------------------------------------------------------------------

    def test_invalid_a_too_short_raises(self):
        b = generate_node_id("good")
        with pytest.raises(ValueError, match="node ID 'a'"):
            xor_distance(b"\x00" * 10, b)

    def test_invalid_b_too_short_raises(self):
        a = generate_node_id("good")
        with pytest.raises(ValueError, match="node ID 'b'"):
            xor_distance(a, b"\x00" * 10)

    def test_invalid_a_empty_raises(self):
        b = generate_node_id("good")
        with pytest.raises(ValueError):
            xor_distance(b"", b)

    def test_invalid_b_empty_raises(self):
        a = generate_node_id("good")
        with pytest.raises(ValueError):
            xor_distance(a, b"")

    def test_invalid_a_too_long_raises(self):
        b = generate_node_id("good")
        with pytest.raises(ValueError, match="node ID 'a'"):
            xor_distance(b"\x00" * (ID_BYTES + 1), b)

    def test_invalid_b_too_long_raises(self):
        a = generate_node_id("good")
        with pytest.raises(ValueError, match="node ID 'b'"):
            xor_distance(a, b"\x00" * (ID_BYTES + 1))
