"""
Configuration for task execution timing.

TASK_TIMEOUT_SECONDS controls how long we wait for a result before
deciding the executing node has died and the task needs to be retried
elsewhere.
"""

TASK_TIMEOUT_SECONDS = 10.0

MAX_RETRY_ATTEMPTS = 3