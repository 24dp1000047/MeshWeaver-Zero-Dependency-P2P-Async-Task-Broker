import asyncio
import time

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


# =========================================================
# Protocol-Level Tests
# =========================================================

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


# =========================================================
# UDP Network Helper
# =========================================================

async def create_network(node):
    """
    Create a UDP NetworkProtocol for the given node.

    Port 0 allows the operating system to automatically
    assign an available UDP port.
    """

    loop = asyncio.get_running_loop()

    protocol = NetworkProtocol(node)

    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol,
        local_addr=(node.host, node.port),
    )

    return transport, protocol


# =========================================================
# Two-Node Routing Integration Test
# =========================================================

async def run_two_node_task_routing():
    """
    Test real UDP task-routing communication.

    Flow:

        Node A
           |
           | TASK_ROUTE_REQUEST
           v
        Node B
           |
           | ROUTE_CANDIDATE_RESPONSE
           v
        Node A
    """

    node_a = Node(
        node_id="node-a",
        host="127.0.0.1",
        port=0,
    )

    node_b = Node(
        node_id="node-b",
        host="127.0.0.1",
        port=0,
    )

    transport_a = None
    transport_b = None

    try:
        # -------------------------------------------------
        # Start Node A
        # -------------------------------------------------

        transport_a, network_a = await create_network(node_a)

        # -------------------------------------------------
        # Start Node B
        # -------------------------------------------------

        transport_b, network_b = await create_network(node_b)

        # -------------------------------------------------
        # Get the actual UDP address assigned to Node B
        # -------------------------------------------------

        address_a = transport_a.get_extra_info("sockname")
        address_b = transport_b.get_extra_info("sockname")

        print(f"Node A address: {address_a}")
        print(f"Node B address: {address_b}")

        # -------------------------------------------------
        # Node A -> Node B
        # TASK_ROUTE_REQUEST
        # -------------------------------------------------

        response = await network_a.send_request(
            TASK_ROUTE_REQUEST,
            address_b,
            payload={
                "task_id": "task-001",
                "source_node": "node-a",
                "candidate_node": "node-b",
                "cpu_load": 25.5,
                "timestamp": time.time(),
            },
            timeout=3,
        )

        # -------------------------------------------------
        # Verify response type
        # -------------------------------------------------

        assert response["type"] == ROUTE_CANDIDATE_RESPONSE

        # -------------------------------------------------
        # Verify request/response correlation
        # -------------------------------------------------

        assert response["request_id"]

        # The request should no longer be pending after
        # the response has been received.
        assert response["request_id"] not in network_a.pending_requests

        # -------------------------------------------------
        # Verify response sender
        # -------------------------------------------------

        assert response["sender_id"] == "node-b"

        # -------------------------------------------------
        # Verify routing metadata
        # -------------------------------------------------

        payload = response["payload"]

        assert payload["task_id"] == "task-001"
        assert payload["source_node"] == "node-a"
        assert payload["candidate_node"] == "node-b"
        assert payload["cpu_load"] == 25.5
        assert "timestamp" in payload

    finally:
        # -------------------------------------------------
        # Cleanly close Node A
        # -------------------------------------------------

        if transport_a is not None:
            transport_a.close()

        # -------------------------------------------------
        # Cleanly close Node B
        # -------------------------------------------------

        if transport_b is not None:
            transport_b.close()

        # Give the asyncio event loop a moment to process
        # transport shutdown.
        await asyncio.sleep(0.05)


def test_two_node_task_routing():
    """
    Synchronous pytest wrapper for the asynchronous
    two-node UDP routing test.

    No pytest-asyncio dependency is required.
    """

    asyncio.run(run_two_node_task_routing())