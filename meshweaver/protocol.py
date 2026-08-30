"""
protocol.py — Message encoding / decoding for the MeshWeaver P2P layer.

All messages are JSON-serialised dicts sent over the wire.
Each message has at minimum two fields:

    ``type``      — one of the message type constants below.
    ``sender_id`` — node ID of the originating node.

DHT RPC Messages (Kademlia layer)
----------------------------------
* PING        — liveness probe; carries sender_id and an echo token.
* PONG        — reply to a PING; echoes back the same token.
* FIND_NODE   — request the k closest known contacts to a target node ID.
* FOUND_NODES — response carrying a list of contacts.
* TASK_REQUEST — a signed task-execution request issued by a node.

Async Routing / Task Protocol (Prateek's async-networking layer)
-----------------------------------------------------------------
* TASK_ROUTE_REQUEST      — broadcast to find the best executor node.
* ROUTE_CANDIDATE_RESPONSE — a node's reply offering itself as a candidate.
* ROUTE_DECISION          — coordinator selects the winning executor.
* TASK_SUBMIT             — send task payload to the selected executor.
* TASK_RESULT             — result returned by the executor.
* TASK_ERROR              — error report from the executor.
* TASK_REASSIGN           — re-route a task to a different node after failure.
* HEARTBEAT               — periodic liveness signal.
* HEARTBEAT_ACK           — acknowledgement of a heartbeat.

Public API — DHT layer (backward-compatible)
---------------------------------------------
- MSG_PING, MSG_PONG, MSG_FIND_NODE, MSG_FOUND_NODES  — type constants
- MSG_TASK_REQUEST                                     — task request type
- create_message(message_type, sender_id, ...)         — generic helper
- build_ping(sender_id_hex, token)                     — create PING dict
- build_pong(sender_id_hex, token)                     — create PONG dict
- build_find_node(sender_id_hex, target_id_hex)        — create FIND_NODE dict
- build_found_nodes(sender_id_hex, target_id_hex, contacts)
- build_task_request(sender_id_hex, task_id, payload)  — create TASK_REQUEST
- encode_message(message)                              — dict → UTF-8 bytes
- decode_message(data)                                 — UTF-8 bytes → dict
- validate_message(message[, expected_type])           — structural check

Public API — Async routing layer (Prateek)
------------------------------------------
- TASK_ROUTE_REQUEST, ROUTE_CANDIDATE_RESPONSE, ROUTE_DECISION
- TASK_SUBMIT, TASK_RESULT, TASK_ERROR, TASK_REASSIGN
- HEARTBEAT, HEARTBEAT_ACK
- create_request(message_type, sender_id, payload)         — auto UUID
- create_task_route_request(sender_id, task_id, ...)
- create_route_candidate_response(sender_id, request_id, ...)
- create_route_decision(sender_id, task_id, candidate_node, ...)
- canonical_bytes(message)                                 — signing helper
- sign_message(message, secret)                            — HMAC-SHA256 sign
- verify_message_signature(message, secret)                — verify HMAC sig
"""

import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Message type constants — DHT / Kademlia layer
# ---------------------------------------------------------------------------

MSG_PING = "PING"
MSG_PONG = "PONG"
MSG_FIND_NODE = "FIND_NODE"
MSG_FOUND_NODES = "FOUND_NODES"
MSG_TASK_REQUEST = "TASK_REQUEST"

# ---------------------------------------------------------------------------
# Message type constants — Async routing / task layer (Prateek)
# ---------------------------------------------------------------------------

PING = "PING"
PONG = "PONG"
TASK_ROUTE_REQUEST = "TASK_ROUTE_REQUEST"
ROUTE_CANDIDATE_RESPONSE = "ROUTE_CANDIDATE_RESPONSE"
ROUTE_DECISION = "ROUTE_DECISION"
TASK_SUBMIT = "TASK_SUBMIT"
TASK_RESULT = "TASK_RESULT"
TASK_ERROR = "TASK_ERROR"
TASK_REASSIGN = "TASK_REASSIGN"
HEARTBEAT = "HEARTBEAT"
HEARTBEAT_ACK = "HEARTBEAT_ACK"

# ---------------------------------------------------------------------------
# Generic message helper (supports both legacy and new call signatures)
# ---------------------------------------------------------------------------


def create_message(
    message_type: str,
    sender_id: str,
    request_id: Optional[str] = None,
    payload: Any = None,
) -> Dict[str, Any]:
    """Return a message dict with *message_type* and *sender_id*.

    This is both the original generic helper (Commit 3 backward compat) and
    Prateek's extended version that supports optional *request_id* and *payload*.

    Parameters
    ----------
    message_type:
        One of the message type constants.
    sender_id:
        Node ID of the originating node.  Must be non-empty.
    request_id:
        Optional UUID string for request/response correlation.
    payload:
        Optional dict carrying message-specific data.

    Returns
    -------
    dict
        ``{"type": ..., "sender_id": ...[, "request_id": ...][, "payload": ...]}``
    """
    if not message_type or not sender_id:
        raise ValueError("message_type and sender_id are required")
    message: Dict[str, Any] = {"type": message_type, "sender_id": sender_id}
    if request_id is not None:
        message["request_id"] = request_id
    if payload is not None:
        message["payload"] = payload
    return message


# ---------------------------------------------------------------------------
# Async routing helpers (Prateek)
# ---------------------------------------------------------------------------


def create_request(
    message_type: str,
    sender_id: str,
    payload: Any = None,
) -> Dict[str, Any]:
    """Like :func:`create_message` but auto-generates a UUID *request_id*."""
    return create_message(message_type, sender_id, str(uuid.uuid4()), payload)


def create_task_route_request(
    sender_id: str,
    task_id: str,
    candidate_node: Optional[str] = None,
    cpu_load: Optional[float] = None,
    candidates=None,
) -> Dict[str, Any]:
    """Create a TASK_ROUTE_REQUEST broadcast message."""
    payload = {
        "task_id": task_id,
        "source_node": sender_id,
        "candidate_node": candidate_node,
        "cpu_load": cpu_load,
        "candidates": list(candidates or []),
        "timestamp": time.time(),
    }
    return create_request(TASK_ROUTE_REQUEST, sender_id, payload)


def create_route_candidate_response(
    sender_id: str,
    request_id: str,
    task_id: str,
    candidate_node: str,
    cpu_load: float,
) -> Dict[str, Any]:
    """Create a ROUTE_CANDIDATE_RESPONSE in reply to a TASK_ROUTE_REQUEST."""
    return create_message(
        ROUTE_CANDIDATE_RESPONSE,
        sender_id,
        request_id,
        {
            "task_id": task_id,
            "source_node": sender_id,
            "candidate_node": candidate_node,
            "cpu_load": float(cpu_load),
            "timestamp": time.time(),
        },
    )


def create_route_decision(
    sender_id: str,
    task_id: str,
    candidate_node: str,
    cpu_load: Optional[float] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a ROUTE_DECISION announcing the chosen executor."""
    return create_message(
        ROUTE_DECISION,
        sender_id,
        request_id,
        {
            "task_id": task_id,
            "source_node": sender_id,
            "candidate_node": candidate_node,
            "cpu_load": cpu_load,
            "timestamp": time.time(),
        },
    )


# ---------------------------------------------------------------------------
# PING / PONG builders (DHT / Kademlia layer)
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
# TASK_REQUEST builder
# ---------------------------------------------------------------------------


def build_task_request(
    sender_id_hex: str,
    task_id: str,
    payload: dict,
) -> dict:
    """Return an **unsigned** TASK_REQUEST message dict.

    The returned dict contains ``type``, ``sender_id``, ``task_id``, and
    ``payload``.  It does **not** include a ``signature`` field — that is
    added separately by :func:`meshweaver.kademlia.signer.TaskSigner.sign_request`
    so that the canonical signing payload is always computed from a clean,
    signature-free dict.

    Parameters
    ----------
    sender_id_hex:
        64-character hex-encoded node ID of the requesting node.
    task_id:
        An opaque identifier for the task (e.g. a UUID string).  Must be
        non-empty.
    payload:
        Arbitrary JSON-serialisable dict carrying task parameters.

    Returns
    -------
    dict
        ``{"type": "TASK_REQUEST", "sender_id": ...,
        "task_id": ..., "payload": {...}}``

    Raises
    ------
    ValueError
        If *sender_id_hex* or *task_id* is empty.
    TypeError
        If *payload* is not a dict.
    """
    if not sender_id_hex:
        raise ValueError("sender_id_hex must not be empty")
    if not task_id:
        raise ValueError("task_id must not be empty")
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    return {
        "type": MSG_TASK_REQUEST,
        "sender_id": sender_id_hex,
        "task_id": task_id,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------


def encode_message(message: Dict[str, Any]) -> bytes:
    """Serialise *message* to UTF-8 encoded JSON bytes (canonical, sorted keys)."""
    return json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode_message(data: bytes) -> Dict[str, Any]:
    """Deserialise UTF-8 JSON bytes to a message dict and validate structure."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("message data must be bytes")
    message = json.loads(bytes(data).decode("utf-8"))
    validate_message(message)
    return message


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


def validate_message(
    message: Dict[str, Any],
    expected_type: Optional[str] = None,
) -> None:
    """Raise ``ValueError`` if *message* is structurally invalid.

    Checks:

    * ``message`` is a dict.
    * ``message["type"]`` is a non-empty string.
    * ``message["sender_id"]`` is a non-empty string.
    * If *expected_type* is given, ``message["type"]`` must match it.
    * If present, ``message["request_id"]`` must be a string.
    * If present, ``message["payload"]`` must be a dict.

    Parameters
    ----------
    message:
        The decoded message dict.
    expected_type:
        Optional.  One of the message type constants.  When supplied the
        message type must match exactly (backward compat with DHT layer).

    Raises
    ------
    ValueError
        On any structural violation.
    """
    if not isinstance(message, dict):
        raise ValueError("message must be a dict")
    if not isinstance(message.get("type"), str) or not message.get("type"):
        raise ValueError("message.type is required")
    if expected_type is not None and message.get("type") != expected_type:
        raise ValueError(
            f"expected type {expected_type!r}, got {message.get('type')!r}"
        )
    if not isinstance(message.get("sender_id"), str) or not message.get("sender_id"):
        raise ValueError("message missing non-empty 'sender_id'")
    if "request_id" in message and not isinstance(message["request_id"], str):
        raise ValueError("request_id must be a string")
    if "payload" in message and not isinstance(message["payload"], dict):
        raise ValueError("payload must be an object")


# ---------------------------------------------------------------------------
# HMAC-SHA256 message signing (Prateek's security layer)
# ---------------------------------------------------------------------------


def canonical_bytes(message: Dict[str, Any]) -> bytes:
    """Return the canonical, signature-free JSON bytes used for HMAC signing."""
    unsigned = dict(message)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_message(message: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """Return a copy of *message* with an HMAC-SHA256 ``signature`` field."""
    signed = dict(message)
    signed["signature"] = hmac.new(
        secret, canonical_bytes(message), hashlib.sha256
    ).hexdigest()
    return signed


def verify_message_signature(message: Dict[str, Any], secret: bytes) -> bool:
    """Return ``True`` if *message* carries a valid HMAC-SHA256 signature."""
    signature = message.get("signature")
    if not isinstance(signature, str):
        return False
    expected = hmac.new(
        secret, canonical_bytes(message), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
