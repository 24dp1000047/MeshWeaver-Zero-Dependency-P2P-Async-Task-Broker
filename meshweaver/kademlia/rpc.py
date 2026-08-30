"""
rpc.py — PING-based peer validation and initial FIND_NODE handling.

This module implements the two core DHT RPC operations introduced in Commit 5:

1. **PingValidator** — validates whether a peer is alive by issuing a PING
   and verifying the PONG reply.  All I/O is injected through a callable
   so the logic is fully testable without real sockets.

2. **FindNodeHandler** — builds FIND_NODE request messages and parses
   FOUND_NODES responses, turning them back into ``KademliaContact`` objects
   ready for the routing table.

Design notes
------------
* **No real sockets** — network transport is injected (dependency-injection
  pattern), keeping this module pure logic and 100 % testable.
* **No extra dependencies** — standard library only.
* **Reuses existing building blocks**:
    - :mod:`meshweaver.protocol` for message encoding/decoding/validation.
    - :mod:`meshweaver.kademlia.node_id` for ID serialisation.
    - :mod:`meshweaver.kademlia.routing_table` for ``KademliaContact``.
    - :mod:`meshweaver.kademlia.peer_store` for the ``PeerStore``.

Public API
----------
- ``PingValidator``      — PING / PONG peer liveness check.
- ``FindNodeHandler``    — FIND_NODE request builder + FOUND_NODES parser.
- ``contacts_to_dicts``  — convert ``KademliaContact`` list to wire format.
- ``dicts_to_contacts``  — parse wire-format contact list back to objects.
"""

from __future__ import annotations

import uuid
from typing import Callable, List, Optional

from meshweaver.kademlia.node_id import (
    ID_BYTES,
    node_id_from_hex,
    node_id_to_hex,
    xor_distance,
)
from meshweaver.kademlia.routing_table import KademliaContact
from meshweaver.protocol import (
    MSG_FOUND_NODES,
    MSG_PING,
    MSG_PONG,
    MSG_FIND_NODE,
    build_find_node,
    build_found_nodes,
    build_ping,
    build_pong,
    decode_message,
    encode_message,
    validate_message,
)


# ---------------------------------------------------------------------------
# Wire-format helpers
# ---------------------------------------------------------------------------


def contacts_to_dicts(contacts: List[KademliaContact]) -> list:
    """Convert a list of ``KademliaContact`` objects to JSON-serialisable dicts.

    Each dict has the keys ``"node_id"`` (hex str), ``"host"`` (str), and
    ``"port"`` (int).

    Parameters
    ----------
    contacts:
        Zero or more ``KademliaContact`` instances.

    Returns
    -------
    list
        List of ``{"node_id": ..., "host": ..., "port": ...}`` dicts.
    """
    return [
        {
            "node_id": node_id_to_hex(c.node_id),
            "host": c.host,
            "port": c.port,
        }
        for c in contacts
    ]


def dicts_to_contacts(raw: list) -> List[KademliaContact]:
    """Parse a list of contact dicts (from the wire) into ``KademliaContact`` objects.

    Parameters
    ----------
    raw:
        List of dicts, each expected to have ``"node_id"`` (hex str),
        ``"host"`` (str), and ``"port"`` (int).

    Returns
    -------
    list
        List of ``KademliaContact`` instances.

    Raises
    ------
    KeyError
        If a required field is missing from a contact dict.
    ValueError
        If ``node_id`` hex does not decode to exactly ``ID_BYTES`` bytes, or
        if ``port`` is out of range.
    """
    result = []
    for entry in raw:
        node_id = node_id_from_hex(entry["node_id"])
        contact = KademliaContact(
            node_id=node_id,
            host=entry["host"],
            port=int(entry["port"]),
        )
        result.append(contact)
    return result


# ---------------------------------------------------------------------------
# PingValidator
# ---------------------------------------------------------------------------


class PingValidator:
    """Validates peer liveness using the PING / PONG exchange.

    Usage pattern::

        def my_send_recv(encoded_request: bytes) -> bytes:
            # … send over UDP/TCP and return the raw reply …

        validator = PingValidator(local_id_hex="abc…")
        ok = validator.ping(send_recv=my_send_recv)

    For unit tests, ``send_recv`` can be a simple in-process function that
    immediately returns a PONG.

    Parameters
    ----------
    local_id_hex:
        64-character hex-encoded node ID of the local node.
    """

    def __init__(self, local_id_hex: str) -> None:
        if not local_id_hex:
            raise ValueError("local_id_hex must not be empty")
        self._local_id_hex = local_id_hex

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def build_ping_request(self, token: Optional[str] = None) -> bytes:
        """Return an encoded PING request.

        Parameters
        ----------
        token:
            Optional correlation token.  If ``None``, a fresh UUID is
            generated automatically.

        Returns
        -------
        bytes
            UTF-8 JSON encoded PING message.
        """
        tok = token if token is not None else str(uuid.uuid4())
        msg = build_ping(self._local_id_hex, tok)
        return encode_message(msg)

    def handle_ping(self, encoded_request: bytes) -> bytes:
        """Process an incoming PING and return the encoded PONG reply.

        This method is called on the *receiving* side of the PING exchange.

        Parameters
        ----------
        encoded_request:
            Raw bytes of an incoming PING message.

        Returns
        -------
        bytes
            Encoded PONG reply with the same token as the incoming PING.

        Raises
        ------
        ValueError
            If *encoded_request* is not a valid PING message.
        """
        msg = decode_message(encoded_request)
        validate_message(msg, MSG_PING)
        token = msg.get("token")
        if not token:
            raise ValueError("PING message missing 'token' field")
        pong = build_pong(self._local_id_hex, token)
        return encode_message(pong)

    def validate_pong(self, encoded_pong: bytes, expected_token: str) -> bool:
        """Verify that *encoded_pong* is a valid PONG matching *expected_token*.

        Parameters
        ----------
        encoded_pong:
            Raw bytes of the PONG reply to check.
        expected_token:
            The token that was sent in the original PING.

        Returns
        -------
        bool
            ``True`` if the PONG is structurally valid and carries the
            expected token; ``False`` otherwise.
        """
        try:
            msg = decode_message(encoded_pong)
            validate_message(msg, MSG_PONG)
            return msg.get("token") == expected_token
        except (ValueError, KeyError, UnicodeDecodeError):
            return False

    def ping(
        self,
        send_recv: Callable[[bytes], bytes],
        token: Optional[str] = None,
    ) -> bool:
        """Perform a full PING / PONG round-trip using *send_recv*.

        Parameters
        ----------
        send_recv:
            A callable ``(encoded_request: bytes) -> bytes`` that delivers
            the PING to the remote peer and returns the raw reply.
        token:
            Optional fixed token (useful in tests).  Defaults to a new UUID.

        Returns
        -------
        bool
            ``True`` if the peer replied with a valid, token-matching PONG;
            ``False`` on any error (bad reply, wrong token, etc.).
        """
        tok = token if token is not None else str(uuid.uuid4())
        try:
            request = self.build_ping_request(tok)
            reply = send_recv(request)
            return self.validate_pong(reply, tok)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# FindNodeHandler
# ---------------------------------------------------------------------------


class FindNodeHandler:
    """Builds FIND_NODE requests and parses FOUND_NODES responses.

    Usage pattern (requester side)::

        handler = FindNodeHandler(local_id_hex=..., k=20)
        request_bytes = handler.build_request(target_id_hex=...)
        # … send request_bytes to remote node, receive reply_bytes …
        contacts = handler.parse_response(reply_bytes, target_id_hex=...)

    Usage pattern (responder side)::

        handler = FindNodeHandler(local_id_hex=..., k=20)
        target_hex, response_bytes = handler.handle_request(
            encoded_request, peer_store
        )

    Parameters
    ----------
    local_id_hex:
        64-character hex-encoded node ID of the local node.
    k:
        Maximum number of contacts to include in a FOUND_NODES response
        (default 20, matching the Kademlia paper).
    """

    def __init__(self, local_id_hex: str, k: int = 20) -> None:
        if not local_id_hex:
            raise ValueError("local_id_hex must not be empty")
        if k < 1:
            raise ValueError("k must be at least 1")
        self._local_id_hex = local_id_hex
        self._k = k

    # ------------------------------------------------------------------
    # Requester side
    # ------------------------------------------------------------------

    def build_request(self, target_id_hex: str) -> bytes:
        """Return an encoded FIND_NODE request targeting *target_id_hex*.

        Parameters
        ----------
        target_id_hex:
            Hex-encoded node ID being looked up.

        Returns
        -------
        bytes
            UTF-8 JSON encoded FIND_NODE message.
        """
        msg = build_find_node(self._local_id_hex, target_id_hex)
        return encode_message(msg)

    def parse_response(
        self, encoded_response: bytes, target_id_hex: str
    ) -> List[KademliaContact]:
        """Parse a FOUND_NODES response into a list of ``KademliaContact`` objects.

        Parameters
        ----------
        encoded_response:
            Raw bytes of the FOUND_NODES reply.
        target_id_hex:
            The target ID that was requested; used to verify the response is
            for the right query.

        Returns
        -------
        list
            Up to *k* ``KademliaContact`` objects, sorted by XOR distance
            to the target (closest first).

        Raises
        ------
        ValueError
            If the response is not a valid FOUND_NODES message or does not
            match *target_id_hex*.
        """
        msg = decode_message(encoded_response)
        validate_message(msg, MSG_FOUND_NODES)
        if msg.get("target_id") != target_id_hex:
            raise ValueError(
                f"response target_id {msg.get('target_id')!r} does not match "
                f"expected {target_id_hex!r}"
            )
        raw_contacts = msg.get("contacts", [])
        contacts = dicts_to_contacts(raw_contacts)
        # Sort by XOR distance to the target so callers get closest-first.
        target_id = node_id_from_hex(target_id_hex)
        contacts.sort(key=lambda c: xor_distance(c.node_id, target_id))
        return contacts[: self._k]

    # ------------------------------------------------------------------
    # Responder side
    # ------------------------------------------------------------------

    def handle_request(
        self, encoded_request: bytes, peer_store
    ) -> tuple:
        """Process an incoming FIND_NODE request and return a FOUND_NODES reply.

        Looks up the *k* closest known contacts to the requested target in
        *peer_store* and builds the encoded reply.

        Parameters
        ----------
        encoded_request:
            Raw bytes of an incoming FIND_NODE message.
        peer_store:
            A :class:`~meshweaver.kademlia.peer_store.PeerStore` instance
            whose routing table will be queried for close contacts.

        Returns
        -------
        tuple[str, bytes]
            ``(target_id_hex, encoded_response)`` — the target that was
            requested and the ready-to-send FOUND_NODES bytes.

        Raises
        ------
        ValueError
            If *encoded_request* is not a valid FIND_NODE message.
        """
        msg = decode_message(encoded_request)
        validate_message(msg, MSG_FIND_NODE)
        target_id_hex = msg.get("target_id")
        if not target_id_hex:
            raise ValueError("FIND_NODE message missing 'target_id' field")

        target_id = node_id_from_hex(target_id_hex)

        # Collect all known contacts and sort by XOR distance to target.
        all_contacts = peer_store.routing_table.get_all_contacts()
        all_contacts.sort(key=lambda c: xor_distance(c.node_id, target_id))
        closest = all_contacts[: self._k]

        contact_dicts = contacts_to_dicts(closest)
        response = build_found_nodes(
            self._local_id_hex, target_id_hex, contact_dicts
        )
        return target_id_hex, encode_message(response)
