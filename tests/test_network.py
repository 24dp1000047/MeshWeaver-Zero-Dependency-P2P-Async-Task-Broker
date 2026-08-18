import asyncio

from meshweaver.node import Node
from meshweaver.network import NetworkProtocol
from meshweaver.protocol import create_message, encode_message


async def main():
    loop = asyncio.get_running_loop()

    node1 = Node("node-1", "127.0.0.1", 9001)
    node2 = Node("node-2", "127.0.0.1", 9002)

    transport1, _ = await loop.create_datagram_endpoint(
        lambda: NetworkProtocol(node1),
        local_addr=(node1.host, node1.port)
    )

    transport2, _ = await loop.create_datagram_endpoint(
        lambda: NetworkProtocol(node2),
        local_addr=(node2.host, node2.port)
    )

    message = create_message(
        "PING",
        node1.node_id
    )

    transport1.sendto(
        encode_message(message),
        (node2.host, node2.port)
    )

    await asyncio.sleep(1)

    transport1.close()
    transport2.close()


asyncio.run(main())