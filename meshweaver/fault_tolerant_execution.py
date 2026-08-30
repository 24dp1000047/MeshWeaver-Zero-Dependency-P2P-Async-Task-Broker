"""
Wraps task sending with timeout-based failure detection.

If a node doesn't respond within TASK_TIMEOUT_SECONDS, we treat it as
dead: the task is marked FAILED so the caller can select a new node
and retry, instead of hanging forever waiting on a node that's gone.
"""

import asyncio

from .task_transport import send_task
from .task_config import TASK_TIMEOUT_SECONDS


async def execute_with_timeout(task_record):
    """
    Send task_record's task to its currently assigned node and wait for
    a result, but give up after TASK_TIMEOUT_SECONDS.

    On success: marks the task COMPLETED and returns the result.
    On timeout or connection error: marks the task FAILED and returns None.

    task_record.assigned_node must already be set (call
    task_record.mark_running(node) before calling this).
    """
    host, port = task_record.assigned_node

    try:
        result = await asyncio.wait_for(
            send_task(host, port, "sender-node", task_record.task_blob),
            timeout=TASK_TIMEOUT_SECONDS,
        )
        task_record.mark_completed(result)
        return result

    except asyncio.TimeoutError:
        task_record.mark_failed(f"timed out after {TASK_TIMEOUT_SECONDS}s waiting for {host}:{port}")
        return None

    except (ConnectionRefusedError, ConnectionResetError, OSError) as e:
        task_record.mark_failed(f"connection error to {host}:{port}: {e}")
        return None