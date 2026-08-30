import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Dict


class NodeIdentity:
    """Zero-dependency authenticated node identity using HMAC-SHA256."""

    def __init__(self, node_id: str, secret: bytes):
        if not node_id or not secret:
            raise ValueError("node_id and secret are required")
        self.node_id = node_id
        self.secret = bytes(secret)

    @classmethod
    def generate(cls, node_id: str, size: int = 32):
        return cls(node_id, secrets.token_bytes(size))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.secret).hexdigest()[:16]

    def sign(self, message: Dict) -> Dict:
        from meshweaver.protocol import sign_message
        return sign_message(message, self.secret)

    def verify(self, message: Dict) -> bool:
        from meshweaver.protocol import verify_message_signature
        return verify_message_signature(message, self.secret)

    def save(self, path: str) -> None:
        Path(path).write_bytes(self.secret)

    @classmethod
    def load(cls, node_id: str, path: str):
        return cls(node_id, Path(path).read_bytes())
