"""Transport-independent public contracts, safe to import from the SDK."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
ExportFormat = Literal["json", "txt", "markdown", "srt", "vtt"]


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


class TranscriptionOptions(Contract):
    model: str = "qwen-audio-3.0-asr-flash-filetrans"
    language_hints: list[str] = Field(default_factory=list, max_length=4)
    diarization: bool = False
    speaker_count: int | None = Field(default=None, ge=2, le=100)
    context: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def validate_speakers(self):
        if self.speaker_count is not None and not self.diarization:
            raise ValueError("speaker_count requires diarization")
        return self


class CreateTranscription(Contract):
    asset_id: str
    options: TranscriptionOptions = Field(default_factory=TranscriptionOptions)


class ModelCapability(Contract):
    id: str
    provider: str
    max_bytes: int = 2_000_000_000
    max_duration_ms: int = 43_200_000
    max_diarization_ms: int = 7_200_000
    diarization: bool = True
    context: bool = False
    max_language_hints: int = 1


class Word(Contract):
    text: str
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class Segment(Word):
    speaker_id: str | None = None
    channel_id: int | None = None
    words: list[Word] = Field(default_factory=list)


class Transcript(Contract):
    schema_version: Literal["1"] = "1"
    job_id: str
    asset_id: str
    provider: str
    model: str
    language: str | None = None
    duration_ms: int
    text: str
    segments: list[Segment]
    warnings: list[str] = Field(default_factory=list)


class TranscriptPage(Contract):
    job_id: str
    segments: list[Segment]
    next_cursor: str | None = None
    warnings: list[str] = Field(default_factory=list)


class JobView(Contract):
    id: str
    asset_id: str
    state: JobState
    options: TranscriptionOptions
    created_at: datetime
    updated_at: datetime
    attempt: int
    error: ErrorInfo | None = None
    remote_may_run: bool = False


class JobPage(Contract):
    items: list[JobView]
    next_cursor: str | None = None


class RetryRequest(Contract):
    acknowledge_duplicate_risk: bool = False


class AssetView(Contract):
    id: str
    filename: str
    size: int
    duration_ms: int | None = None
    media_info: dict[str, Any] | None = None
