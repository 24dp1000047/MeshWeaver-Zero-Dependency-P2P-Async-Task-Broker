import asyncio
import time

from meshweaver.node import Node
from meshweaver.network import NetworkProtocol
from meshweaver.protocol import TASK_ROUTE_REQUEST, ROUTE_CANDIDATE_RESPONSE, create_task_route_request, encode_message, decode_message


def test_task_route_request_contains_required_metadata():
    message = create_task_route_request("node-1", "task-001", "node-2", 25.5)
    assert message["type"] == TASK_ROUTE_REQUEST
    assert message["request_id"]
    payload = message["payload"]
    assert payload["task_id"] == "task-001"
    assert payload["source_node"] == "node-1"
    assert payload["candidate_node"] == "node-2"
    assert payload["cpu_load"] == 25.5
    assert "timestamp" in payload


def test_routing_message_encode_decode():
    message = create_task_route_request("node-1", "task-001", "node-2", 30.0)
    assert decode_message(encode_message(message)) == message


async def run_two_node_task_routing():
    loop = asyncio.get_running_loop()
    node_a = Node("node-a", "127.0.0.1", 0)
    node_b = Node("node-b", "127.0.0.1", 0, cpu_load=11.0)
    transport_a, network_a = await loop.create_datagram_endpoint(lambda: NetworkProtocol(node_a), local_addr=(node_a.host, 0))
    transport_b, network_b = await loop.create_datagram_endpoint(lambda: NetworkProtocol(node_b), local_addr=(node_b.host, 0))
    try:
        response = await network_a.send_task_route_request(
            ("127.0.0.1", transport_b.get_extra_info("sockname")[1]), "task-001", ["node-a", "node-b"], timeout=3
        )
        assert response["type"] == ROUTE_CANDIDATE_RESPONSE
        assert response["sender_id"] == "node-b"
        assert response["payload"]["candidate_node"] == "node-b"
        assert response["payload"]["task_id"] == "task-001"
    finally:
        transport_a.close(); transport_b.close(); await asyncio.sleep(0.05)


def test_two_node_task_routing():
    asyncio.run(run_two_node_task_routing())


def test_routing_timeout():
    async def run():
        loop = asyncio.get_running_loop()
        node = Node("node-a", "127.0.0.1", 0)
        transport, network = await loop.create_datagram_endpoint(lambda: NetworkProtocol(node), local_addr=(node.host, 0))
        try:
            try:
                await network.send_request("PING", ("127.0.0.1", 65500), timeout=0.05)
                assert False
            except TimeoutError:
                assert not network.pending_requests
        finally:
            transport.close(); await asyncio.sleep(0.02)
    asyncio.run(run())
