"""
Task lifecycle states for fault-tolerant execution.

A task moves through these states as it's submitted, executed, and
either completes or fails and gets retried elsewhere:

    PENDING -> RUNNING -> COMPLETED
                  |
                  v
               FAILED -> (retry) -> PENDING
"""

from enum import Enum


class TaskState(Enum):
    PENDING = "PENDING"      # created, not yet sent to a node
    RUNNING = "RUNNING"      # sent to a node, waiting for result
    COMPLETED = "COMPLETED"  # result received successfully
    FAILED = "FAILED"        # execution node died or timed out