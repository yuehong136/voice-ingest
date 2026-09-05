import json

import httpx
import pytest
from pydantic import SecretStr

from voice_ingest.exports.render import render
from voice_ingest.providers.aliyun import AliyunProvider
from voice_ingest.providers.base import SubmissionUnknown, normalize, validate_options
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import DomainError, TranscriptionOptions


def settings():
    return Settings(
        _env_file=None,
        api_key=SecretStr("api-secret"),
        provider="aliyun",
        aliyun_api_key=SecretStr("provider-secret"),
    )


def test_token_plan_key_cannot_silently_use_regular_billing():
    with pytest.raises(ValueError, match="no billing fallback"):
        Settings(
            _env_file=None,
            api_key=SecretStr("local-test"),
            provider="aliyun",
            aliyun_api_key=SecretStr("sk-sp-test-only"),
        )


async def test_aliyun_wire_contract_and_file_level_failure():
    requests = []

    async def handler(request):
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["input"]["context"][0]["content"][0]["type"] == "input_text"
            assert body["parameters"]["diarization_enabled"] is True
            assert request.headers["X-DashScope-Async"] == "enable"
            return httpx.Response(
                200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}}
            )
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [{"subtask_status": "FAILED", "code": "FILE_DOWNLOAD_FAILED"}],
                }
            },
        )

    provider = AliyunProvider(settings(), httpx.MockTransport(handler))
    try:
        task_id = await provider.submit(
            "http://files.example/audio?signature=secret",
            TranscriptionOptions(diarization=True, context="会议背景"),
            3600000,
        )
        assert task_id == "task-1"
        assert (await provider.poll(task_id)).state == "failed"
    finally:
        await provider.close()


async def test_provider_unknown_and_rate_limit():
    async def unknown(request):
        raise httpx.ReadTimeout("secret signed URL")

    provider = AliyunProvider(settings(), httpx.MockTransport(unknown))
    try:
        with pytest.raises(SubmissionUnknown) as error:
            await provider.submit("http://example/audio", TranscriptionOptions(), 1000)
        assert "secret" not in str(error.value)
    finally:
        await provider.close()
    provider = AliyunProvider(settings(), httpx.MockTransport(lambda request: httpx.Response(429)))
    try:
        with pytest.raises(DomainError) as error:
            await provider.submit("http://example/audio", TranscriptionOptions(), 1000)
        assert error.value.info.retryable
    finally:
        await provider.close()


async def test_download_never_forwards_api_key_or_redirects():
    async def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"transcripts": []})

    provider = AliyunProvider(settings(), httpx.MockTransport(handler))
    try:
        assert await provider.fetch(
            "https://result.oss-cn-beijing.aliyuncs.com/a?Signature=test"
        ) == {"transcripts": []}
        with pytest.raises(DomainError):
            await provider.fetch("http://127.0.0.1/private")
    finally:
        await provider.close()


def test_capabilities_and_no_invented_timestamps():
    with pytest.raises(DomainError, match="two hours"):
        validate_options(TranscriptionOptions(diarization=True), 7_200_001)
    with pytest.raises(DomainError, match="context"):
        validate_options(TranscriptionOptions(model="fun-asr", context="custom"))
    raw = {"transcripts": [{"text": "hello", "sentences": [{"text": "hello"}]}]}
    transcript = normalize(
        raw,
        job_id="a",
        asset_id="b",
        provider="aliyun",
        options=TranscriptionOptions(),
        duration_ms=1000,
    )
    assert transcript.segments[0].start_ms is None
    with pytest.raises(DomainError, match="timestamps"):
        render(transcript, "srt")
    assert b"hello" in render(transcript, "txt")


def test_normalization_preserves_channels_and_word_punctuation():
    raw = {
        "transcripts": [
            {
                "channel_id": 1,
                "text": "hello!",
                "sentences": [
                    {
                        "text": "hello!",
                        "begin_time": 100,
                        "end_time": 500,
                        "speaker_id": 0,
                        "words": [
                            {
                                "text": "hello",
                                "punctuation": "!",
                                "begin_time": 100,
                                "end_time": 500,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    result = normalize(
        raw,
        job_id="a",
        asset_id="b",
        provider="aliyun",
        options=TranscriptionOptions(),
        duration_ms=1000,
    )
    assert result.segments[0].speaker_id == "0"
    assert result.segments[0].channel_id == 1
    assert result.segments[0].words[0].text == "hello!"
    assert b"00:00:00,100 --> 00:00:00,500" in render(result, "srt")
