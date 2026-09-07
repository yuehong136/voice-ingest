"""Aliyun duplex protocol consumed into one bounded, complete audio result."""

import asyncio
import json
import logging
from uuid import uuid4

from websockets.asyncio.client import connect

from voice_ingest.providers.base import SubmissionUnknown
from voice_ingest.providers.speech import Completed
from voice_ingest.runtime.settings import Settings
from voice_ingest.synthesis.contracts import SynthesisOptions
from voice_ingest.transcription.contracts import DomainError

MAX_AUDIO_BYTES = 64 * 1024 * 1024


class AliyunTTS:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def synthesize(self, text: str, options: SynthesisOptions) -> Completed:
        task_id = str(uuid4())
        events, chunks = [], []
        size, started, submitted = 0, False, False
        # Even DEBUG configuration must not expose websocket frame bodies or credentials.
        logger = logging.getLogger("voice_ingest.provider_transport")
        logger.disabled = True

        def message(action, payload):
            return json.dumps(
                {
                    "header": {"action": action, "task_id": task_id, "streaming": "duplex"},
                    "payload": payload,
                }
            )

        try:
            async with asyncio.timeout(600):
                async with connect(
                    self.settings.aliyun_websocket_url,
                    additional_headers={
                        "Authorization": f"Bearer {self.settings.aliyun_api_key.get_secret_value()}"
                    },
                    open_timeout=20,
                    close_timeout=5,
                    max_size=MAX_AUDIO_BYTES,
                    logger=logger,
                ) as socket:
                    submitted = True  # A failed send can still have reached the provider.
                    await socket.send(
                        message(
                            "run-task",
                            {
                                "task_group": "audio",
                                "task": "tts",
                                "function": "SpeechSynthesizer",
                                "model": options.model,
                                "parameters": {
                                    "text_type": "PlainText",
                                    "voice": options.voice,
                                    "format": options.format,
                                    "sample_rate": options.sample_rate,
                                    "volume": 50,
                                    "rate": 1,
                                    "pitch": 1,
                                    "enable_ssml": False,
                                },
                                "input": {},
                            },
                        )
                    )
                    while True:
                        packet = await asyncio.wait_for(socket.recv(), timeout=60)
                        if isinstance(packet, bytes):
                            if not started:
                                raise SubmissionUnknown()
                            size += len(packet)
                            if size > MAX_AUDIO_BYTES:
                                raise SubmissionUnknown()
                            chunks.append(packet)
                            continue
                        event = json.loads(packet)
                        header = event.get("header", {})
                        if header.get("task_id") != task_id:
                            raise SubmissionUnknown()
                        events.append(event)
                        if len(events) > 20000:
                            raise SubmissionUnknown()
                        kind = header.get("event")
                        if kind == "task-started" and not started:
                            started = True
                            await socket.send(message("continue-task", {"input": {"text": text}}))
                            await socket.send(message("finish-task", {"input": {}}))
                        elif kind == "task-finished":
                            if not started or size == 0:
                                raise SubmissionUnknown()
                            return Completed(
                                {"events": events, "request_id": task_id, "complete": True},
                                b"".join(chunks),
                            )
                        elif kind == "task-failed":
                            # A remote failure is definite, but it isn't safe to retry implicitly.
                            raise DomainError(
                                "provider_task_failed", "Speech synthesis failed", 502
                            )
        except DomainError as exc:
            exc.raw = {"events": events, "request_id": task_id, "complete": False}
            raise
        except Exception:
            if submitted:
                error = SubmissionUnknown()
                error.raw = {"events": events, "request_id": task_id, "complete": False}
                raise error from None
            raise DomainError(
                "provider_unavailable", "Could not connect to synthesis service", 503, True
            ) from None
