"""
TCP transport for sending and executing tasks between nodes.
"""

import asyncio
import struct

from .protocol import create_task_message, extract_task_blob, encode_message, decode_message
from .serializer import deserialize_task, execute_task


async def send_task(host, port, sender_id, task_blob):
    reader, writer = await asyncio.open_connection(host, port)

    message = create_task_message(sender_id, task_blob)
    data = encode_message(message)

    writer.write(struct.pack(">I", len(data)))
    writer.write(data)
    await writer.drain()

    result_length_bytes = await reader.readexactly(4)
    result_length = struct.unpack(">I", result_length_bytes)[0]
    result_data = await reader.readexactly(result_length)
    result_message = decode_message(result_data)

    writer.close()
    await writer.wait_closed()

    return result_message["payload"]["result"]


async def handle_task_connection(reader, writer, node_id):
    length_bytes = await reader.readexactly(4)
    length = struct.unpack(">I", length_bytes)[0]
    data = await reader.readexactly(length)

    message = decode_message(data)
    task_blob = extract_task_blob(message)
    task = deserialize_task(task_blob)

    try:
        result = execute_task(task)
        response = {"type": "TASK_RESULT", "sender_id": node_id, "payload": {"result": result}}
    except Exception as e:
        response = {"type": "TASK_ERROR", "sender_id": node_id, "payload": {"error": str(e)}}

    response_data = encode_message(response)
    writer.write(struct.pack(">I", len(response_data)))
    writer.write(response_data)
    await writer.drain()

    writer.close()
    await writer.wait_closed()


async def start_task_server(host, port, node_id):
    async def handler(reader, writer):
        await handle_task_connection(reader, writer, node_id)

    server = await asyncio.start_server(handler, host, port)
    return server