"""
node_id.py — SHA-256 based deterministic node ID generation.

A Kademlia node ID is a 256-bit (32-byte) value derived deterministically
from a seed string (e.g., "host:port") using SHA-256.  The ID is stored as
a plain Python bytes object so it can be compared, XOR'd, and serialised
without extra dependencies.
"""

import hashlib


# Kademlia uses 160-bit IDs in the original paper, but 256 bits (SHA-256)
# gives better collision resistance and is trivially produced by hashlib.
ID_BITS = 256
ID_BYTES = ID_BITS // 8


def generate_node_id(seed: str) -> bytes:
    """Return a deterministic 256-bit node ID derived from *seed*.

    The seed can be any string that uniquely identifies the node within the
    overlay network — typically ``"host:port"`` or a public key fingerprint.

    Parameters
    ----------
    seed:
        An arbitrary non-empty string used as SHA-256 input.

    Returns
    -------
    bytes
        A 32-byte (256-bit) node ID.

    Raises
    ------
    ValueError
        If *seed* is empty.

    Examples
    --------
    >>> nid = generate_node_id("127.0.0.1:5000")
    >>> len(nid)
    32
    >>> isinstance(nid, bytes)
    True
    """
    if not seed:
        raise ValueError("seed must be a non-empty string")

    return hashlib.sha256(seed.encode("utf-8")).digest()


def node_id_to_hex(node_id: bytes) -> str:
    """Return the hexadecimal string representation of a node ID.

    Parameters
    ----------
    node_id:
        A 32-byte node ID produced by :func:`generate_node_id`.

    Returns
    -------
    str
        A 64-character lowercase hex string.

    Raises
    ------
    ValueError
        If *node_id* is not exactly :data:`ID_BYTES` bytes long.

    Examples
    --------
    >>> nid = generate_node_id("127.0.0.1:5000")
    >>> len(node_id_to_hex(nid))
    64
    """
    if len(node_id) != ID_BYTES:
        raise ValueError(
            f"node_id must be {ID_BYTES} bytes, got {len(node_id)}"
        )
    return node_id.hex()


def node_id_from_hex(hex_str: str) -> bytes:
    """Parse a hex string back into a raw node ID.

    Parameters
    ----------
    hex_str:
        A 64-character hexadecimal string.

    Returns
    -------
    bytes
        A 32-byte node ID.

    Raises
    ------
    ValueError
        If *hex_str* does not decode to exactly :data:`ID_BYTES` bytes.

    Examples
    --------
    >>> nid = generate_node_id("127.0.0.1:5000")
    >>> node_id_from_hex(node_id_to_hex(nid)) == nid
    True
    """
    raw = bytes.fromhex(hex_str)
    if len(raw) != ID_BYTES:
        raise ValueError(
            f"hex_str must decode to {ID_BYTES} bytes, got {len(raw)}"
        )
    return raw
