import asyncio

from meshweaver.protocol import (
    create_message,
    create_request,
    encode_message,
    decode_message,
    TASK_ROUTE_REQUEST,
    ROUTE_CANDIDATE_RESPONSE,
    ROUTE_DECISION,
)


class NetworkProtocol(asyncio.DatagramProtocol):

    def __init__(self, node):
        self.node = node
        self.transport = None
        self.pending_requests = {}

    # =====================================================
    # CONNECTION
    # =====================================================

    def connection_made(self, transport):
        self.transport = transport

        print(
            f"{self.node.node_id} started on "
            f"{self.node.host}:{self.node.port}"
        )

    # =====================================================
    # INCOMING DATAGRAM
    # =====================================================

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

        # -------------------------------------------------
        # Check whether this message is a response to one
        # of our pending requests.
        # -------------------------------------------------

        if request_id in self.pending_requests:

            future = self.pending_requests.pop(request_id)

            if not future.done():
                future.set_result(message)

            return

        # -------------------------------------------------
        # Otherwise, handle it as a new incoming message.
        # -------------------------------------------------

        self.dispatch_message(message, addr)

    # =====================================================
    # MESSAGE DISPATCH
    # =====================================================

    def dispatch_message(self, message, addr):
        message_type = message.get("type")

        if message_type == "PING":
            self.handle_ping(message, addr)

        elif message_type == "PONG":
            self.handle_pong(message, addr)

        elif message_type == TASK_ROUTE_REQUEST:
            self.handle_task_route_request(message, addr)

        elif message_type == ROUTE_CANDIDATE_RESPONSE:
            self.handle_route_candidate_response(message, addr)

        elif message_type == ROUTE_DECISION:
            self.handle_route_decision(message, addr)

        else:
            print(
                f"{self.node.node_id}: "
                f"Unknown message type: {message_type}"
            )

    # =====================================================
    # PING / PONG
    # =====================================================

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

    # =====================================================
    # TASK ROUTING REQUEST
    # =====================================================

    def handle_task_route_request(self, message, addr):
        """
        Handle an incoming TASK_ROUTE_REQUEST.

        The routing metadata is extracted from the request
        and returned to the requesting node in a
        ROUTE_CANDIDATE_RESPONSE.

        The same request_id is preserved so that the sender
        can correlate the response with its original request.
        """

        payload = message.get("payload", {})

        task_id = payload.get("task_id")
        source_node = payload.get("source_node")
        candidate_node = payload.get("candidate_node")
        cpu_load = payload.get("cpu_load")
        timestamp = payload.get("timestamp")

        request_id = message.get("request_id")

        print(
            f"{self.node.node_id} received "
            f"TASK_ROUTE_REQUEST:"
        )

        print(f"  task_id: {task_id}")
        print(f"  source_node: {source_node}")
        print(f"  candidate_node: {candidate_node}")
        print(f"  cpu_load: {cpu_load}")
        print(f"  timestamp: {timestamp}")
        print(f"  request_id: {request_id}")

        # -------------------------------------------------
        # Create candidate-node response.
        # -------------------------------------------------

        response = create_message(
            ROUTE_CANDIDATE_RESPONSE,
            self.node.node_id,
            request_id=request_id,
            payload={
                "task_id": task_id,
                "source_node": source_node,
                "candidate_node": candidate_node,
                "cpu_load": cpu_load,
                "timestamp": timestamp,
            }
        )

        # -------------------------------------------------
        # Send response back to requesting node.
        # -------------------------------------------------

        self.transport.sendto(
            encode_message(response),
            addr
        )

        print(
            f"{self.node.node_id} sent "
            f"ROUTE_CANDIDATE_RESPONSE to {addr} "
            f"(request_id={request_id})"
        )

    # =====================================================
    # ROUTE CANDIDATE RESPONSE
    # =====================================================

    def handle_route_candidate_response(self, message, addr):
        """
        Handle a ROUTE_CANDIDATE_RESPONSE that does not
        correspond to a currently pending request.

        Normally, responses are handled automatically by
        datagram_received() through pending_requests.
        """

        payload = message.get("payload", {})

        print(
            f"{self.node.node_id} received "
            f"ROUTE_CANDIDATE_RESPONSE:"
        )

        print(
            f"  task_id: "
            f"{payload.get('task_id')}"
        )

        print(
            f"  candidate_node: "
            f"{payload.get('candidate_node')}"
        )

        print(
            f"  cpu_load: "
            f"{payload.get('cpu_load')}"
        )

        print(
            f"  request_id: "
            f"{message.get('request_id')}"
        )

    # =====================================================
    # ROUTE DECISION
    # =====================================================

    def handle_route_decision(self, message, addr):
        """
        Handle a routing decision message.
        """

        payload = message.get("payload", {})

        print(
            f"{self.node.node_id} received "
            f"ROUTE_DECISION:"
        )

        print(
            f"  task_id: "
            f"{payload.get('task_id')}"
        )

        print(
            f"  selected_node: "
            f"{payload.get('candidate_node')}"
        )

        print(
            f"  cpu_load: "
            f"{payload.get('cpu_load')}"
        )

        print(
            f"  request_id: "
            f"{message.get('request_id')}"
        )

    # =====================================================
    # GENERIC REQUEST / RESPONSE
    # =====================================================

    async def send_request(
        self,
        message_type,
        address,
        payload=None,
        timeout=3
    ):
        """
        Send a request and wait for its response.

        payload is optional so the existing Week 1–2
        request functionality remains compatible.

        Example:

            await network.send_request(
                TASK_ROUTE_REQUEST,
                address,
                payload={
                    "task_id": "task-001",
                    "source_node": "node-1",
                    "candidate_node": "node-2",
                    "cpu_load": 25.5,
                    "timestamp": 1234567890
                }
            )
        """

        request = create_request(
            message_type,
            self.node.node_id,
            payload
        )

        request_id = request["request_id"]

        loop = asyncio.get_running_loop()

        future = loop.create_future()

        self.pending_requests[request_id] = future

        # -------------------------------------------------
        # Send request
        # -------------------------------------------------

        self.transport.sendto(
            encode_message(request),
            address
        )

        print(
            f"{self.node.node_id} sent "
            f"{message_type} to {address} "
            f"(request_id={request_id})"
        )

        # -------------------------------------------------
        # Wait for response
        # -------------------------------------------------

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

    # =====================================================
    # NETWORK ERRORS
    # =====================================================

    def error_received(self, exc):
        print(
            f"Network error: {exc}"
        )

    # =====================================================
    # CONNECTION LOST
    # =====================================================

    def connection_lost(self, exc):
        print(
            "Connection closed"
        )

        for future in self.pending_requests.values():

            if not future.done():

                future.set_exception(
                    ConnectionError(
                        "Network connection lost"
                    )
                )

        self.pending_requests.clear()