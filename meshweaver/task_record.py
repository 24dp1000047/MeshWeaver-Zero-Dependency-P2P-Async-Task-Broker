"""
Tracks the lifecycle of a single task as it moves through the mesh.

A TaskRecord holds everything needed to know what a task is doing right
now, and everything needed to retry it on a different node if the one
running it dies.
"""

import time
import uuid

from .task_state import TaskState


class TaskRecord:
    def __init__(self, task_blob):
        """
        Args:
            task_blob: the cloudpickle-serialized task bytes
                       (from serializer.serialize_task()).
        """
        self.task_id = str(uuid.uuid4())
        self.task_blob = task_blob
        self.state = TaskState.PENDING
        self.assigned_node = None      # (host, port) currently running this task
        self.attempt = 0                # how many times we've tried to run this
        self.created_at = time.time()
        self.started_at = None          # when current attempt started running
        self.result = None
        self.error = None

    def mark_running(self, node):
        """Mark this task as sent to a node and now executing."""
        self.state = TaskState.RUNNING
        self.assigned_node = node
        self.attempt += 1
        self.started_at = time.time()

    def mark_completed(self, result):
        """Mark this task as successfully finished."""
        self.state = TaskState.COMPLETED
        self.result = result

    def mark_failed(self, error=None):
        """Mark this task as failed (node died, timed out, or errored)."""
        self.state = TaskState.FAILED
        self.error = error

    def reset_for_retry(self):
        """Move a FAILED task back to PENDING so it can be re-submitted."""
        self.state = TaskState.PENDING
        self.assigned_node = None
        self.started_at = None

    def is_running_on(self, node):
        """Check if this task is currently assigned to the given node."""
        return self.state == TaskState.RUNNING and self.assigned_node == node

    def __repr__(self):
        return f"TaskRecord(id={self.task_id[:8]}, state={self.state.value}, attempt={self.attempt}, node={self.assigned_node})"