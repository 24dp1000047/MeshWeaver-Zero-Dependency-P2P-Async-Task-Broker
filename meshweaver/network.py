import asyncio

from .protocol import create_message, encode_message, decode_message


class NetworkProtocol(asyncio.DatagramProtocol):

    def __init__(self, node):
        self.node = node
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

        print(
            f"{self.node.node_id} started on "
            f"{self.node.host}:{self.node.port}"
        )

    def datagram_received(self, data, addr):
        message = decode_message(data)

        print(
            f"{self.node.node_id} received "
            f"{message} from {addr}"
        )

        if message["type"] == "PING":
            self.handle_ping(message, addr)

    def handle_ping(self, message, addr):
        response = create_message(
            "PONG",
            self.node.node_id
        )

        self.transport.sendto(
            encode_message(response),
            addr
        )

        print(f"{self.node.node_id} sent PONG to {addr}")

    def error_received(self, exc):
        print(f"Network error: {exc}")

    def connection_lost(self, exc):
        print("Connection closed")