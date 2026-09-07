from dataclasses import dataclass
from typing import Any, Literal, Protocol

from voice_ingest.transcription.contracts import (
    DomainError,
    TranscriptionOptions,
)


class SubmissionUnknown(DomainError):
    def __init__(self):
        super().__init__(
            "submission_unknown",
            "Provider may have accepted this request; review before resubmitting",
            409,
        )


@dataclass
class PollResult:
    state: Literal["pending", "succeeded", "failed", "cancelled"]
    result_url: str | None = None
    error_code: str | None = None
    raw: dict[str, Any] | None = None


class ASRProvider(Protocol):
    name: str

    async def submit(self, url: str, options: TranscriptionOptions, duration_ms: int) -> str: ...
    async def poll(self, task_id: str) -> PollResult: ...
    async def fetch(self, url: str) -> dict[str, Any]: ...
    async def cancel(self, task_id: str) -> bool: ...
    async def close(self) -> None: ...
