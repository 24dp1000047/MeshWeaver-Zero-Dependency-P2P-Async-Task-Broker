import asyncio
import inspect
import pickle
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


PENDING = "PENDING"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
RETRY = "RETRY"


@dataclass
class TaskRecord:
    task_id: str
    state: str = PENDING
    executing_node: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0


class TaskManager:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.tasks: Dict[str, TaskRecord] = {}
        self.accepted_results = set()
        self.registry: Dict[str, Callable] = {}

    def register(self, name: str, fn: Callable) -> None:
        if not callable(fn):
            raise TypeError("fn must be callable")
        self.registry[name] = fn

    def create(self, fn_name: str, args=(), kwargs=None, task_id=None) -> Dict[str, Any]:
        if fn_name not in self.registry:
            raise KeyError(f"Unknown task function: {fn_name}")
        task_id = task_id or str(uuid.uuid4())
        self.tasks[task_id] = TaskRecord(task_id)
        return {"task_id": task_id, "fn_name": fn_name, "args": list(args), "kwargs": kwargs or {}}

    def validate_signed_task(self, message: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
        from meshweaver.protocol import verify_message_signature
        if not verify_message_signature(message, secret):
            raise PermissionError("invalid or missing task signature")
        payload = message.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("task_id"), str) or not payload.get("task_id"):
            raise ValueError("invalid task metadata")
        return payload

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task.get("task_id")
        fn_name = task.get("fn_name")
        if not isinstance(task_id, str) or not task_id or fn_name not in self.registry:
            raise ValueError("invalid task")
        record = self.tasks.setdefault(task_id, TaskRecord(task_id))
        record.state = RUNNING
        record.executing_node = self.node_id
        record.attempts += 1
        try:
            fn = self.registry[fn_name]
            result = fn(*task.get("args", []), **task.get("kwargs", {}))
            if inspect.isawaitable(result):
                result = await result
            record.result = result
            record.state = COMPLETED
            return {"task_id": task_id, "result": result, "node_id": self.node_id}
        except Exception as exc:
            record.state = FAILED
            record.error = f"{type(exc).__name__}: {exc}"
            return {"task_id": task_id, "error": record.error, "node_id": self.node_id}

    def accept_result(self, task_id: str, result: Any) -> bool:
        if task_id in self.accepted_results:
            return False
        self.accepted_results.add(task_id)
        return True

    def mark_for_retry(self, task_id: str) -> None:
        record = self.tasks.setdefault(task_id, TaskRecord(task_id))
        record.state = RETRY
        record.executing_node = None

    @staticmethod
    def serialize(task: Dict[str, Any]) -> bytes:
        return pickle.dumps(task, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def deserialize(data: bytes) -> Dict[str, Any]:
        task = pickle.loads(data)
        if not isinstance(task, dict):
            raise ValueError("malformed task payload")
        return task
