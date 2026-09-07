"""Provider execution boundary; scheduler code only speaks this protocol."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from voice_ingest.providers.base import PollResult
from voice_ingest.synthesis.contracts import Voice
from voice_ingest.transcription.contracts import ModelCapability


@dataclass
class SpeechRequest:
    kind: str
    options: dict[str, Any]
    input: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    duration_ms: int = 0


@dataclass
class Accepted:
    task_id: str
    raw: dict[str, Any]


@dataclass
class Completed:
    raw: dict[str, Any]
    audio: bytes | None = field(default=None, repr=False)


class SpeechAdapter(Protocol):
    name: str

    def models(self) -> list[ModelCapability]: ...
    def voices(self, model: str) -> list[Voice]: ...
    def validate(
        self, request: SpeechRequest, *, size: int | None = None, format_name: str | None = None
    ) -> None: ...
    async def start(self, request: SpeechRequest) -> Accepted | Completed: ...
    async def poll(self, task_id: str) -> PollResult: ...
    async def fetch(self, reference: str) -> Completed: ...
    async def cancel(self, task_id: str) -> bool: ...
    def normalize(
        self, raw: dict[str, Any], request: SpeechRequest, context: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def close(self) -> None: ...
