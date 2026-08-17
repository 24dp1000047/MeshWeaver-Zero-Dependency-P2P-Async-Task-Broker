"""
protocol.py — Message encoding / decoding for the MeshWeaver DHT layer.

All DHT RPC messages are JSON-serialised dicts sent over the wire.
Each message has at minimum two fields:

    ``type``      — one of the MSG_* constants below.
    ``sender_id`` — hex-encoded node ID of the originating node.

PING / PONG
-----------
* PING  — liveness probe; carries sender_id and an echo token.
* PONG  — reply to a PING; echoes back the same token so the caller can
          correlate the response.

FIND_NODE / FOUND_NODES
-----------------------
* FIND_NODE   — request the *k* closest known contacts to a target node ID.
* FOUND_NODES — response carrying a list of contacts.

Public API
----------
- MSG_PING, MSG_PONG, MSG_FIND_NODE, MSG_FOUND_NODES  — message type constants
- create_message(message_type, sender_id)              — generic helper (legacy)
- build_ping(sender_id_hex, token)                     — create a PING dict
- build_pong(sender_id_hex, token)                     — create a PONG dict
- build_find_node(sender_id_hex, target_id_hex)        — create FIND_NODE dict
- build_found_nodes(sender_id_hex, target_id_hex, contacts) — create response
- encode_message(message)                              — dict → UTF-8 bytes
- decode_message(data)                                 — UTF-8 bytes → dict
- validate_message(message, expected_type)             — basic structural check
"""

import json

# ---------------------------------------------------------------------------
# Message type constants
# ---------------------------------------------------------------------------

MSG_PING = "PING"
MSG_PONG = "PONG"
MSG_FIND_NODE = "FIND_NODE"
MSG_FOUND_NODES = "FOUND_NODES"

# ---------------------------------------------------------------------------
# Legacy helper (preserved for backwards-compatibility with earlier commits)
# ---------------------------------------------------------------------------


def create_message(message_type, sender_id):
    """Return a minimal message dict with *message_type* and *sender_id*.

    This is the original, generic helper preserved from Commit 3.
    Prefer the typed builders (``build_ping``, ``build_find_node``, …) for
    new code.
    """
    return {
        "type": message_type,
        "sender_id": sender_id,
    }


# ---------------------------------------------------------------------------
# PING / PONG builders
# ---------------------------------------------------------------------------


def build_ping(sender_id_hex: str, token: str) -> dict:
    """Return a PING message dict.

    Parameters
    ----------
    sender_id_hex:
        64-character hex-encoded node ID of the sender.
    token:
        An opaque string chosen by the caller (e.g. a UUID or sequence
        number) used to correlate the PONG reply.

    Returns
    -------
    dict
        ``{"type": "PING", "sender_id": ..., "token": ...}``
    """
    if not sender_id_hex:
        raise ValueError("sender_id_hex must not be empty")
    if not token:
        raise ValueError("token must not be empty")
    return {
        "type": MSG_PING,
        "sender_id": sender_id_hex,
        "token": token,
    }


def build_pong(sender_id_hex: str, token: str) -> dict:
    """Return a PONG message dict — the reply to a PING.

    Parameters
    ----------
    sender_id_hex:
        64-character hex-encoded node ID of the replying node.
    token:
        Must match the ``token`` field from the original PING so the
        initiator can correlate the reply.

    Returns
    -------
    dict
        ``{"type": "PONG", "sender_id": ..., "token": ...}``
    """
    if not sender_id_hex:
        raise ValueError("sender_id_hex must not be empty")
    if not token:
        raise ValueError("token must not be empty")
    return {
        "type": MSG_PONG,
        "sender_id": sender_id_hex,
        "token": token,
    }


# ---------------------------------------------------------------------------
# FIND_NODE / FOUND_NODES builders
# ---------------------------------------------------------------------------


def build_find_node(sender_id_hex: str, target_id_hex: str) -> dict:
    """Return a FIND_NODE request dict.

    Parameters
    ----------
    sender_id_hex:
        Hex-encoded node ID of the requesting node.
    target_id_hex:
        Hex-encoded node ID being looked up.

    Returns
    -------
    dict
        ``{"type": "FIND_NODE", "sender_id": ..., "target_id": ...}``
    """
    if not sender_id_hex:
        raise ValueError("sender_id_hex must not be empty")
    if not target_id_hex:
        raise ValueError("target_id_hex must not be empty")
    return {
        "type": MSG_FIND_NODE,
        "sender_id": sender_id_hex,
        "target_id": target_id_hex,
    }


def build_found_nodes(
    sender_id_hex: str,
    target_id_hex: str,
    contacts: list,
) -> dict:
    """Return a FOUND_NODES response dict.

    Parameters
    ----------
    sender_id_hex:
        Hex-encoded node ID of the responding node.
    target_id_hex:
        The target ID that was requested (echoed back for correlation).
    contacts:
        List of contact dicts, each with keys ``"node_id"``, ``"host"``,
        and ``"port"``.  Callers should pass at most *k* entries.

    Returns
    -------
    dict
        ``{"type": "FOUND_NODES", "sender_id": ..., "target_id": ...,
        "contacts": [...]}``
    """
    if not sender_id_hex:
        raise ValueError("sender_id_hex must not be empty")
    if not target_id_hex:
        raise ValueError("target_id_hex must not be empty")
    if not isinstance(contacts, list):
        raise TypeError("contacts must be a list")
    return {
        "type": MSG_FOUND_NODES,
        "sender_id": sender_id_hex,
        "target_id": target_id_hex,
        "contacts": contacts,
    }


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------


def encode_message(message: dict) -> bytes:
    """Serialise *message* to UTF-8 encoded JSON bytes."""
    return json.dumps(message).encode("utf-8")


def decode_message(data: bytes) -> dict:
    """Deserialise UTF-8 JSON bytes to a message dict."""
    return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


def validate_message(message: dict, expected_type: str) -> None:
    """Raise ``ValueError`` if *message* is structurally invalid.

    Checks:

    * ``message`` is a dict.
    * ``message["type"]`` matches *expected_type*.
    * ``message["sender_id"]`` is present and non-empty.

    Parameters
    ----------
    message:
        The decoded message dict.
    expected_type:
        One of the MSG_* constants this message is expected to be.

    Raises
    ------
    ValueError
        On any structural violation.
    """
    if not isinstance(message, dict):
        raise ValueError("message must be a dict")
    if message.get("type") != expected_type:
        raise ValueError(
            f"expected type {expected_type!r}, got {message.get('type')!r}"
        )
    if not message.get("sender_id"):
        raise ValueError("message missing non-empty 'sender_id'")