"""
discovery.py — Additional peer discovery after the initial bootstrap join.

After a new node has joined the DHT via :mod:`meshweaver.kademlia.bootstrap`,
it typically knows only the contacts returned by the bootstrap peer.
:class:`PeerDiscovery` fans out ``FIND_NODE(self)`` queries to those initial
contacts, collects further contacts from their responses, and stores any new
ones in the local :class:`~meshweaver.kademlia.peer_store.PeerStore`.

This is one round of the Kademlia iterative node-lookup directed at the
joining node's own ID — the standard mechanism for populating the routing
table after bootstrap.

Routing-table updates
---------------------
Every time a seed contact responds successfully its entry in the routing
table is refreshed (moved to the most-recently-seen tail of its k-bucket).
Newly discovered contacts are added to the routing table through
:meth:`~meshweaver.kademlia.peer_store.PeerStore.add_or_update`.  Contacts
whose k-bucket is full are silently dropped (standard Kademlia eviction).

Reuses
------
- :class:`~meshweaver.kademlia.rpc.FindNodeHandler` — FIND_NODE request /
  FOUND_NODES parsing.
- :class:`~meshweaver.kademlia.peer_store.PeerStore` — contact storage and
  duplicate detection.

Public API
----------
- ``PeerDiscovery`` — fans out FIND_NODE queries and stores discovered peers.
"""

from __future__ import annotations

from typing import Callable, List

from meshweaver.kademlia.peer_store import PeerStore
from meshweaver.kademlia.routing_table import KademliaContact
from meshweaver.kademlia.rpc import FindNodeHandler


# ---------------------------------------------------------------------------
# PeerDiscovery
# ---------------------------------------------------------------------------


class PeerDiscovery:
    """Discovers additional peers by fanning out FIND_NODE queries.

    After the initial bootstrap join, the local node knows a handful of
    contacts.  :class:`PeerDiscovery` queries each of those contacts with
    ``FIND_NODE(self)``, collects additional contacts from their responses,
    and stores any previously-unknown contacts in the local
    :class:`~meshweaver.kademlia.peer_store.PeerStore`.

    Parameters
    ----------
    local_id_hex:
        64-character hex-encoded node ID of the **local** (joining) node.
    peer_store:
        The local peer store; used both to check for already-known contacts
        (deduplication) and to persist newly discovered ones.
    find_node_handler:
        A pre-configured :class:`~meshweaver.kademlia.rpc.FindNodeHandler`
        whose ``local_id_hex`` matches *local_id_hex*.

    Examples
    --------
    >>> from meshweaver.kademlia.node_id import generate_node_id, node_id_to_hex
    >>> from meshweaver.kademlia.peer_store import PeerStore
    >>> from meshweaver.kademlia.rpc import FindNodeHandler
    >>> local_id = generate_node_id("127.0.0.1:6000")
    >>> local_hex = node_id_to_hex(local_id)
    >>> store = PeerStore(local_id)
    >>> discovery = PeerDiscovery(
    ...     local_id_hex=local_hex,
    ...     peer_store=store,
    ...     find_node_handler=FindNodeHandler(local_hex),
    ... )
    """

    def __init__(
        self,
        local_id_hex: str,
        peer_store: PeerStore,
        find_node_handler: FindNodeHandler,
    ) -> None:
        if not local_id_hex:
            raise ValueError("local_id_hex must not be empty")
        self._local_id_hex = local_id_hex
        self._peer_store = peer_store
        self._find_node_handler = find_node_handler

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(
        self,
        contacts: List[KademliaContact],
        send_recv_for: Callable[[KademliaContact], Callable[[bytes], bytes]],
    ) -> List[KademliaContact]:
        """Fan out FIND_NODE queries to *contacts* and store new peers found.

        For each contact in *contacts*:

        1. Obtain its transport callable via ``send_recv_for(contact)``.
        2. Send ``FIND_NODE(self_id_hex)`` to that contact.
        3. **Refresh the seed contact** in the routing table — it responded,
           so we update its last-seen position in its k-bucket.
        4. Parse the ``FOUND_NODES`` reply into :class:`KademliaContact` objects.
        5. For each returned contact that is **not** already in the peer store,
           call :meth:`~meshweaver.kademlia.peer_store.PeerStore.add_or_update`.

        Contacts that fail to respond (transport raises) or return a malformed
        reply are silently skipped so that a single unreachable peer does not
        abort the whole discovery round.

        Parameters
        ----------
        contacts:
            Seed contacts to query — typically the list returned by
            :meth:`~meshweaver.kademlia.bootstrap.BootstrapClient.join`.
        send_recv_for:
            A factory callable ``(contact: KademliaContact) -> send_recv_fn``
            where the returned ``send_recv_fn`` is a
            ``(encoded_request: bytes) -> bytes`` transport for that specific
            peer.  Using a factory keeps this class socket-free and testable.

        Returns
        -------
        list[KademliaContact]
            All **newly** stored contacts (contacts already present in the peer
            store before this call are excluded; contacts whose k-bucket was
            full are also excluded).  The list may be empty if no new peers
            were found or all queries failed.
        """
        newly_stored: List[KademliaContact] = []
        # Track IDs added during *this* call to avoid double-counting when the
        # same contact appears in multiple FOUND_NODES responses.
        added_this_round: set = set()

        for seed_contact in contacts:
            try:
                send_recv = send_recv_for(seed_contact)
                request_bytes = self._find_node_handler.build_request(
                    self._local_id_hex
                )
                response_bytes = send_recv(request_bytes)
                discovered = self._find_node_handler.parse_response(
                    response_bytes, self._local_id_hex
                )
            except Exception:
                # Unreachable peer or malformed reply — skip gracefully.
                continue

            # -----------------------------------------------------------------
            # The seed contact responded — refresh it in the routing table so
            # it is moved to the most-recently-seen (tail) position in its
            # k-bucket.  This is a no-op if the seed is the local node itself.
            # -----------------------------------------------------------------
            if seed_contact.node_id.hex() != self._local_id_hex:
                try:
                    self._peer_store.add_or_update(
                        seed_contact.node_id,
                        seed_contact.host,
                        seed_contact.port,
                    )
                except ValueError:
                    pass  # Seed equals local node — ignore.

            for contact in discovered:
                # Skip the local node itself.
                if contact.node_id.hex() == self._local_id_hex:
                    continue
                # Skip contacts already in the store before this call and
                # contacts we already added in this round.
                if (
                    self._peer_store.contains(contact.node_id)
                    or contact.node_id in added_this_round
                ):
                    continue
                try:
                    accepted = self._peer_store.add_or_update(
                        contact.node_id, contact.host, contact.port
                    )
                    if accepted:
                        newly_stored.append(contact)
                        added_this_round.add(contact.node_id)
                except ValueError:
                    # Contact equals local node — skip.
                    pass

        return newly_stored

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PeerDiscovery("
            f"local={self._local_id_hex[:8]}…, "
            f"peers_known={self._peer_store.peer_count()})"
        )
