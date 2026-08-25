import asyncio
import time

import pytest

from meshweaver.node import Node
from meshweaver.network import NetworkProtocol
from meshweaver.protocol import (
    TASK_ROUTE_REQUEST,
    ROUTE_CANDIDATE_RESPONSE,
    create_task_route_request,
    create_route_candidate_response,
    encode_message,
    decode_message,
)


def test_task_route_request_contains_required_metadata():
    message = create_task_route_request(
        sender_id="node-1",
        task_id="task-001",
        candidate_node="node-2",
        cpu_load=25.5,
    )

    assert message["type"] == TASK_ROUTE_REQUEST
    assert message["request_id"]

    payload = message["payload"]

    assert payload["task_id"] == "task-001"
    assert payload["source_node"] == "node-1"
    assert payload["candidate_node"] == "node-2"
    assert payload["cpu_load"] == 25.5
    assert "timestamp" in payload


def test_routing_message_encode_decode():
    message = create_task_route_request(
        sender_id="node-1",
        task_id="task-001",
        candidate_node="node-2",
        cpu_load=30.0,
    )

    encoded = encode_message(message)
    decoded = decode_message(encoded)

    assert decoded == message


def test_candidate_response_preserves_request_id():
    request = create_task_route_request(
        sender_id="node-1",
        task_id="task-001",
        candidate_node="node-2",
        cpu_load=20.0,
    )

    response = create_route_candidate_response(
        sender_id="node-2",
        request_id=request["request_id"],
        task_id="task-001",
        candidate_node="node-2",
        cpu_load=20.0,
    )

    assert response["type"] == ROUTE_CANDIDATE_RESPONSE
    assert response["request_id"] == request["request_id"]
    assert response["payload"]["task_id"] == "task-001"
    assert response["payload"]["candidate_node"] == "node-2"
    assert response["payload"]["cpu_load"] == 20.0