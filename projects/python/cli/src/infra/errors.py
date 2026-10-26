"""infra/errors: typed exception hierarchy — all domain exceptions inherit from CoreError."""


##### ROOT #####
class CoreError(Exception):
    """All e-core exceptions inherit from this root."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
