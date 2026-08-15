"""
Task Serializer for MeshWeaver.

Uses cloudpickle to package a Python function (and its arguments) into
bytes so it can be sent over the network to a peer node and executed
remotely.

Regular pickle can't serialize things like lambdas or functions defined
inside another function. cloudpickle can, which matters here because
tasks submitted to the mesh could be any arbitrary function a user writes.
"""

import cloudpickle


def serialize_task(func, args=None, kwargs=None):
    task = {
        "func": func,
        "args": args or (),
        "kwargs": kwargs or {},
    }
    return cloudpickle.dumps(task)


def deserialize_task(blob):
    task = cloudpickle.loads(blob)
    return task


def execute_task(task):
    func = task["func"]
    args = task["args"]
    kwargs = task["kwargs"]
    return func(*args, **kwargs)
