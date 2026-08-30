"""
signer.py — Task-request signing using the node's cryptographic identity.

When a node issues a TASK_REQUEST it signs the request with its identity
key pair so that receiving nodes can verify the request came from who it
claims to be and that no field was tampered with in transit.

Signing scheme
--------------
    canonical_payload = JSON({ type, sender_id, task_id, payload })
                        with keys sorted, no extra whitespace
    signature         = HMAC-SHA256(public_key, canonical_payload.encode())
    signature_hex     = signature.hex()   # 64-char lowercase hex

Why the *public* key is the HMAC secret:
    HMAC-SHA256 is a symmetric construction \u2014 both parties must know the
    secret.  The public key (SHA-256(private_key)) is broadcast to peers
    as part of identity exchange.  Using it as the HMAC secret lets any
    peer that knows the sender's public key independently verify the
    signature without ever seeing the private key.

The ``signature`` field is deliberately excluded from the canonical
payload so that the payload used for signing/verification is always
deterministic and does not depend on the current signature value.

Public API
----------
- ``TaskSigner`` \u2014 signs TASK_REQUEST dicts using a node key pair.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from meshweaver.kademlia.identity import NodeKeyPair
from meshweaver.protocol import MSG_TASK_REQUEST


# ---------------------------------------------------------------------------
# Canonical payload helper (module-level so verifier can reuse it)
# ---------------------------------------------------------------------------


def canonical_payload(message: dict) -> bytes:
    """Return the canonical UTF-8 bytes used for signing and verification.

    The canonical form covers the four mandatory TASK_REQUEST fields:
    ``type``, ``sender_id``, ``task_id``, and ``payload``.  The
    ``signature`` field is intentionally excluded so the same bytes are
    produced regardless of whether a signature is already attached.

    Keys are sorted alphabetically and no extra whitespace is added,
    making the output fully deterministic across Python versions and
    platforms.

    Parameters
    ----------
    message:
        A TASK_REQUEST dict (with or without a ``signature`` field).

    Returns
    -------
    bytes
        UTF-8 encoded canonical JSON string.

    Raises
    ------
    KeyError
        If any of the required fields (``type``, ``sender_id``,
        ``task_id``, ``payload``) is missing from *message*.
    ValueError
        If the message type is not ``MSG_TASK_REQUEST``.
    """
    if message.get("type") != MSG_TASK_REQUEST:
        raise ValueError(
            f"canonical_payload expects a TASK_REQUEST message, "
            f"got type={message.get('type')!r}"
        )
    # Only include the fields that are part of the signed contract.
    signing_dict = {
        "payload": message["payload"],
        "sender_id": message["sender_id"],
        "task_id": message["task_id"],
        "type": message["type"],
    }
    return json.dumps(signing_dict, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


# ---------------------------------------------------------------------------
# TaskSigner
# ---------------------------------------------------------------------------


class TaskSigner:
    """Signs TASK_REQUEST dicts using the node's cryptographic identity.

    Usage pattern::

        from meshweaver.kademlia.identity import generate_keypair
        from meshweaver.kademlia.signer import TaskSigner
        from meshweaver.protocol import build_task_request

        kp = generate_keypair()
        signer = TaskSigner(kp)

        unsigned = build_task_request(
            sender_id_hex=kp.public_key_hex(),
            task_id="task-001",
            payload={"fn": "add", "args": [1, 2]},
        )
        signed = signer.sign_request(unsigned)
        # signed now has a \"signature\" field

    Parameters
    ----------
    keypair:
        The :class:`~meshweaver.kademlia.identity.NodeKeyPair` of the
        signing node.  The public key is used as the HMAC-SHA256 secret.
    """

    def __init__(self, keypair: NodeKeyPair) -> None:
        if not isinstance(keypair, NodeKeyPair):
            raise TypeError(
                f"keypair must be a NodeKeyPair instance, got {type(keypair)!r}"
            )
        self._keypair = keypair

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sign_request(self, message: dict) -> dict:
        """Sign *message* and return a new dict with a ``signature`` field.

        The original *message* dict is **not** mutated.  A shallow copy is
        returned with the ``signature`` key added.

        Parameters
        ----------
        message:
            An **unsigned** TASK_REQUEST dict as returned by
            :func:`~meshweaver.protocol.build_task_request`.

        Returns
        -------
        dict
            A copy of *message* with ``\"signature\"`` set to a 64-character
            lowercase hex string (``HMAC-SHA256(public_key, canonical)``).

        Raises
        ------
        KeyError
            If a required field is missing from *message*.
        ValueError
            If *message* is not a TASK_REQUEST.
        """
        payload_bytes = canonical_payload(message)
        sig_bytes = hmac.new(
            self._keypair.public_key,
            payload_bytes,
            hashlib.sha256,
        ).digest()
        signed = dict(message)
        signed["signature"] = sig_bytes.hex()
        return signed

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def keypair(self) -> NodeKeyPair:
        """The key pair this signer was constructed with."""
        return self._keypair

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TaskSigner(public_key={self._keypair.public_key.hex()[:16]}\u2026)"
        )
