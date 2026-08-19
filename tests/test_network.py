import asyncio

from meshweaver.node import Node
from meshweaver.network import NetworkProtocol


def test_ping_pong():
    asyncio.run(run_ping_pong())


async def run_ping_pong():
    loop = asyncio.get_running_loop()

    node1 = Node("node-1", "127.0.0.1", 9001)
    node2 = Node("node-2", "127.0.0.1", 9002)

    transport1, protocol1 = await loop.create_datagram_endpoint(
        lambda: NetworkProtocol(node1),
        local_addr=(node1.host, node1.port)
    )

    transport2, protocol2 = await loop.create_datagram_endpoint(
        lambda: NetworkProtocol(node2),
        local_addr=(node2.host, node2.port)
    )

    try:
        response = await protocol1.send_request(
            "PING",
            (node2.host, node2.port),
            timeout=3
        )

        assert response["type"] == "PONG"
        assert response["request_id"] is not None

    finally:
        transport1.close()
        transport2.close()