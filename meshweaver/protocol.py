import json
import base64


def create_message(message_type, sender_id, payload=None):
    """
    Build a message dict.

    Args:
        message_type: e.g. "PING", "PONG", "TASK", "TASK_RESULT"
        sender_id: ID of the node sending this message.
        payload: Optional extra data for the message (dict).
    """
    message = {
        "type": message_type,
        "sender_id": sender_id,
    }
    if payload is not None:
        message["payload"] = payload
    return message


def encode_message(message):
    return json.dumps(message).encode("utf-8")


def decode_message(data):
    return json.loads(data.decode("utf-8"))


def create_task_message(sender_id, task_blob):
    """
    Build a TASK message carrying a cloudpickle-serialized task.

    task_blob is raw bytes from serializer.serialize_task() — since JSON
    can't hold raw bytes, we base64-encode it into a string first.
    """
    encoded_blob = base64.b64encode(task_blob).decode("ascii")
    return create_message("TASK", sender_id, payload={"blob": encoded_blob})


def extract_task_blob(message):
    """
    Pull the raw cloudpickle bytes back out of a decoded TASK message.
    """
    encoded_blob = message["payload"]["blob"]
    return base64.b64decode(encoded_blob)