"""Aliyun capability adapter; all vendor-specific validation stays here."""

from typing import Any

from voice_ingest.providers.aliyun_contracts import MODELS, normalize, validate_options
from voice_ingest.providers.aliyun_tts import AliyunTTS
from voice_ingest.providers.base import ASRProvider
from voice_ingest.providers.speech import Accepted, Completed, SpeechRequest
from voice_ingest.runtime.settings import Settings
from voice_ingest.synthesis.contracts import SynthesisOptions, SynthesisResult, Voice
from voice_ingest.transcription.contracts import DomainError, ModelCapability, TranscriptionOptions


class AliyunSpeechAdapter:
    name = "aliyun"
    tts_model = "qwen-audio-3.0-tts-flash"
    tts_voice = "longanhuan_v3.6"
    tts_format = "mp3"

    def __init__(self, client: ASRProvider, settings: Settings):
        self.client = client
        self.tts = AliyunTTS(settings)

    def models(self) -> list[ModelCapability]:
        return [m.model_copy(update={"provider": self.name}) for m in MODELS] + [
            ModelCapability(
                id=self.tts_model,
                provider=self.name,
                kind="synthesis",
                execution="audio_stream",
                formats=[self.tts_format],
                sample_rates=[22050],
                max_text_characters=20000,
                diarization=False,
                max_language_hints=0,
            ),
        ]

    def voices(self, model: str) -> list[Voice]:
        return (
            [Voice(id=self.tts_voice, name=self.tts_voice, model=model, deployment_id="default")]
            if model == self.tts_model
            else []
        )

    def validate(self, request: SpeechRequest, *, size=None, format_name=None):
        if request.kind == "transcription":
            validate_options(
                TranscriptionOptions.model_validate(request.options),
                request.duration_ms,
                size,
                format_name,
            )
        elif request.kind == "synthesis":
            options = SynthesisOptions.model_validate(request.options)
            if (
                options.model != self.tts_model
                or options.voice != self.tts_voice
                or options.format != self.tts_format
                or options.sample_rate != 22050
            ):
                raise DomainError(
                    "unsupported_synthesis", "Select a supported model, voice and format"
                )
            text = request.input.get("text", "")
            if not isinstance(text, str) or not text.strip() or len(text) > 20000:
                raise DomainError("invalid_text", "Supply 1-20000 characters of text")
        else:
            raise DomainError("unsupported_capability", "Speech capability is not supported")

    async def start(self, request: SpeechRequest) -> Accepted | Completed:
        self.validate(request)
        if request.kind == "synthesis":
            return await self.tts.synthesize(
                request.input["text"], SynthesisOptions.model_validate(request.options)
            )
        assert request.source_url
        try:
            task_id = await self.client.submit(
                request.source_url,
                TranscriptionOptions.model_validate(request.options),
                request.duration_ms,
            )
        except DomainError as exc:
            exc.raw = getattr(self.client, "last_response", None)
            raise
        raw = getattr(self.client, "submission_response", None) or {"task_id": task_id}
        return Accepted(task_id, raw)

    async def poll(self, task_id: str):
        return await self.client.poll(task_id)

    async def fetch(self, reference: str) -> Completed:
        return Completed(await self.client.fetch(reference))

    async def cancel(self, task_id: str):
        return await self.client.cancel(task_id)

    def normalize(
        self, raw: dict[str, Any], request: SpeechRequest, context: dict[str, Any]
    ) -> dict[str, Any]:
        if request.kind == "transcription":
            return normalize(
                raw,
                job_id=context["job_id"],
                asset_id=context["asset_id"],
                provider=self.name,
                options=TranscriptionOptions.model_validate(request.options),
                duration_ms=request.duration_ms,
            ).model_dump()
        options = SynthesisOptions.model_validate(request.options)
        return SynthesisResult(
            job_id=context["job_id"],
            provider=self.name,
            model=options.model,
            deployment_id=context["deployment_id"],
            deployment_revision=context["deployment_revision"],
            voice=options.voice,
            format=options.format,
            content_type=f"audio/{'mpeg' if options.format == 'mp3' else 'wav'}",
            size=context["size"],
            sha256=context["sha256"],
            duration_ms=context["duration_ms"],
            sample_rate=options.sample_rate,
            request_id=raw.get("request_id"),
            input_characters=len(request.input["text"]),
            audio_path=f"/v1/syntheses/{context['job_id']}/audio",
        ).model_dump()

    async def close(self):
        await self.client.close()
