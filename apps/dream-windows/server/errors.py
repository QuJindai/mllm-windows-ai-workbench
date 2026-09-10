from __future__ import annotations

from typing import Any


class DreamApiError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 503, retryable: bool = False, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.detail = detail or {}
