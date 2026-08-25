import json
import uuid
import time


# =========================================================
# Message Types
# =========================================================

# Existing Week 1–2 message types
PING = "PING"
PONG = "PONG"

# Week 3 routing message types
TASK_ROUTE_REQUEST = "TASK_ROUTE_REQUEST"
ROUTE_CANDIDATE_RESPONSE = "ROUTE_CANDIDATE_RESPONSE"
ROUTE_DECISION = "ROUTE_DECISION"


# =========================================================
# Common Message
# =========================================================

def create_message(
    message_type,
    sender_id,
    request_id=None,
    payload=None
):
    """
    Create a common MeshWeaver protocol message.

    Parameters:
        message_type:
            Type of message such as PING, PONG,
            TASK_ROUTE_REQUEST, etc.

        sender_id:
            ID of the node sending the message.

        request_id:
            Unique ID used to correlate a request
            with its response.

        payload:
            Optional message-specific data.
    """

    message = {
        "type": message_type,
        "sender_id": sender_id
    }

    if request_id is not None:
        message["request_id"] = request_id

    if payload is not None:
        message["payload"] = payload

    return message


# =========================================================
# Generic Request
# =========================================================

def create_request(
    message_type,
    sender_id,
    payload=None
):
    """
    Create a request message with a unique request ID.

    The request ID allows the networking layer to match
    the response with the original request.
    """

    request_id = str(uuid.uuid4())

    return create_message(
        message_type=message_type,
        sender_id=sender_id,
        request_id=request_id,
        payload=payload
    )


# =========================================================
# TASK ROUTE REQUEST
# =========================================================

def create_task_route_request(
    sender_id,
    task_id,
    candidate_node=None,
    cpu_load=None
):
    """
    Create a task-routing request.

    Routing metadata includes:

        task_id
        source_node
        candidate_node
        cpu_load
        timestamp
    """

    payload = {
        "task_id": task_id,
        "source_node": sender_id,
        "candidate_node": candidate_node,
        "cpu_load": cpu_load,
        "timestamp": time.time()
    }

    return create_request(
        message_type=TASK_ROUTE_REQUEST,
        sender_id=sender_id,
        payload=payload
    )


# =========================================================
# ROUTE CANDIDATE RESPONSE
# =========================================================

def create_route_candidate_response(
    sender_id,
    request_id,
    task_id,
    candidate_node,
    cpu_load
):
    """
    Create a candidate-node response.

    The request_id from the original routing request
    is preserved so the sender can correlate this
    response with the correct request.
    """

    payload = {
        "task_id": task_id,
        "source_node": sender_id,
        "candidate_node": candidate_node,
        "cpu_load": cpu_load,
        "timestamp": time.time()
    }

    return create_message(
        message_type=ROUTE_CANDIDATE_RESPONSE,
        sender_id=sender_id,
        request_id=request_id,
        payload=payload
    )


# =========================================================
# ROUTE DECISION
# =========================================================

def create_route_decision(
    sender_id,
    task_id,
    candidate_node,
    cpu_load=None
):
    """
    Create a routing decision message.

    This message indicates the node selected for
    execution of a particular task.
    """

    payload = {
        "task_id": task_id,
        "source_node": sender_id,
        "candidate_node": candidate_node,
        "cpu_load": cpu_load,
        "timestamp": time.time()
    }

    return create_message(
        message_type=ROUTE_DECISION,
        sender_id=sender_id,
        payload=payload
    )


# =========================================================
# Message Encoding
# =========================================================

def encode_message(message):
    """
    Convert a Python dictionary into UTF-8 encoded JSON.
    """

    return json.dumps(message).encode("utf-8")


# =========================================================
# Message Decoding
# =========================================================

def decode_message(data):
    """
    Convert UTF-8 encoded JSON bytes into a Python dictionary.
    """

    return json.loads(data.decode("utf-8"))