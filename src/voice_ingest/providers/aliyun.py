import json
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from voice_ingest.providers.base import PollResult, SubmissionUnknown
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import DomainError, TranscriptionOptions


class AliyunProvider:
    name = "aliyun"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.client = httpx.AsyncClient(
            base_url=settings.aliyun_base_url + "/",
            timeout=30,
            transport=transport,
            headers={"Authorization": f"Bearer {settings.aliyun_api_key.get_secret_value()}"},
            follow_redirects=False,
        )
        # A separate client prevents sending DashScope credentials to the result object store.
        self.download_client = httpx.AsyncClient(
            timeout=60, transport=transport, follow_redirects=False
        )

    async def _request(
        self, method: str, path: str, *, submitting=False, **kwargs
    ) -> dict[str, Any]:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.TransportError:
            if submitting:
                raise SubmissionUnknown() from None
            raise DomainError(
                "provider_unavailable", "Provider request failed", 503, True
            ) from None
        if response.status_code == 429:
            raise DomainError("provider_rate_limited", "Provider rate limit reached", 429, True)
        if response.status_code >= 500:
            if submitting:
                raise SubmissionUnknown()
            raise DomainError("provider_unavailable", "Provider temporarily unavailable", 503, True)
        if response.status_code >= 400:
            raise DomainError(
                "provider_rejected",
                "Provider rejected the request; check credentials, region and model",
                502,
            )
        try:
            data = response.json()
        except ValueError:
            if submitting:
                raise SubmissionUnknown() from None
            raise DomainError(
                "invalid_provider_response", "Provider returned invalid JSON", 502, True
            ) from None
        if data.get("code"):
            raise DomainError("provider_rejected", "Provider returned a business error", 502)
        return data

    async def submit(self, url: str, options: TranscriptionOptions, duration_ms: int) -> str:
        source: dict[str, Any] = {"file_urls": [url]}
        if options.context:
            source["context"] = [
                {"role": "user", "content": [{"type": "input_text", "text": options.context}]}
            ]
        parameters: dict[str, Any] = {"diarization_enabled": options.diarization}
        if options.speaker_count:
            parameters["speaker_count"] = options.speaker_count
        if options.language_hints:
            parameters["language_hints"] = options.language_hints
        response = await self._request(
            "POST",
            "services/audio/asr/transcription",
            submitting=True,
            headers={"X-DashScope-Async": "enable"},
            json={"model": options.model, "input": source, "parameters": parameters},
        )
        task_id = response.get("output", {}).get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise SubmissionUnknown()
        return task_id

    async def poll(self, task_id: str) -> PollResult:
        response = await self._request("GET", f"tasks/{quote(task_id, safe='')}")
        output = response.get("output", {})
        state = output.get("task_status")
        if state in {"PENDING", "RUNNING"}:
            return PollResult("pending")
        if state == "CANCELED":
            return PollResult("cancelled")
        if state == "FAILED":
            return PollResult("failed", error_code="provider_task_failed")
        if state == "SUCCEEDED":
            results = output.get("results", [])
            if len(results) != 1 or results[0].get("subtask_status") != "SUCCEEDED":
                return PollResult("failed", error_code="provider_file_failed")
            url = results[0].get("transcription_url")
            if not isinstance(url, str):
                raise DomainError(
                    "invalid_provider_response", "Missing transcription result URL", 502
                )
            return PollResult("succeeded", result_url=url)
        raise DomainError("invalid_provider_response", "Unknown provider task state", 502, True)

    async def fetch(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        # Only provider-returned OSS URLs are accepted; no redirects or user-controlled URLs.
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".aliyuncs.com")
            or parsed.username
            or parsed.port not in {None, 443}
        ):
            raise DomainError("invalid_result_url", "Provider result must be an HTTPS Alibaba URL")
        try:
            async with self.download_client.stream("GET", url) as response:
                if response.status_code in {403, 404}:
                    raise DomainError(
                        "result_expired", "Provider result is expired or inaccessible", 502
                    )
                if response.status_code != 200:
                    raise DomainError("result_download_failed", "Result download failed", 502, True)
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise DomainError("result_too_large", "Provider JSON exceeds 32 MiB")
                    chunks.append(chunk)
                return json.loads(b"".join(chunks))
        except httpx.TransportError:
            raise DomainError(
                "result_download_failed", "Result download failed", 502, True
            ) from None
        except ValueError:
            raise DomainError("invalid_result", "Result is not valid JSON", 502) from None

    async def cancel(self, task_id: str) -> bool:
        # Only PENDING tasks can be cancelled. Never imply running inference stopped.
        if (await self.poll(task_id)).state != "pending":
            return False
        response = await self._request("POST", f"tasks/{quote(task_id, safe='')}/cancel")
        return response.get("output", {}).get("task_status") == "CANCELED"

    async def close(self):
        await self.client.aclose()
        await self.download_client.aclose()
