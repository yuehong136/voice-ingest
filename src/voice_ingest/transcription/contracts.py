"""Transcription input/output contracts, independent of synthesis and transport."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from voice_ingest.jobs.contracts import (
    ACTIVE as ACTIVE,
)
from voice_ingest.jobs.contracts import (
    TERMINAL as TERMINAL,
)
from voice_ingest.jobs.contracts import (
    Contract as Contract,
)
from voice_ingest.jobs.contracts import (
    DomainError as DomainError,
)
from voice_ingest.jobs.contracts import (
    ErrorInfo as ErrorInfo,
)
from voice_ingest.jobs.contracts import (
    JobState as JobState,
)

ExportFormat = Literal["json", "txt", "markdown", "srt", "vtt"]


class TranscriptionOptions(Contract):
    model: str = "qwen-audio-3.0-asr-flash-filetrans"
    deployment_id: str | None = None
    routing: Literal["any", "local_only"] = "any"
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
    kind: Literal["transcription", "synthesis"] = "transcription"
    deployment_id: str = "default"
    deployment_revision: str = "1"
    location: Literal["cloud", "local", "test"] = "cloud"
    execution: Literal["remote_task", "direct", "audio_stream"] = "remote_task"
    formats: list[str] = Field(default_factory=list)
    sample_rates: list[int] = Field(default_factory=list)
    max_text_characters: int | None = None
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
    kind: Literal["transcription"] = "transcription"
    deployment_id: str = "default"
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
