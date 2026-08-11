import json


def create_message(message_type, sender_id):
    return {
        "type": message_type,
        "sender_id": sender_id
    }


def encode_message(message):
    return json.dumps(message).encode("utf-8")



def decode_message(data):
    return json.loads(data.decode("utf-8"))