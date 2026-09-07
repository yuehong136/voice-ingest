"""Synthesis contracts contain no server or inference dependencies."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from voice_ingest.jobs.contracts import Contract, ErrorInfo, JobState


class SynthesisOptions(Contract):
    model: str = "qwen-audio-3.0-tts-flash"
    deployment_id: str | None = None
    routing: Literal["any", "local_only"] = "any"
    voice: str = "longanhuan_v3.6"
    format: Literal["mp3", "wav"] = "mp3"
    sample_rate: int = 22050


class CreateSynthesis(Contract):
    text: str = Field(min_length=1, max_length=20000, repr=False)
    options: SynthesisOptions = Field(default_factory=SynthesisOptions)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str):
        if not value.strip():
            raise ValueError("Text must not be blank")
        return value


class SynthesisJob(Contract):
    id: str
    kind: Literal["synthesis"] = "synthesis"
    state: JobState
    options: SynthesisOptions
    deployment_id: str
    created_at: datetime
    updated_at: datetime
    attempt: int
    error: ErrorInfo | None = None
    remote_may_run: bool = False


class SynthesisPage(Contract):
    items: list[SynthesisJob]
    next_cursor: str | None = None


class SynthesisResult(Contract):
    schema_version: Literal["1"] = "1"
    job_id: str
    provider: str
    model: str
    deployment_id: str
    deployment_revision: str
    voice: str
    format: Literal["mp3", "wav"]
    content_type: str
    size: int
    sha256: str
    duration_ms: int
    sample_rate: int
    request_id: str | None = None
    input_characters: int
    usage_source: Literal["measured_input"] = "measured_input"
    audio_path: str


class Voice(Contract):
    id: str
    name: str
    model: str
    deployment_id: str
