"""Stable domain errors shared by REST and MCP adapters."""


class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def not_found() -> DomainError:
    return DomainError("not_found", "The requested record was not found.", 404)


def forbidden() -> DomainError:
    return DomainError("forbidden", "This action is not authorized.", 403)


def conflict(code: str = "invalid_state", message: str = "The proposal is no longer available for this action.") -> DomainError:
    return DomainError(code, message, 409)
