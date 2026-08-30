"""
verifier.py — Signature verification for TASK_REQUEST messages.

When a node receives a TASK_REQUEST it must verify that:

    1. The message carries a ``signature`` field.
    2. The signature is a valid 64-character hex string (32 bytes).
    3. The signature was produced by HMAC-SHA256(sender_public_key,
       canonical_payload) \u2014 the same computation used by
       :class:`~meshweaver.kademlia.signer.TaskSigner`.

If any of these checks fail the message is rejected.  If the payload
was tampered with after signing the re-computed HMAC will not match and
the message is also rejected.

Security note
-------------
The verifier uses ``hmac.compare_digest()`` for the final comparison,
which is timing-safe and resistant to timing side-channel attacks.

Public API
----------
- ``SignatureVerifier`` \u2014 verifies TASK_REQUEST message signatures.
"""

from __future__ import annotations

import hashlib
import hmac

from meshweaver.kademlia.signer import canonical_payload


# ---------------------------------------------------------------------------
# SignatureVerifier
# ---------------------------------------------------------------------------


class SignatureVerifier:
    """Verifies HMAC-SHA256 signatures on TASK_REQUEST messages.

    Usage pattern::

        from meshweaver.kademlia.verifier import SignatureVerifier

        verifier = SignatureVerifier()

        # `public_key` is the 32-byte public key of the claimed sender,
        # obtained from an identity-exchange or peer registry.
        is_valid = verifier.verify_request(received_message, sender_public_key)
        if not is_valid:
            # reject \u2014 tampered, forged, or missing signature
            ...

    The verifier is **stateless** \u2014 it holds no keys and no per-connection
    state.  Callers supply the sender's public key on every call, making
    it safe to share a single :class:`SignatureVerifier` instance across
    many concurrent requests.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify_request(self, message: dict, public_key: bytes) -> bool:
        """Verify the HMAC-SHA256 signature on a signed TASK_REQUEST.

        The method re-computes ``HMAC-SHA256(public_key, canonical_payload)``
        and compares it with the ``signature`` field in *message* using a
        timing-safe comparison.

        Parameters
        ----------
        message:
            A received (and potentially signed) TASK_REQUEST dict.  The
            dict must contain all four canonical fields (``type``,
            ``sender_id``, ``task_id``, ``payload``) plus a ``signature``
            field added by the sender.
        public_key:
            The 32-byte public key of the *claimed* sender, obtained from
            a peer registry or identity exchange.  This is the same key
            the sender used as the HMAC secret when signing.

        Returns
        -------
        bool
            ``True`` if the signature is present, well-formed, and matches
            the expected HMAC.  ``False`` in every other case, including:

            * ``signature`` field is absent from *message*.
            * ``signature`` is not a valid 64-character hex string.
            * The recomputed HMAC does not match the stored signature.
            * *message* is missing a required canonical field.
            * *message* has the wrong ``type``.
            * *public_key* has wrong length or wrong type.

        Notes
        -----
        This method never raises on bad input \u2014 it returns ``False``
        instead, making it safe to call on untrusted / malformed messages
        without try/except wrappers at the call site.
        """
        try:
            return self._verify(message, public_key)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private implementation
    # ------------------------------------------------------------------

    def _verify(self, message: dict, public_key: bytes) -> bool:
        """Inner verification logic \u2014 may raise; wrapped by verify_request."""
        # ---------------------------------------------------------------
        # 1. Basic type / key checks
        # ---------------------------------------------------------------
        if not isinstance(message, dict):
            return False
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            return False

        # ---------------------------------------------------------------
        # 2. Extract and validate the signature field
        # ---------------------------------------------------------------
        sig_hex = message.get("signature")
        if not sig_hex:
            return False  # missing signature
        if not isinstance(sig_hex, str) or len(sig_hex) != 64:
            return False  # wrong format / length

        try:
            sig_bytes = bytes.fromhex(sig_hex)
        except ValueError:
            return False  # not valid hex

        # ---------------------------------------------------------------
        # 3. Re-compute the expected HMAC
        # ---------------------------------------------------------------
        payload_bytes = canonical_payload(message)
        expected = hmac.new(
            public_key,
            payload_bytes,
            hashlib.sha256,
        ).digest()

        # ---------------------------------------------------------------
        # 4. Timing-safe comparison
        # ---------------------------------------------------------------
        return hmac.compare_digest(expected, sig_bytes)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return "SignatureVerifier()"
