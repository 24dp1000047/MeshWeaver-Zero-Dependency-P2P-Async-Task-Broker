import json
import uuid


def create_message(message_type, sender_id, request_id=None):
    message = {
        "type": message_type,
        "sender_id": sender_id
    }

    if request_id is not None:
        message["request_id"] = request_id

    return message


def create_request(message_type, sender_id):
    request_id = str(uuid.uuid4())

    return create_message(
        message_type,
        sender_id,
        request_id
    )


def encode_message(message):
    return json.dumps(message).encode("utf-8")


def decode_message(data):
    return json.loads(data.decode("utf-8"))