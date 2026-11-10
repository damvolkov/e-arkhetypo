"""tests/support/logs: the recorder a test swaps in for the access log's logger."""


class RequestLogs:
    """The `request` events the access log writes, fields only — what a test asserts a request was logged with."""

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def info(self, event: str, **fields: object) -> None:
        _ = event == "request" and self.requests.append(fields)
