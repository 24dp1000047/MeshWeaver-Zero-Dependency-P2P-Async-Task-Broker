"""
lookup.py - Peer lookup using the Kademlia routing table.

Given a *target* node ID, :class:`PeerLookup` returns the *k* closest known
peers by XOR distance from the local routing table.  This is the local-table
query step that underpins Kademlia's iterative FIND_NODE algorithm.

Design notes
------------
* **Pure data** - no network I/O; operates entirely on the in-process
  :class:`~meshweaver.kademlia.routing_table.RoutingTable`.
* **No extra dependencies** - standard library only.
* **Reuses existing building blocks** -
    :mod:`meshweaver.kademlia.node_id` for XOR distance,
    :mod:`meshweaver.kademlia.routing_table` for ``RoutingTable`` /
    ``KademliaContact``.

Public API
----------
- ``PeerLookup``               - main lookup class.
- ``PeerLookup.find_closest``  - return up to *k* contacts closest to target.
"""

from __future__ import annotations

from typing import List

from meshweaver.kademlia.node_id import ID_BYTES, node_id_from_hex, xor_distance
from meshweaver.kademlia.routing_table import DEFAULT_K, KademliaContact, RoutingTable


class PeerLookup:
    """Lookup peers closest to a target node ID using the local routing table.

    Parameters
    ----------
    routing_table:
        The :class:`RoutingTable` owned by the local node.  All contacts
        currently stored in the table are eligible candidates.
    k:
        Maximum number of contacts to return per lookup (default
        :data:`~meshweaver.kademlia.routing_table.DEFAULT_K`).

    Examples
    --------
    >>> from meshweaver.kademlia.node_id import generate_node_id
    >>> from meshweaver.kademlia.routing_table import RoutingTable, KademliaContact
    >>> local_id = generate_node_id("127.0.0.1:5000")
    >>> rt = RoutingTable(local_id)
    >>> peer_id = generate_node_id("127.0.0.1:5001")
    >>> rt.add_contact(KademliaContact(peer_id, "127.0.0.1", 5001))
    True
    >>> lookup = PeerLookup(rt)
    >>> results = lookup.find_closest(peer_id)
    >>> len(results) == 1
    True
    >>> results[0].node_id == peer_id
    True
    """

    def __init__(self, routing_table: RoutingTable, k: int = DEFAULT_K) -> None:
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}")
        self._routing_table = routing_table
        self._k = k

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_closest(self, target_id: bytes) -> List[KademliaContact]:
        """Return up to *k* contacts closest to *target_id* by XOR distance.

        All contacts in the routing table are ranked by their XOR distance
        to *target_id* and the *k* nearest are returned in ascending order
        (closest first).

        The local node itself is never stored in the routing table, so it
        will never appear in the results.

        Parameters
        ----------
        target_id:
            A 32-byte node ID to search for.

        Returns
        -------
        list[KademliaContact]
            Between 0 and *k* contacts, sorted by XOR distance to
            *target_id* (closest first).

        Raises
        ------
        ValueError
            If *target_id* is not exactly :data:`~meshweaver.kademlia.node_id.ID_BYTES`
            bytes long.
        """
        if len(target_id) != ID_BYTES:
            raise ValueError(
                f"target_id must be {ID_BYTES} bytes, got {len(target_id)}"
            )

        all_contacts = self._routing_table.get_all_contacts()
        all_contacts.sort(key=lambda c: xor_distance(c.node_id, target_id))
        return all_contacts[: self._k]

    def find_closest_hex(self, target_id_hex: str) -> List[KademliaContact]:
        """Return up to *k* contacts closest to *target_id_hex* by XOR distance.

        Convenience wrapper around :meth:`find_closest` that accepts a
        hex-encoded target ID instead of raw bytes.

        Parameters
        ----------
        target_id_hex:
            64-character hex-encoded node ID to search for.

        Returns
        -------
        list[KademliaContact]
            Between 0 and *k* contacts, sorted by XOR distance to the target
            (closest first).

        Raises
        ------
        ValueError
            If *target_id_hex* does not decode to exactly
            :data:`~meshweaver.kademlia.node_id.ID_BYTES` bytes.
        """
        target_id = node_id_from_hex(target_id_hex)
        return self.find_closest(target_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def k(self) -> int:
        """The maximum number of contacts returned per lookup."""
        return self._k

    @property
    def routing_table(self) -> RoutingTable:
        """The underlying :class:`RoutingTable` used for lookups."""
        return self._routing_table

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PeerLookup("
            f"local={self._routing_table.local_node_id.hex()[:8]}..., "
            f"k={self._k})"
        )
