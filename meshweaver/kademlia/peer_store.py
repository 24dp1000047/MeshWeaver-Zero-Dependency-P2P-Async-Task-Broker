"""
peer_store.py — Known-peer management for the Kademlia DHT layer.

``PeerStore`` is a thin management layer that sits on top of
:class:`~meshweaver.kademlia.routing_table.RoutingTable`.  It enriches
each known peer with lightweight metadata (first-seen / last-seen
timestamps) and exposes a clean API for the rest of the application to
add, retrieve, update, and remove known peers without touching bucket
internals directly.

Design notes
------------
* **No networking** — purely data management; no PING, FIND_NODE, or I/O.
* **No extra dependencies** — standard library only (``time``, ``dataclasses``).
* **Reuses existing structures** — delegates storage and bucket placement to
  :class:`RoutingTable`; ``PeerRecord`` wraps ``KademliaContact`` with meta.
* **Thread-agnostic** — callers are responsible for locking if needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from meshweaver.kademlia.node_id import ID_BYTES
from meshweaver.kademlia.routing_table import KademliaContact, RoutingTable


# ---------------------------------------------------------------------------
# PeerRecord
# ---------------------------------------------------------------------------


@dataclass
class PeerRecord:
    """A known peer enriched with management metadata.

    Attributes
    ----------
    contact:
        The underlying :class:`KademliaContact` (node ID, host, port).
    first_seen:
        Unix timestamp (float) of when the peer was first added.
    last_seen:
        Unix timestamp (float) of when the peer was most recently seen /
        refreshed.  Updated each time :meth:`PeerStore.add_or_update` is
        called for the same node ID.
    """

    contact: KademliaContact
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def node_id(self) -> bytes:
        """Raw 32-byte node ID — delegates to the wrapped contact."""
        return self.contact.node_id

    @property
    def host(self) -> str:
        """Host string of the peer."""
        return self.contact.host

    @property
    def port(self) -> int:
        """Port number of the peer."""
        return self.contact.port

    def touch(self) -> None:
        """Update :attr:`last_seen` to the current time."""
        self.last_seen = time.time()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PeerRecord("
            f"node_id={self.node_id.hex()[:8]}…, "
            f"host={self.host!r}, "
            f"port={self.port}, "
            f"last_seen={self.last_seen:.3f})"
        )


# ---------------------------------------------------------------------------
# PeerStore
# ---------------------------------------------------------------------------


class PeerStore:
    """Manages the set of known peers for a single local Kademlia node.

    ``PeerStore`` wraps a :class:`RoutingTable` and a flat
    ``Dict[bytes, PeerRecord]`` index.  The routing table handles XOR-based
    bucket placement; the record dict provides O(1) metadata access by
    node ID.

    Parameters
    ----------
    local_node_id:
        The 32-byte SHA-256 ID of the **local** node.
    k:
        Maximum contacts per k-bucket (forwarded to :class:`RoutingTable`).

    Examples
    --------
    >>> from meshweaver.kademlia.node_id import generate_node_id
    >>> local_id = generate_node_id("127.0.0.1:5000")
    >>> store = PeerStore(local_id)
    >>> peer_id = generate_node_id("127.0.0.1:5001")
    >>> store.add_or_update(peer_id, "127.0.0.1", 5001)
    True
    >>> rec = store.get(peer_id)
    >>> rec is not None
    True
    >>> rec.host
    '127.0.0.1'
    """

    def __init__(self, local_node_id: bytes, k: int = 20) -> None:
        if len(local_node_id) != ID_BYTES:
            raise ValueError(
                f"local_node_id must be {ID_BYTES} bytes, got {len(local_node_id)}"
            )
        self._local_node_id: bytes = local_node_id
        self._routing_table: RoutingTable = RoutingTable(local_node_id, k=k)
        # Flat index: node_id -> PeerRecord (for O(1) metadata access)
        self._records: Dict[bytes, PeerRecord] = {}

    # ------------------------------------------------------------------
    # Core management API
    # ------------------------------------------------------------------

    def add_or_update(self, node_id: bytes, host: str, port: int) -> bool:
        """Add a new peer or refresh an existing one.

        * If the peer is **new**, a :class:`PeerRecord` is created and the
          contact is inserted into the routing table.
        * If the peer is **already known**, its ``host``, ``port``, and
          ``last_seen`` timestamp are updated in place; the contact is also
          refreshed inside its k-bucket (moved to the tail).

        Parameters
        ----------
        node_id:
            Raw 32-byte peer identifier.
        host:
            IPv4/IPv6 address or hostname.
        port:
            Listening port (1–65535).

        Returns
        -------
        bool
            ``True`` if the peer is now stored (added or refreshed).
            ``False`` if the target k-bucket was full and the peer could not
            be inserted (only possible for **new** peers; existing peers are
            always refreshed regardless of bucket state).

        Raises
        ------
        ValueError
            If *node_id* equals the local node ID, or if validation inside
            :class:`KademliaContact` fails.
        """
        if node_id == self._local_node_id:
            raise ValueError("Cannot add the local node to the peer store")

        contact = KademliaContact(node_id, host, port)

        if node_id in self._records:
            # Update metadata in the existing record.
            record = self._records[node_id]
            record.contact = contact
            record.touch()
            # Refresh position inside the k-bucket (moves to tail).
            self._routing_table.add_contact(contact)
            return True

        # New peer — attempt to insert into the routing table.
        accepted = self._routing_table.add_contact(contact)
        if accepted:
            self._records[node_id] = PeerRecord(contact=contact)
        return accepted

    def get(self, node_id: bytes) -> Optional[PeerRecord]:
        """Return the :class:`PeerRecord` for *node_id*, or ``None``.

        Parameters
        ----------
        node_id:
            The 32-byte ID of the peer to look up.
        """
        return self._records.get(node_id)

    def remove(self, node_id: bytes) -> bool:
        """Remove the peer identified by *node_id*.

        Removes the peer from both the flat record index and its k-bucket
        in the underlying routing table.

        Parameters
        ----------
        node_id:
            The 32-byte ID of the peer to remove.

        Returns
        -------
        bool
            ``True`` if the peer was found and removed, ``False`` otherwise.
        """
        if node_id not in self._records:
            return False
        self._records.pop(node_id)
        self._routing_table.remove_contact(node_id)
        return True

    def contains(self, node_id: bytes) -> bool:
        """Return ``True`` if *node_id* is a currently known peer.

        Parameters
        ----------
        node_id:
            The 32-byte ID to check.
        """
        return node_id in self._records

    # ------------------------------------------------------------------
    # Bulk / query helpers
    # ------------------------------------------------------------------

    def all_peers(self) -> List[PeerRecord]:
        """Return all known peer records as an unordered list."""
        return list(self._records.values())

    def peer_count(self) -> int:
        """Return the total number of currently known peers."""
        return len(self._records)

    def clear(self) -> None:
        """Remove all known peers, resetting the store to an empty state."""
        self._records.clear()
        # Re-create the routing table so bucket state is also wiped.
        self._routing_table = RoutingTable(self._local_node_id, k=self._routing_table.k)

    # ------------------------------------------------------------------
    # Read-only access to the underlying routing table
    # ------------------------------------------------------------------

    @property
    def routing_table(self) -> RoutingTable:
        """Expose the underlying :class:`RoutingTable` for inspection."""
        return self._routing_table

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the total number of known peers."""
        return len(self._records)

    def __contains__(self, node_id: bytes) -> bool:
        """Support ``node_id in store`` membership tests."""
        return node_id in self._records

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PeerStore("
            f"local={self._local_node_id.hex()[:8]}…, "
            f"peers={len(self)})"
        )
