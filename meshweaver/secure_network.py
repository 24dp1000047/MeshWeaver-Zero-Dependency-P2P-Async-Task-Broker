import asyncio
import ssl
from typing import Optional, Tuple


class SecureNetworkProtocol:
    """Length-prefixed JSON-over-TLS peer transport."""
    def __init__(self, node_id: str, on_message=None):
        self.node_id = node_id
        self.on_message = on_message
        self.reader = None
        self.writer = None

    async def connect(self, host: str, port: int, ssl_context: ssl.SSLContext):
        self.reader, self.writer = await asyncio.open_connection(host, port, ssl=ssl_context)
        return self

    async def send(self, data: bytes):
        if not self.writer:
            raise ConnectionError("TLS connection is not established")
        self.writer.write(len(data).to_bytes(4, "big") + data)
        await self.writer.drain()

    async def receive(self) -> bytes:
        if not self.reader:
            raise ConnectionError("TLS connection is not established")
        raw_len = await self.reader.readexactly(4)
        size = int.from_bytes(raw_len, "big")
        if size > 10 * 1024 * 1024:
            raise ValueError("message too large")
        return await self.reader.readexactly(size)

    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None


def create_server_context(certfile: str, keyfile: str, cafile: Optional[str] = None,
                          require_client_cert: bool = False) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    if cafile:
        context.load_verify_locations(cafile=cafile)
    if require_client_cert:
        context.verify_mode = ssl.CERT_REQUIRED
    return context


def create_client_context(cafile: Optional[str] = None, certfile: Optional[str] = None,
                          keyfile: Optional[str] = None, verify: bool = True) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cafile)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if certfile and keyfile:
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context


async def start_tls_server(host: str, port: int, ssl_context: ssl.SSLContext, client_connected_cb):
    return await asyncio.start_server(client_connected_cb, host, port, ssl=ssl_context)
