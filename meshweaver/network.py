import asyncio
import time
from typing import Dict, Optional, Tuple

from meshweaver.protocol import (
    create_message, create_request, encode_message, decode_message,
    TASK_ROUTE_REQUEST, ROUTE_CANDIDATE_RESPONSE, ROUTE_DECISION,
    HEARTBEAT, HEARTBEAT_ACK, PING, PONG,
)


class NetworkProtocol(asyncio.DatagramProtocol):
    """Async UDP control-plane protocol with correlated requests and heartbeats."""

    def __init__(self, node, on_message=None, on_node_seen=None):
        self.node = node
        self.transport = None
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.on_message = on_message
        self.on_node_seen = on_node_seen
        self.last_seen: Dict[str, float] = {}

    def connection_made(self, transport):
        self.transport = transport
        address = transport.get_extra_info("sockname")
        if address:
            self.node.port = address[1]
        print(f"{self.node.node_id} started on {self.node.host}:{self.node.port}")

    def datagram_received(self, data, addr):
        try:
            message = decode_message(data)
        except Exception as exc:
            print(f"Invalid message received from {addr}: {exc}")
            return

        sender_id = message.get("sender_id")
        if sender_id:
            self.last_seen[sender_id] = time.time()
            if self.on_node_seen:
                self.on_node_seen(message, addr)

        request_id = message.get("request_id")
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests.pop(request_id)
            if not future.done():
                future.set_result(message)
            return
        self.dispatch_message(message, addr)

    def dispatch_message(self, message, addr):
        handlers = {
            PING: self.handle_ping,
            PONG: self.handle_pong,
            TASK_ROUTE_REQUEST: self.handle_task_route_request,
            ROUTE_CANDIDATE_RESPONSE: self.handle_route_candidate_response,
            ROUTE_DECISION: self.handle_route_decision,
            HEARTBEAT: self.handle_heartbeat,
            HEARTBEAT_ACK: self.handle_heartbeat_ack,
        }
        handler = handlers.get(message.get("type"))
        if handler:
            handler(message, addr)
        elif self.on_message:
            self.on_message(message, addr)
        else:
            print(f"{self.node.node_id}: Unknown message type: {message.get('type')}")

    def _send(self, message, address):
        if not self.transport:
            raise ConnectionError("UDP transport is not connected")
        self.transport.sendto(encode_message(message), address)

    def handle_ping(self, message, addr):
        self._send(create_message(PONG, self.node.node_id, message.get("request_id")), addr)

    def handle_pong(self, message, addr):
        return None

    def handle_heartbeat(self, message, addr):
        payload = message.get("payload", {})
        self.node.touch(payload.get("cpu_load"), payload.get("ram_percent"))
        self._send(create_message(HEARTBEAT_ACK, self.node.node_id, message.get("request_id"), {
            "timestamp": time.time(), "cpu_load": self.node.cpu_load, "ram_percent": self.node.ram_percent,
        }), addr)

    def handle_heartbeat_ack(self, message, addr):
        return None

    def handle_task_route_request(self, message, addr):
        payload = message.get("payload", {})
        task_id = payload.get("task_id")
        if not task_id or not payload.get("source_node"):
            return
        response = create_message(ROUTE_CANDIDATE_RESPONSE, self.node.node_id,
                                  request_id=message.get("request_id"), payload={
            "task_id": task_id,
            "source_node": payload.get("source_node"),
            "candidate_node": self.node.node_id,
            "cpu_load": self.node.cpu_load if payload.get("cpu_load") is None else payload.get("cpu_load"),
            "timestamp": time.time(),
        })
        self._send(response, addr)

    def handle_route_candidate_response(self, message, addr):
        if self.on_message:
            self.on_message(message, addr)

    def handle_route_decision(self, message, addr):
        if self.on_message:
            self.on_message(message, addr)

    async def send_request(self, message_type: str, address: Tuple[str, int], payload=None, timeout: float = 3.0,
                           signed_by=None):
        request = create_request(message_type, self.node.node_id, payload)
        if signed_by is not None:
            request = signed_by.sign(request)
        request_id = request["request_id"]
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_requests[request_id] = future
        try:
            self._send(request, address)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self.pending_requests.pop(request_id, None)
            raise TimeoutError(f"Request {request_id} timed out") from exc
        except BaseException:
            self.pending_requests.pop(request_id, None)
            raise

    async def heartbeat_loop(self, addresses, interval=1.0, timeout=1.5):
        """Periodically probe peers and yield state updates to the caller."""
        while True:
            results = {}
            for address in addresses:
                try:
                    response = await self.heartbeat(address, timeout=timeout)
                    results[address] = response
                except (TimeoutError, ConnectionError, OSError):
                    results[address] = None
            yield results
            await asyncio.sleep(interval)

    async def heartbeat(self, address, timeout=1.5):
        return await self.send_request(HEARTBEAT, address, {
            "timestamp": time.time(), "cpu_load": self.node.cpu_load, "ram_percent": self.node.ram_percent,
        }, timeout=timeout)

    async def send_task_route_request(self, address, task_id, candidates=None, timeout=3.0, signed_by=None):
        payload = {
            "task_id": task_id,
            "source_node": self.node.node_id,
            "candidate_node": None,
            "cpu_load": None,
            "candidates": list(candidates or []),
            "timestamp": time.time(),
        }
        return await self.send_request(TASK_ROUTE_REQUEST, address, payload, timeout, signed_by=signed_by)

    def connection_lost(self, exc):
        error = ConnectionError("Network connection lost")
        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(error)
        self.pending_requests.clear()
        self.transport = None
