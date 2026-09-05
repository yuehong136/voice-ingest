from dataclasses import dataclass
from typing import Any, Literal, Protocol

from voice_ingest.transcription.contracts import (
    DomainError,
    ModelCapability,
    Transcript,
    TranscriptionOptions,
)

MODELS = [
    ModelCapability(
        id="qwen-audio-3.0-asr-flash-filetrans",
        provider="aliyun",
        context=True,
        max_language_hints=4,
    ),
    ModelCapability(id="fun-asr", provider="aliyun"),
]


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


class ASRProvider(Protocol):
    name: str

    async def submit(self, url: str, options: TranscriptionOptions, duration_ms: int) -> str: ...
    async def poll(self, task_id: str) -> PollResult: ...
    async def fetch(self, url: str) -> dict[str, Any]: ...
    async def cancel(self, task_id: str) -> bool: ...
    async def close(self) -> None: ...


def validate_options(
    options: TranscriptionOptions,
    duration_ms: int | None = None,
    size: int | None = None,
    format_name: str | None = None,
):
    model = next((m for m in MODELS if m.id == options.model), None)
    if not model:
        raise DomainError("unsupported_model", "Select a model returned by /v1/models")
    if options.context and not model.context:
        raise DomainError("unsupported_context", "This model does not accept context")
    if options.context and len(options.context) > 400:
        raise DomainError(
            "context_too_long", "Aliyun accepts at most 400 context characters per turn"
        )
    if len(options.language_hints) > model.max_language_hints:
        raise DomainError("unsupported_languages", "Too many language hints for this model")
    if duration_ms and duration_ms > model.max_duration_ms:
        raise DomainError("audio_too_long", "Audio exceeds the model's 12 hour limit")
    if options.diarization and duration_ms and duration_ms > model.max_diarization_ms:
        raise DomainError(
            "diarization_too_long", "Diarization is limited to two hours by this service"
        )
    if size and size > model.max_bytes:
        raise DomainError("audio_too_large", "Audio exceeds the model's 2 GB limit")
    supported = {
        "aac",
        "amr",
        "avi",
        "flac",
        "flv",
        "mov",
        "mp4",
        "m4a",
        "3gp",
        "3g2",
        "mj2",
        "matroska",
        "webm",
        "mp3",
        "mpeg",
        "mpegts",
        "ogg",
        "wav",
        "asf",
    }
    if format_name and not set(format_name.split(",")) & supported:
        raise DomainError("unsupported_format", "Audio container is not supported by this model")


def normalize(
    raw: dict[str, Any],
    *,
    job_id: str,
    asset_id: str,
    provider: str,
    options: TranscriptionOptions,
    duration_ms: int,
) -> Transcript:
    from voice_ingest.transcription.contracts import Segment, Word

    tracks = raw.get("transcripts")
    if not isinstance(tracks, list):
        raise DomainError("invalid_result", "Provider result has no transcripts array")
    segments = []
    warnings = []

    def timing(data: dict[str, Any]):
        start, end = data.get("begin_time"), data.get("end_time")
        valid = type(start) is int and type(end) is int and 0 <= start < end <= duration_ms + 1000
        if not valid:
            warnings.append("missing_or_invalid_timestamps")
            return None, None
        return start, end

    for track in tracks:
        sentences = track.get("sentences", [])
        if not sentences and track.get("text"):
            segments.append(Segment(text=track["text"], channel_id=track.get("channel_id")))
            warnings.append("missing_or_invalid_timestamps")
        for sentence in sentences:
            start, end = timing(sentence)
            words = []
            for word in sentence.get("words", []):
                ws, we = timing(word)
                words.append(
                    Word(
                        text=word.get("text", "") + word.get("punctuation", ""),
                        start_ms=ws,
                        end_ms=we,
                    )
                )
            speaker = sentence.get("speaker_id")
            segments.append(
                Segment(
                    text=sentence.get("text", ""),
                    start_ms=start,
                    end_ms=end,
                    speaker_id=str(speaker) if speaker is not None else None,
                    channel_id=track.get("channel_id"),
                    words=words,
                )
            )
    segments.sort(
        key=lambda segment: segment.start_ms if segment.start_ms is not None else float("inf")
    )
    text = "\n".join(track.get("text", "") for track in tracks)
    if not text:
        text = "\n".join(segment.text for segment in segments)
    if not text.strip():
        warnings.append("empty_transcript")
    if options.diarization and segments and not any(s.speaker_id for s in segments):
        warnings.append("diarization_not_returned")
    return Transcript(
        job_id=job_id,
        asset_id=asset_id,
        provider=provider,
        model=options.model,
        duration_ms=duration_ms,
        text=text,
        segments=segments,
        warnings=sorted(set(warnings)),
    )
