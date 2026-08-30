import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Dict, Optional

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


def create_message(message_type: str, sender_id: str, request_id: Optional[str] = None, payload: Any = None) -> Dict[str, Any]:
    if not message_type or not sender_id:
        raise ValueError("message_type and sender_id are required")
    message = {"type": message_type, "sender_id": sender_id}
    if request_id is not None:
        message["request_id"] = request_id
    if payload is not None:
        message["payload"] = payload
    return message


def create_request(message_type: str, sender_id: str, payload: Any = None) -> Dict[str, Any]:
    return create_message(message_type, sender_id, str(uuid.uuid4()), payload)


def create_task_route_request(sender_id: str, task_id: str, candidate_node: Optional[str] = None,
                              cpu_load: Optional[float] = None, candidates=None) -> Dict[str, Any]:
    payload = {
        "task_id": task_id,
        "source_node": sender_id,
        "candidate_node": candidate_node,
        "cpu_load": cpu_load,
        "candidates": list(candidates or []),
        "timestamp": time.time(),
    }
    return create_request(TASK_ROUTE_REQUEST, sender_id, payload)


def create_route_candidate_response(sender_id: str, request_id: str, task_id: str,
                                    candidate_node: str, cpu_load: float) -> Dict[str, Any]:
    return create_message(ROUTE_CANDIDATE_RESPONSE, sender_id, request_id, {
        "task_id": task_id, "source_node": sender_id, "candidate_node": candidate_node,
        "cpu_load": float(cpu_load), "timestamp": time.time(),
    })


def create_route_decision(sender_id: str, task_id: str, candidate_node: str,
                          cpu_load: Optional[float] = None, request_id: Optional[str] = None) -> Dict[str, Any]:
    return create_message(ROUTE_DECISION, sender_id, request_id, {
        "task_id": task_id, "source_node": sender_id, "candidate_node": candidate_node,
        "cpu_load": cpu_load, "timestamp": time.time(),
    })


def encode_message(message: Dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode_message(data: bytes) -> Dict[str, Any]:
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("message data must be bytes")
    message = json.loads(bytes(data).decode("utf-8"))
    validate_message(message)
    return message


def validate_message(message: Dict[str, Any]) -> None:
    if not isinstance(message, dict):
        raise ValueError("message must be an object")
    if not isinstance(message.get("type"), str) or not message.get("type"):
        raise ValueError("message.type is required")
    if not isinstance(message.get("sender_id"), str) or not message.get("sender_id"):
        raise ValueError("message.sender_id is required")
    if "request_id" in message and not isinstance(message["request_id"], str):
        raise ValueError("request_id must be a string")
    if "payload" in message and not isinstance(message["payload"], dict):
        raise ValueError("payload must be an object")


def canonical_bytes(message: Dict[str, Any]) -> bytes:
    unsigned = dict(message)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_message(message: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    signed = dict(message)
    signed["signature"] = hmac.new(secret, canonical_bytes(message), hashlib.sha256).hexdigest()
    return signed


def verify_message_signature(message: Dict[str, Any], secret: bytes) -> bool:
    signature = message.get("signature")
    if not isinstance(signature, str):
        return False
    expected = hmac.new(secret, canonical_bytes(message), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
