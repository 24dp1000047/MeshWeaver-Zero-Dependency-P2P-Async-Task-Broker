"""
Central registry of all tasks a node knows about, keyed by task_id.

This is what lets any part of the system answer "what's the current
state of task X" and is where failure detection and re-routing will
look to find tasks that need attention.
"""

from .task_state import TaskState


class TaskRegistry:
    def __init__(self):
        self._tasks = {}  # task_id -> TaskRecord

    def add(self, task_record):
        """Register a new task."""
        self._tasks[task_record.task_id] = task_record

    def get(self, task_id):
        """Look up a task by ID. Returns None if not found."""
        return self._tasks.get(task_id)

    def remove(self, task_id):
        """Remove a task from the registry (e.g. after it's fully done)."""
        self._tasks.pop(task_id, None)

    def all_tasks(self):
        """Return all tracked tasks."""
        return list(self._tasks.values())

    def tasks_in_state(self, state):
        """Return all tasks currently in a given TaskState."""
        return [t for t in self._tasks.values() if t.state == state]

    def running_tasks_on(self, node):
        """Return all tasks currently running on a specific node.

        Used when a node is detected as dead, to find every task that
        needs to be failed and re-routed.
        """
        return [t for t in self._tasks.values() if t.is_running_on(node)]

    def __len__(self):
        return len(self._tasks)