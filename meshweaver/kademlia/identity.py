"""
identity.py — Cryptographic node identity for MeshWeaver DHT nodes.

Each node in the overlay network has a unique cryptographic identity
consisting of a private/public key pair.  The public key is derived
deterministically from the private key so it can be shared with peers.
The node ID used in the Kademlia routing table is derived from the
public key, making it cryptographically tied to the node's identity.

Key derivation scheme (stdlib-only, zero external dependencies):
    private_key  = 32 random bytes (secrets.token_bytes)
    public_key   = SHA-256(private_key)          — 32 bytes
    node_id      = SHA-256(public_key)            — 32 bytes (same format
                                                    as generate_node_id())

Signing / verification (HMAC-SHA256, see signer.py / verifier.py):
    signature    = HMAC-SHA256(public_key, canonical_payload)

Using the *public* key as the HMAC secret allows any peer that knows
the public key to independently verify a signature — no private key
exchange is required for verification.

Persistence:
    Keys are stored as a simple base64-encoded text file.  Only the
    32-byte private key is persisted; the public key and node ID are
    always re-derived on load so the file stays minimal.

Public API
----------
- ``NodeKeyPair``          — dataclass holding private + public key.
- ``generate_keypair()``   — create a fresh random key pair.
- ``node_id_from_keypair(kp)`` — derive the 32-byte Kademlia node ID.
- ``save_keypair(kp, path)``   — persist private key to a text file.
- ``load_keypair(path)``       — restore a key pair from a text file.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Union


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KEY_BYTES = 32  # 256-bit keys throughout

# Marker lines used in the key file so it's recognisable.
_FILE_HEADER = "-----BEGIN MESHWEAVER PRIVATE KEY-----"
_FILE_FOOTER = "-----END MESHWEAVER PRIVATE KEY-----"


# ---------------------------------------------------------------------------
# NodeKeyPair
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeKeyPair:
    """An immutable cryptographic identity for a single DHT node.

    Attributes
    ----------
    private_key:
        32 random bytes — kept secret, never shared.  Used to derive the
        public key; not used directly for signing (the public key is).
    public_key:
        32 bytes — ``SHA-256(private_key)``.  Shared with peers.  Used as
        the HMAC secret when signing and verifying task requests.

    Notes
    -----
    Construct instances via :func:`generate_keypair` or
    :func:`load_keypair` rather than directly, to ensure the
    ``private_key → public_key`` invariant is always maintained.
    """

    private_key: bytes
    public_key: bytes

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        if len(self.private_key) != _KEY_BYTES:
            raise ValueError(
                f"private_key must be {_KEY_BYTES} bytes, "
                f"got {len(self.private_key)}"
            )
        if len(self.public_key) != _KEY_BYTES:
            raise ValueError(
                f"public_key must be {_KEY_BYTES} bytes, "
                f"got {len(self.public_key)}"
            )
        # Enforce the derivation invariant.
        expected_pub = hashlib.sha256(self.private_key).digest()
        if self.public_key != expected_pub:
            raise ValueError(
                "public_key does not match SHA-256(private_key) — "
                "use generate_keypair() or load_keypair() to construct "
                "NodeKeyPair instances"
            )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def public_key_hex(self) -> str:
        """Return the public key as a 64-character hex string."""
        return self.public_key.hex()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"NodeKeyPair("
            f"public_key={self.public_key.hex()[:16]}…)"
        )


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def generate_keypair() -> NodeKeyPair:
    """Generate a fresh random cryptographic key pair.

    Returns
    -------
    NodeKeyPair
        A new :class:`NodeKeyPair` with a cryptographically random
        private key and its corresponding public key.

    Examples
    --------
    >>> kp = generate_keypair()
    >>> len(kp.private_key)
    32
    >>> len(kp.public_key)
    32
    >>> kp.public_key == __import__('hashlib').sha256(kp.private_key).digest()
    True
    """
    private_key = secrets.token_bytes(_KEY_BYTES)
    public_key = hashlib.sha256(private_key).digest()
    return NodeKeyPair(private_key=private_key, public_key=public_key)


# ---------------------------------------------------------------------------
# Node ID derivation
# ---------------------------------------------------------------------------


def node_id_from_keypair(keypair: NodeKeyPair) -> bytes:
    """Derive the 32-byte Kademlia node ID from a key pair.

    The node ID is ``SHA-256(public_key)`` — the same 32-byte format
    produced by :func:`~meshweaver.kademlia.node_id.generate_node_id`.
    Because the public key is itself derived from the private key,
    the node ID is uniquely and cryptographically tied to the node's
    identity.

    Parameters
    ----------
    keypair:
        A :class:`NodeKeyPair` instance.

    Returns
    -------
    bytes
        A 32-byte node ID compatible with the rest of the Kademlia stack.

    Examples
    --------
    >>> kp = generate_keypair()
    >>> nid = node_id_from_keypair(kp)
    >>> len(nid)
    32
    >>> isinstance(nid, bytes)
    True
    """
    if not isinstance(keypair, NodeKeyPair):
        raise TypeError(
            f"keypair must be a NodeKeyPair instance, got {type(keypair)!r}"
        )
    return hashlib.sha256(keypair.public_key).digest()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_keypair(keypair: NodeKeyPair, path: Union[str, os.PathLike]) -> None:
    """Persist *keypair* to a text file at *path*.

    Only the 32-byte private key is written.  The public key and node ID
    are always re-derived on load, so they are never stored separately.

    The file uses a simple PEM-inspired format::

        -----BEGIN MESHWEAVER PRIVATE KEY-----
        <base64-encoded private key>
        -----END MESHWEAVER PRIVATE KEY-----

    Parameters
    ----------
    keypair:
        The :class:`NodeKeyPair` to persist.
    path:
        Filesystem path where the key file should be written.  Parent
        directories must already exist.

    Raises
    ------
    TypeError
        If *keypair* is not a :class:`NodeKeyPair`.
    OSError
        If the file cannot be written (e.g. permission denied).

    Examples
    --------
    >>> import tempfile, os
    >>> kp = generate_keypair()
    >>> with tempfile.NamedTemporaryFile(delete=False, suffix='.key') as f:
    ...     tmp = f.name
    >>> save_keypair(kp, tmp)
    >>> os.path.exists(tmp)
    True
    >>> os.unlink(tmp)
    """
    if not isinstance(keypair, NodeKeyPair):
        raise TypeError(
            f"keypair must be a NodeKeyPair instance, got {type(keypair)!r}"
        )
    encoded = base64.b64encode(keypair.private_key).decode("ascii")
    content = f"{_FILE_HEADER}\n{encoded}\n{_FILE_FOOTER}\n"
    with open(path, "w", encoding="ascii") as fh:
        fh.write(content)


def load_keypair(path: Union[str, os.PathLike]) -> NodeKeyPair:
    """Load a :class:`NodeKeyPair` from the file at *path*.

    The public key is re-derived from the stored private key so that the
    :class:`NodeKeyPair` invariant (``public_key == SHA-256(private_key)``)
    is always satisfied.

    Parameters
    ----------
    path:
        Filesystem path to a key file previously written by
        :func:`save_keypair`.

    Returns
    -------
    NodeKeyPair
        The restored key pair.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the file is malformed (missing markers, wrong key length, or
        invalid base64).

    Examples
    --------
    >>> import tempfile, os
    >>> kp = generate_keypair()
    >>> with tempfile.NamedTemporaryFile(delete=False, suffix='.key') as f:
    ...     tmp = f.name
    >>> save_keypair(kp, tmp)
    >>> kp2 = load_keypair(tmp)
    >>> kp2 == kp
    True
    >>> os.unlink(tmp)
    """
    path = str(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Key file not found: {path!r}")

    with open(path, "r", encoding="ascii") as fh:
        raw = fh.read()

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    # Locate header and footer
    try:
        hi = lines.index(_FILE_HEADER)
        fi = lines.index(_FILE_FOOTER)
    except ValueError:
        raise ValueError(
            f"Key file {path!r} is malformed — missing PEM markers"
        )

    if fi <= hi:
        raise ValueError(
            f"Key file {path!r} is malformed — footer before header"
        )

    # Collect body lines between header and footer
    body_lines = lines[hi + 1 : fi]
    if not body_lines:
        raise ValueError(
            f"Key file {path!r} is malformed — no key data between markers"
        )

    try:
        private_key = base64.b64decode("".join(body_lines))
    except Exception as exc:
        raise ValueError(
            f"Key file {path!r} contains invalid base64 data: {exc}"
        ) from exc

    if len(private_key) != _KEY_BYTES:
        raise ValueError(
            f"Key file {path!r} has wrong key length: "
            f"expected {_KEY_BYTES} bytes, got {len(private_key)}"
        )

    public_key = hashlib.sha256(private_key).digest()
    return NodeKeyPair(private_key=private_key, public_key=public_key)
