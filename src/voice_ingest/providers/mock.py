"""Deterministic, restart-safe fake provider. Output is explicitly synthetic."""

from typing import Any
from uuid import uuid4

from voice_ingest.providers.base import PollResult
from voice_ingest.transcription.contracts import TranscriptionOptions


class MockProvider:
    name = "mock"

    async def submit(self, url: str, options: TranscriptionOptions, duration_ms: int) -> str:
        return f"mock-{duration_ms}-{int(options.diarization)}-{uuid4().hex}"

    async def poll(self, task_id: str) -> PollResult:
        return PollResult("succeeded", result_url=task_id)

    async def fetch(self, url: str) -> dict[str, Any]:
        _, duration, diarization, _ = url.split("-")
        total = int(duration)
        sentences = []
        for index, start in enumerate(sorted({0, total // 2, max(0, total - 1000)})):
            sentence: dict[str, Any] = {
                "begin_time": start,
                "end_time": min(total, start + 1000),
                "text": f"[MOCK] Synthetic segment {index + 1}; not speech recognition.",
            }
            if diarization == "1":
                sentence["speaker_id"] = index % 2
            sentences.append(sentence)
        return {
            "transcripts": [
                {
                    "channel_id": 0,
                    "text": "\n".join(s["text"] for s in sentences),
                    "sentences": sentences,
                }
            ],
            "mock": True,
        }

    async def cancel(self, task_id: str) -> bool:
        return True

    async def close(self):
        pass
