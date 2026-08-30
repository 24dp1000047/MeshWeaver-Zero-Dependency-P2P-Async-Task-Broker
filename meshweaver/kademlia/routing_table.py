"""
routing_table.py — Basic DHT routing-table structure.

The Kademlia routing table partitions the 256-bit ID space into *k-buckets*.
Each k-bucket covers a specific distance range and stores up to *k* known
peers (``KademliaContact`` instances).

This module provides:

- ``KademliaContact`` — a lightweight record of a known peer (node ID,
  host, port).
- ``RoutingTable`` — a 256-bucket structure that stores and retrieves
  contacts without performing any network I/O.

Design notes
------------
* **No networking** — this module is deliberately pure data.  PING
  validation and FIND_NODE lookups live in a separate layer (future work).
* **Extensible** — bucket size *k* is a constructor parameter (default 20,
  matching the original Kademlia paper).
* **Zero extra dependencies** — only the Python standard library is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from meshweaver.kademlia.node_id import ID_BITS, ID_BYTES


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DEFAULT_K = 20  # Maximum contacts per k-bucket (Kademlia paper default)


# ---------------------------------------------------------------------------
# KademliaContact
# ---------------------------------------------------------------------------


@dataclass
class KademliaContact:
    """A single peer entry stored inside a k-bucket.

    Attributes
    ----------
    node_id:
        Raw 32-byte SHA-256 node identifier.
    host:
        IPv4/IPv6 address or hostname of the peer.
    port:
        UDP/TCP port the peer is listening on.
    """

    node_id: bytes
    host: str
    port: int

    def __post_init__(self) -> None:
        if len(self.node_id) != ID_BYTES:
            raise ValueError(
                f"node_id must be {ID_BYTES} bytes, got {len(self.node_id)}"
            )
        if not (0 < self.port <= 65535):
            raise ValueError(f"port must be 1–65535, got {self.port}")

    # Contacts are compared by node ID only (host/port may change).
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KademliaContact):
            return NotImplemented
        return self.node_id == other.node_id

    def __hash__(self) -> int:
        return hash(self.node_id)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"KademliaContact("
            f"node_id={self.node_id.hex()[:8]}…, "
            f"host={self.host!r}, "
            f"port={self.port})"
        )


# ---------------------------------------------------------------------------
# KBucket
# ---------------------------------------------------------------------------


@dataclass
class KBucket:
    """A single k-bucket that stores up to *k* :class:`KademliaContact` s.

    Contacts are kept in the order they were last seen (tail = most recent).
    This follows the Kademlia paper's "least-recently seen" eviction policy
    structure, without actually performing liveness checks here.

    Parameters
    ----------
    k:
        Maximum number of contacts this bucket can hold.
    """

    k: int = DEFAULT_K
    contacts: List[KademliaContact] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_full(self) -> bool:
        """Return ``True`` when the bucket has reached capacity *k*."""
        return len(self.contacts) >= self.k

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_contact(self, contact: KademliaContact) -> bool:
        """Attempt to add *contact* to this bucket.

        * If *contact* is already present its entry is moved to the tail
          (marking it as the most-recently seen peer).
        * If the bucket is not full the contact is appended.
        * If the bucket is full the contact is **not** added and ``False``
          is returned — the caller should queue a liveness check on the
          oldest contact (head of list).

        Parameters
        ----------
        contact:
            The peer to add or refresh.

        Returns
        -------
        bool
            ``True`` if the contact is now present (added or refreshed),
            ``False`` if the bucket was full and the contact was dropped.
        """
        # Already present — move to tail (most recently seen).
        if contact in self.contacts:
            self.contacts.remove(contact)
            self.contacts.append(contact)
            return True

        if not self.is_full:
            self.contacts.append(contact)
            return True

        # Bucket is full; contact is dropped (liveness checks out-of-scope).
        return False

    def remove_contact(self, node_id: bytes) -> bool:
        """Remove the contact with *node_id* from this bucket.

        Parameters
        ----------
        node_id:
            The 32-byte ID of the peer to remove.

        Returns
        -------
        bool
            ``True`` if a contact was removed, ``False`` if not found.
        """
        for contact in self.contacts:
            if contact.node_id == node_id:
                self.contacts.remove(contact)
                return True
        return False

    def get_contact(self, node_id: bytes) -> Optional[KademliaContact]:
        """Return the contact matching *node_id*, or ``None``."""
        for contact in self.contacts:
            if contact.node_id == node_id:
                return contact
        return None

    def __len__(self) -> int:
        return len(self.contacts)

    def __repr__(self) -> str:  # pragma: no cover
        return f"KBucket(k={self.k}, contacts={len(self.contacts)})"


# ---------------------------------------------------------------------------
# RoutingTable
# ---------------------------------------------------------------------------


class RoutingTable:
    """Kademlia routing table for a single local node.

    The routing table maintains one :class:`KBucket` per bit of the ID
    space (``ID_BITS`` buckets in total).  Bucket index *i* covers peers
    whose XOR distance to the local node falls in the range
    ``[2^i, 2^(i+1))``.  Bucket 0 (distance 0) is never used in practice
    because a node does not store itself.

    Parameters
    ----------
    local_node_id:
        The 32-byte SHA-256 ID of the **local** node that owns this table.
    k:
        Maximum contacts per k-bucket (default :data:`DEFAULT_K`).

    Examples
    --------
    >>> from meshweaver.kademlia.node_id import generate_node_id
    >>> from meshweaver.kademlia.routing_table import RoutingTable, KademliaContact
    >>> local_id = generate_node_id("127.0.0.1:5000")
    >>> rt = RoutingTable(local_id)
    >>> peer_id = generate_node_id("127.0.0.1:5001")
    >>> contact = KademliaContact(peer_id, "127.0.0.1", 5001)
    >>> rt.add_contact(contact)
    True
    >>> rt.get_contact(peer_id) == contact
    True
    """

    def __init__(self, local_node_id: bytes, k: int = DEFAULT_K) -> None:
        if len(local_node_id) != ID_BYTES:
            raise ValueError(
                f"local_node_id must be {ID_BYTES} bytes, got "
                f"{len(local_node_id)}"
            )
        self.local_node_id: bytes = local_node_id
        self.k: int = k
        # One bucket per bit position (index 0 = closest possible bucket).
        self._buckets: List[KBucket] = [
            KBucket(k=k) for _ in range(ID_BITS)
        ]

    # ------------------------------------------------------------------
    # Bucket index resolution
    # ------------------------------------------------------------------

    def _bucket_index(self, node_id: bytes) -> int:
        """Return the k-bucket index for *node_id* relative to the local node.

        The index equals the position of the highest set bit in the XOR
        distance between the local ID and *node_id* (i.e.,
        ``floor(log2(xor_distance))``).

        Parameters
        ----------
        node_id:
            A 32-byte peer node ID.

        Returns
        -------
        int
            Bucket index in ``[0, ID_BITS - 1]``.

        Raises
        ------
        ValueError
            If *node_id* equals the local node ID (distance 0 has no
            defined bucket).
        """
        xor_int = int.from_bytes(self.local_node_id, "big") ^ int.from_bytes(
            node_id, "big"
        )
        if xor_int == 0:
            raise ValueError(
                "Cannot determine bucket for the local node itself "
                "(XOR distance is 0)"
            )
        # bit_length() gives the number of bits needed to represent xor_int,
        # so the highest set bit position is bit_length() - 1.
        return xor_int.bit_length() - 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_contact(self, contact: KademliaContact) -> bool:
        """Add or refresh *contact* in the appropriate k-bucket.

        Parameters
        ----------
        contact:
            The peer to store.

        Returns
        -------
        bool
            ``True`` if stored or refreshed, ``False`` if the bucket was
            full and the contact could not be added.

        Raises
        ------
        ValueError
            If *contact* has the same node ID as the local node.
        """
        if contact.node_id == self.local_node_id:
            raise ValueError("Cannot add the local node to its own routing table")
        idx = self._bucket_index(contact.node_id)
        return self._buckets[idx].add_contact(contact)

    def remove_contact(self, node_id: bytes) -> bool:
        """Remove the contact with *node_id* from its k-bucket.

        Parameters
        ----------
        node_id:
            The 32-byte ID of the peer to remove.

        Returns
        -------
        bool
            ``True`` if removed, ``False`` if not found.
        """
        if node_id == self.local_node_id:
            return False
        try:
            idx = self._bucket_index(node_id)
        except ValueError:
            return False
        return self._buckets[idx].remove_contact(node_id)

    def get_contact(self, node_id: bytes) -> Optional[KademliaContact]:
        """Return the stored contact for *node_id*, or ``None``.

        Parameters
        ----------
        node_id:
            The 32-byte ID to look up.
        """
        if node_id == self.local_node_id:
            return None
        try:
            idx = self._bucket_index(node_id)
        except ValueError:
            return None
        return self._buckets[idx].get_contact(node_id)

    def get_all_contacts(self) -> List[KademliaContact]:
        """Return a flat list of every contact currently in the table."""
        result: List[KademliaContact] = []
        for bucket in self._buckets:
            result.extend(bucket.contacts)
        return result

    def bucket_for(self, node_id: bytes) -> KBucket:
        """Return the :class:`KBucket` responsible for *node_id*.

        Useful for inspecting bucket state in tests and diagnostics.
        """
        idx = self._bucket_index(node_id)
        return self._buckets[idx]

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the total number of contacts across all buckets."""
        return sum(len(b) for b in self._buckets)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RoutingTable("
            f"local={self.local_node_id.hex()[:8]}…, "
            f"k={self.k}, "
            f"contacts={len(self)})"
        )
