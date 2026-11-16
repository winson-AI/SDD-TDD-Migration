"""WebDriverAgent input operations. Propagate failures to the current step."""


def type_text(client, text):
    client.send_keys(text)


def clear_text(client):
    # WDA has no global clear endpoint. This is the upstream bounded backspace gesture.
    client.send_keys(["\b"] * 60)
