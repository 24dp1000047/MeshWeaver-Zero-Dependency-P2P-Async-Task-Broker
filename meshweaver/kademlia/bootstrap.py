"""
bootstrap.py — Kademlia bootstrap / join flow for a new node.

When a fresh node wants to join an existing DHT overlay it must contact at
least one *bootstrap peer* — a node whose address is known in advance.  The
join sequence follows the Kademlia paper:

    1. **PING** the bootstrap peer to confirm it is reachable.
    2. **FIND_NODE(self)** — ask the bootstrap peer for the *k* contacts it
       knows that are closest to the new node's own ID.
    3. **Store** every returned contact in the local :class:`PeerStore`.

All network I/O is injected through a ``send_recv`` callable so the module
remains socket-free and fully testable without real network connections.

Reuses
------
- :class:`~meshweaver.kademlia.rpc.PingValidator` — PING / PONG exchange.
- :class:`~meshweaver.kademlia.rpc.FindNodeHandler` — FIND_NODE request /
  FOUND_NODES parsing.
- :class:`~meshweaver.kademlia.peer_store.PeerStore` — contact storage.

Public API
----------
- ``BootstrapError``   — raised when the bootstrap peer cannot be reached or
                         the join sequence fails.
- ``BootstrapClient``  — orchestrates the join flow.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from meshweaver.kademlia.peer_store import PeerStore
from meshweaver.kademlia.routing_table import KademliaContact
from meshweaver.kademlia.rpc import FindNodeHandler, PingValidator


# ---------------------------------------------------------------------------
# BootstrapError
# ---------------------------------------------------------------------------


class BootstrapError(Exception):
    """Raised when the bootstrap / join sequence cannot be completed.

    Typical causes
    --------------
    * The bootstrap peer did not respond to the initial PING.
    * The FIND_NODE reply was malformed or carried no contacts.
    * The transport callable raised an unrecoverable exception.
    """


# ---------------------------------------------------------------------------
# BootstrapClient
# ---------------------------------------------------------------------------


class BootstrapClient:
    """Orchestrates the Kademlia bootstrap / join flow for a new node.

    Parameters
    ----------
    local_id_hex:
        64-character hex-encoded node ID of the **joining** (new) node.
    peer_store:
        The local :class:`~meshweaver.kademlia.peer_store.PeerStore` that
        will be populated with contacts learned from the bootstrap peer.
    ping_validator:
        A pre-configured :class:`~meshweaver.kademlia.rpc.PingValidator`
        instance (its ``local_id_hex`` must match *local_id_hex*).
    find_node_handler:
        A pre-configured :class:`~meshweaver.kademlia.rpc.FindNodeHandler`
        instance (its ``local_id_hex`` must match *local_id_hex*).

    Examples
    --------
    >>> from meshweaver.kademlia.node_id import generate_node_id, node_id_to_hex
    >>> from meshweaver.kademlia.peer_store import PeerStore
    >>> from meshweaver.kademlia.rpc import PingValidator, FindNodeHandler
    >>> local_id = generate_node_id("127.0.0.1:6000")
    >>> local_hex = node_id_to_hex(local_id)
    >>> store = PeerStore(local_id)
    >>> client = BootstrapClient(
    ...     local_id_hex=local_hex,
    ...     peer_store=store,
    ...     ping_validator=PingValidator(local_hex),
    ...     find_node_handler=FindNodeHandler(local_hex),
    ... )
    """

    def __init__(
        self,
        local_id_hex: str,
        peer_store: PeerStore,
        ping_validator: PingValidator,
        find_node_handler: FindNodeHandler,
    ) -> None:
        if not local_id_hex:
            raise ValueError("local_id_hex must not be empty")
        self._local_id_hex = local_id_hex
        self._peer_store = peer_store
        self._ping_validator = ping_validator
        self._find_node_handler = find_node_handler

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def join(
        self,
        bootstrap_host: str,
        bootstrap_port: int,
        send_recv: Callable[[bytes], bytes],
    ) -> List[KademliaContact]:
        """Execute the Kademlia join sequence against a bootstrap peer.

        Steps
        -----
        1. PING the bootstrap peer via *send_recv*; raise
           :exc:`BootstrapError` if the peer does not reply with a valid
           PONG.
        2. Send ``FIND_NODE(self)`` — ask the bootstrap peer for contacts
           closest to the joining node's own ID.
        3. For every contact returned, call
           :meth:`~meshweaver.kademlia.peer_store.PeerStore.add_or_update`
           so they are stored in the local routing table / peer store.
        4. Return the list of contacts that were successfully stored.

        Parameters
        ----------
        bootstrap_host:
            Hostname or IP address of the bootstrap peer (informational;
            not used for I/O here — *send_recv* handles delivery).
        bootstrap_port:
            Port of the bootstrap peer (informational; same rationale).
        send_recv:
            A callable ``(encoded_request: bytes) -> bytes`` that delivers
            a request to the bootstrap peer and returns the raw reply.
            For real networking this wraps a socket send/receive; in tests
            it can be an in-process function.

        Returns
        -------
        list[KademliaContact]
            The contacts received from the bootstrap peer that were
            successfully stored in the local peer store (contacts whose
            k-bucket was already full are excluded).

        Raises
        ------
        BootstrapError
            If the bootstrap peer fails to respond to the PING, or if the
            FIND_NODE exchange fails.
        """
        # -----------------------------------------------------------------
        # Step 1: PING the bootstrap peer
        # -----------------------------------------------------------------
        peer_alive = self._ping_validator.ping(send_recv)
        if not peer_alive:
            raise BootstrapError(
                f"Bootstrap peer {bootstrap_host}:{bootstrap_port} did not "
                "respond to PING — cannot join the DHT."
            )

        # -----------------------------------------------------------------
        # Step 2: FIND_NODE targeting our own ID
        # -----------------------------------------------------------------
        try:
            request_bytes = self._find_node_handler.build_request(
                self._local_id_hex
            )
            response_bytes = send_recv(request_bytes)
            contacts = self._find_node_handler.parse_response(
                response_bytes, self._local_id_hex
            )
        except Exception as exc:
            raise BootstrapError(
                "FIND_NODE exchange with bootstrap peer "
                f"{bootstrap_host}:{bootstrap_port} failed: {exc}"
            ) from exc

        # -----------------------------------------------------------------
        # Step 3: Store returned contacts in the local peer store
        # -----------------------------------------------------------------
        stored: List[KademliaContact] = []
        for contact in contacts:
            try:
                accepted = self._peer_store.add_or_update(
                    contact.node_id, contact.host, contact.port
                )
                if accepted:
                    stored.append(contact)
            except ValueError:
                # Silently skip contacts that equal the local node ID.
                pass

        return stored

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"BootstrapClient("
            f"local={self._local_id_hex[:8]}…, "
            f"peers_known={self._peer_store.peer_count()})"
        )
