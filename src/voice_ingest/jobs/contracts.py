"""Shared, transport-independent contracts; safe in SDK-only installations."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class JobState(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    SUBMITTING = "submitting"
    RUNNING = "running"
    FINALIZING = "finalizing"
    NEEDS_ATTENTION = "needs_attention"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


TERMINAL = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.NEEDS_ATTENTION}
ACTIVE = {state.value for state in JobState} - {state.value for state in TERMINAL}


class ErrorInfo(Contract):
    code: str
    message: str
    retryable: bool = False
    request_id: str | None = None


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        super().__init__(message)
        self.info = ErrorInfo(code=code, message=message, retryable=retryable)
        self.status = status
        self.raw: dict[str, Any] | None = None
