import asyncio

from meshweaver.protocol import (
    create_message,
    create_request,
    encode_message,
    decode_message,
)


class NetworkProtocol(asyncio.DatagramProtocol):

    def __init__(self, node):
        self.node = node
        self.transport = None
        self.pending_requests = {}

    def connection_made(self, transport):
        self.transport = transport

        print(
            f"{self.node.node_id} started on "
            f"{self.node.host}:{self.node.port}"
        )

    def datagram_received(self, data, addr):
        try:
            message = decode_message(data)
        except Exception as exc:
            print(f"Invalid message received: {exc}")
            return

        print(
            f"{self.node.node_id} received "
            f"{message} from {addr}"
        )

        request_id = message.get("request_id")

        # Check if this is a response to one of our requests
        if request_id in self.pending_requests:
            future = self.pending_requests.pop(request_id)

            if not future.done():
                future.set_result(message)

            return

        # Otherwise, dispatch the incoming message
        self.dispatch_message(message, addr)

    def dispatch_message(self, message, addr):
        message_type = message.get("type")

        if message_type == "PING":
            self.handle_ping(message, addr)

        elif message_type == "PONG":
            self.handle_pong(message, addr)

        else:
            print(
                f"{self.node.node_id}: "
                f"Unknown message type: {message_type}"
            )

    def handle_ping(self, message, addr):
        response = create_message(
            "PONG",
            self.node.node_id,
            message.get("request_id")
        )

        self.transport.sendto(
            encode_message(response),
            addr
        )

        print(
            f"{self.node.node_id} sent PONG to {addr}"
        )

    def handle_pong(self, message, addr):
        print(
            f"{self.node.node_id} received PONG from {addr}"
        )

    async def send_request(
        self,
        message_type,
        address,
        timeout=3
    ):
        request = create_request(
            message_type,
            self.node.node_id
        )

        request_id = request["request_id"]

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self.pending_requests[request_id] = future

        self.transport.sendto(
            encode_message(request),
            address
        )

        print(
            f"{self.node.node_id} sent "
            f"{message_type} to {address} "
            f"(request_id={request_id})"
        )

        try:
            response = await asyncio.wait_for(
                future,
                timeout=timeout
            )

            return response

        except asyncio.TimeoutError:
            self.pending_requests.pop(
                request_id,
                None
            )

            raise TimeoutError(
                f"Request {request_id} timed out"
            )

    def error_received(self, exc):
        print(f"Network error: {exc}")

    def connection_lost(self, exc):
        print("Connection closed")

        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(
                    ConnectionError(
                        "Network connection lost"
                    )
                )

        self.pending_requests.clear()