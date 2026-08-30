# Cryptographic Node Identity — MeshWeaver DHT

> Week 4 work (Days 13–20) by Varad — `Varad-kademlia-dht` branch.

This document describes the **node identity → signing → verification** flow
introduced in Commits 12–15.  All code uses only the Python standard library
(`hashlib`, `hmac`, `secrets`, `base64`, `json`, `os`) — no external packages.

---

## Overview

Each DHT node has a unique **cryptographic identity** consisting of a
private/public key pair.  When a node issues a task-execution request
(`TASK_REQUEST`) it **signs** the message with its identity.  The receiving
node **verifies** the signature before acting on the request.

```
  Node A                                         Node B
  ──────                                         ──────
  generate_keypair()                             (knows A's public_key via
       │                                          identity exchange)
       ▼
  build_task_request(...)         wire bytes
  sign_request(msg)  ──────────────────────────► verify_request(msg, A.pub_key)
                                                       │
                                                  True / False
```

---

## Key Derivation Scheme

```
private_key  =  secrets.token_bytes(32)       # 32 random bytes, kept secret
public_key   =  SHA-256(private_key)          # 32 bytes, shared with peers
node_id      =  SHA-256(public_key)           # 32 bytes, Kademlia routing ID
signature    =  HMAC-SHA256(public_key, canonical_payload)   # 32 bytes (hex)
```

Using the **public key** as the HMAC secret is the key design choice: it lets
any peer that knows the sender's public key independently verify a signature
— the private key never needs to leave the originating node.

---

## Module Reference

| Module | Class / function | Purpose |
|---|---|---|
| `meshweaver.kademlia.identity` | `NodeKeyPair` | Immutable frozen dataclass holding `private_key` and `public_key` |
| | `generate_keypair()` | Create a fresh random key pair |
| | `node_id_from_keypair(kp)` | Derive the 32-byte Kademlia node ID |
| | `save_keypair(kp, path)` | Persist the private key to a text file |
| | `load_keypair(path)` | Restore a key pair from a text file |
| `meshweaver.protocol` | `MSG_TASK_REQUEST` | Message type constant `"TASK_REQUEST"` |
| | `build_task_request(sender_id_hex, task_id, payload)` | Build an unsigned TASK_REQUEST dict |
| `meshweaver.kademlia.signer` | `canonical_payload(message)` | Deterministic bytes used for signing/verification |
| | `TaskSigner(keypair)` | Signs TASK_REQUEST messages |
| | `.sign_request(message)` | Returns a signed copy with `"signature"` added |
| `meshweaver.kademlia.verifier` | `SignatureVerifier()` | Stateless verifier |
| | `.verify_request(message, public_key)` | Returns `True` iff signature is valid |

---

## Quick-Start Example

```python
from meshweaver.kademlia.identity import generate_keypair, node_id_from_keypair
from meshweaver.kademlia.signer import TaskSigner
from meshweaver.kademlia.verifier import SignatureVerifier
from meshweaver.protocol import build_task_request

# ── Node A (sender) ──────────────────────────────────────────────────────────
kp_a = generate_keypair()
node_id_a = node_id_from_keypair(kp_a)   # 32-byte Kademlia node ID

signer = TaskSigner(kp_a)
unsigned = build_task_request(
    sender_id_hex=kp_a.public_key_hex(),
    task_id="job-42",
    payload={"fn": "matrix_mul", "size": 512},
)
signed = signer.sign_request(unsigned)
# signed["signature"] is now a 64-char hex HMAC-SHA256 string

# ── Node B (receiver, knows kp_a.public_key via identity exchange) ───────────
verifier = SignatureVerifier()
ok = verifier.verify_request(signed, kp_a.public_key)
# ok == True  →  message is authentic and untampered
```

---

## Key Persistence

Keys are stored in a PEM-inspired plain-text format.  Only the 32-byte
private key is written; the public key and node ID are always re-derived on
load.

```python
from meshweaver.kademlia.identity import save_keypair, load_keypair

save_keypair(kp_a, "/var/lib/meshweaver/node.key")

# Later, on restart:
kp_a = load_keypair("/var/lib/meshweaver/node.key")
```

File format:

```
-----BEGIN MESHWEAVER PRIVATE KEY-----
<base64-encoded 32-byte private key>
-----END MESHWEAVER PRIVATE KEY-----
```

---

## Canonical Payload

The bytes that are signed (and verified) are produced by `canonical_payload()`.
It covers exactly these four fields from a TASK_REQUEST, JSON-serialised with
sorted keys and no whitespace:

```json
{"payload":{...},"sender_id":"<hex>","task_id":"<id>","type":"TASK_REQUEST"}
```

The `"signature"` field is **excluded** from the canonical payload so that
`canonical_payload()` is identical whether called before or after signing.
Any extra metadata fields (outside these four) are also excluded, meaning
they do not affect the signature but are forwarded through the system unchanged.

---

## Security Properties

| Property | Status |
|---|---|
| **Authenticity** | A valid signature proves the message was created by the holder of the private key corresponding to the stated public key. |
| **Integrity** | Any modification to `type`, `sender_id`, `task_id`, or `payload` invalidates the signature. |
| **Timing-safe comparison** | `hmac.compare_digest()` is used — resistant to timing side-channel attacks. |
| **No private key sharing** | Only the public key is broadcast; the private key never leaves the originating node. |
| **Deterministic** | HMAC-SHA256 is deterministic — same key + same message = same signature. |

### Known Limitations (intentional for zero-dependency scope)

- **Symmetric HMAC, not asymmetric**: The scheme is not truly public-key cryptography.  A node that has the public key can forge signatures for that node.  In production a real asymmetric scheme (e.g., Ed25519 via `cryptography`) would be used.
- **No PKI / CA**: Public keys are exchanged out-of-band (e.g., passed at bootstrap time).  There is no certificate authority or revocation mechanism.
- **No nonce / replay prevention**: The same signed message can be replayed.  A production system would add a timestamp or nonce to the payload.

---

## Test Coverage

| Test file | What it covers |
|---|---|
| `tests/test_node_identity.py` | Key generation, derivation, save/load round-trip, error cases |
| `tests/test_task_signing.py` | `build_task_request`, `canonical_payload`, `TaskSigner.sign_request` |
| `tests/test_signature_verification.py` | `SignatureVerifier`: valid, wrong key, tampered fields, malformed input |
| `tests/test_crypto_identity_security.py` | End-to-end security scenarios, cross-node, replay, persistence, wire round-trip |

Run the full suite:

```
python -m pytest tests/ -v
```
