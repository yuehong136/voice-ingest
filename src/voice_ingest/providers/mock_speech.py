"""Explicit test deployment; never registered alongside production vendors."""

import io
import wave

from voice_ingest.providers.aliyun_speech import AliyunSpeechAdapter
from voice_ingest.providers.speech import Completed, SpeechRequest


class MockSpeechAdapter(AliyunSpeechAdapter):
    name = "mock"
    tts_model = "mock-tts"
    tts_voice = "mock-voice"
    tts_format = "wav"

    async def start(self, request: SpeechRequest):
        self.validate(request)
        if request.kind != "synthesis":
            return await super().start(request)
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(22050)
            audio.writeframes(b"\0\0" * 22050)
        return Completed(
            {"complete": True, "request_id": "mock-synthesis", "mock": True}, output.getvalue()
        )
