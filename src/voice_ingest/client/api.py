"""Public async client. No server, database or MCP imports."""

import asyncio
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from voice_ingest.media.contracts import PART_SIZE, UploadView
from voice_ingest.transcription.contracts import (
    TERMINAL,
    AssetView,
    CreateTranscription,
    ErrorInfo,
    ExportFormat,
    JobPage,
    JobView,
    ModelCapability,
    Transcript,
    TranscriptionOptions,
    TranscriptPage,
)


class VoiceError(Exception):
    def __init__(self, error: ErrorInfo, status: int = 0):
        super().__init__(error.message)
        self.error, self.status = error, status


def fingerprint(path: Path) -> dict[str, Any]:
    before = path.stat()
    with path.open("rb") as source:
        sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise VoiceError(ErrorInfo(code="file_changed", message="File changed while hashing"))
    return {"size": after.st_size, "mtime_ns": after.st_mtime_ns, "sha256": sha256}


def read_part(path: Path, offset: int, size: int) -> bytes:
    with path.open("rb") as stream:
        stream.seek(offset)
        return stream.read(size)


def save_state(path: Path, data: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class AsyncVoiceClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
        upload_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(
            base_url=self.base_url + "/",
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            follow_redirects=False,
        )
        self.upload_http = httpx.AsyncClient(
            timeout=120, transport=upload_transport, follow_redirects=False
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        await self.http.aclose()
        await self.upload_http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.TransportError:
            raise VoiceError(
                ErrorInfo(
                    code="connection_failed", message="Backend connection failed", retryable=True
                )
            ) from None
        if response.is_error:
            try:
                error = ErrorInfo.model_validate(response.json()["error"])
            except (ValueError, KeyError, TypeError):
                error = ErrorInfo(
                    code="http_error", message=f"Backend returned HTTP {response.status_code}"
                )
            raise VoiceError(error, response.status_code)
        return response

    async def models(self) -> list[ModelCapability]:
        return [
            ModelCapability.model_validate(m)
            for m in (await self._request("GET", "v1/models")).json()
        ]

    async def get_upload(self, upload_id: str) -> UploadView:
        return UploadView.model_validate(
            (await self._request("GET", f"v1/uploads/{upload_id}")).json()
        )

    async def abort_upload(self, upload_id: str):
        await self._request("DELETE", f"v1/uploads/{upload_id}")

    async def upload(
        self,
        file: str | Path,
        *,
        resume: bool = True,
        state_dir: Path | None = None,
        concurrency: int = 4,
    ) -> AssetView:
        if not 1 <= concurrency <= 16:
            raise ValueError("concurrency must be 1-16")
        path = await asyncio.to_thread(lambda: Path(file).expanduser().resolve(strict=True))
        if not await asyncio.to_thread(path.is_file):
            raise ValueError("Expected a regular file")
        identity = await asyncio.to_thread(fingerprint, path)
        state_dir = state_dir or Path.home() / ".local/state/voice-ingest/uploads"
        cache_key = hashlib.sha256(f"{self.base_url}:{path}".encode()).hexdigest()
        state_path = state_dir / f"{cache_key}.json"
        state: dict[str, Any] = {}
        upload = None
        if resume and state_path.exists():
            try:
                state = json.loads(await asyncio.to_thread(state_path.read_text))
            except (ValueError, OSError):
                state = {}
            if state.get("fingerprint") == identity:
                try:
                    upload = await self.get_upload(state["upload_id"])
                    if upload.state not in {"uploading", "completing", "complete"}:
                        upload = None
                    elif upload.sha256 != identity["sha256"] or upload.size != identity["size"]:
                        upload = None
                except VoiceError as exc:
                    if exc.status not in {404, 409}:
                        raise
        if upload and upload.state == "complete":
            return await self.asset(upload.asset_id)
        if upload and upload.expires_at.timestamp() < time.time():
            upload = None
        if upload is None:
            response = await self._request(
                "POST",
                "v1/uploads",
                json={
                    "filename": path.name,
                    "size": identity["size"],
                    "sha256": identity["sha256"],
                },
            )
            upload = UploadView.model_validate(response.json())
            await asyncio.to_thread(
                save_state, state_path, {"fingerprint": identity, "upload_id": upload.id}
            )
        if upload.state != "completing":
            existing = {p.number: p for p in upload.parts}
            semaphore = asyncio.Semaphore(concurrency)

            async def transfer(number: int):
                assert upload is not None
                async with semaphore:
                    size = min(PART_SIZE, identity["size"] - (number - 1) * PART_SIZE)
                    if number in existing and existing[number].size == size:
                        return
                    body = await asyncio.to_thread(read_part, path, (number - 1) * PART_SIZE, size)
                    for attempt in range(4):
                        signed = (
                            await self._request("POST", f"v1/uploads/{upload.id}/parts/{number}")
                        ).json()["url"]
                        try:
                            response = await self.upload_http.put(signed, content=body)
                            if response.is_success:
                                return
                            if response.status_code not in {403, 408, 429, 500, 502, 503, 504}:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(min(8, 2**attempt))
                    raise VoiceError(
                        ErrorInfo(
                            code="upload_failed",
                            message="Part upload failed; run again to resume",
                            retryable=True,
                        )
                    )

            async with asyncio.TaskGroup() as group:
                for number in range(1, math.ceil(identity["size"] / PART_SIZE) + 1):
                    group.create_task(transfer(number))
        if await asyncio.to_thread(fingerprint, path) != identity:
            await self.abort_upload(upload.id)
            raise VoiceError(
                ErrorInfo(
                    code="file_changed",
                    message="File changed during upload; retry with the new file",
                )
            )
        await self._request("POST", f"v1/uploads/{upload.id}/complete")
        return await self.asset(upload.asset_id)

    async def asset(self, asset_id: str) -> AssetView:
        return AssetView.model_validate(
            (await self._request("GET", f"v1/assets/{asset_id}")).json()
        )

    async def delete_asset(self, asset_id: str):
        await self._request("DELETE", f"v1/assets/{asset_id}")

    async def submit(
        self,
        asset_id: str,
        *,
        options: TranscriptionOptions | None = None,
        idempotency_key: str | None = None,
    ) -> JobView:
        body = CreateTranscription(asset_id=asset_id, options=options or TranscriptionOptions())
        return JobView.model_validate(
            (
                await self._request(
                    "POST",
                    "v1/transcriptions",
                    json=body.model_dump(),
                    headers={"Idempotency-Key": idempotency_key or uuid4().hex},
                )
            ).json()
        )

    async def get(self, job_id: str) -> JobView:
        return JobView.model_validate(
            (await self._request("GET", f"v1/transcriptions/{job_id}")).json()
        )

    async def list(self, cursor: str | None = None, limit: int = 50) -> JobPage:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return JobPage.model_validate(
            (await self._request("GET", "v1/transcriptions", params=params)).json()
        )

    async def cancel(self, job_id: str) -> JobView:
        return JobView.model_validate(
            (await self._request("POST", f"v1/transcriptions/{job_id}/cancel")).json()
        )

    async def retry(self, job_id: str, *, acknowledge_duplicate_risk: bool = False) -> JobView:
        return JobView.model_validate(
            (
                await self._request(
                    "POST",
                    f"v1/transcriptions/{job_id}/retry",
                    json={"acknowledge_duplicate_risk": acknowledge_duplicate_risk},
                )
            ).json()
        )

    async def wait(self, job_id: str, *, timeout: float = 86400, interval: float = 3) -> JobView:  # noqa: ASYNC109
        async with asyncio.timeout(timeout):
            while True:
                job = await self.get(job_id)
                if job.state in TERMINAL:
                    return job
                await asyncio.sleep(interval)

    async def result(self, job_id: str) -> Transcript:
        return Transcript.model_validate(
            (await self._request("GET", f"v1/transcriptions/{job_id}/result")).json()
        )

    async def read(
        self,
        job_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> TranscriptPage:
        params = {
            key: value
            for key, value in dict(
                cursor=cursor, limit=limit, start_ms=start_ms, end_ms=end_ms
            ).items()
            if value is not None
        }
        return TranscriptPage.model_validate(
            (
                await self._request("GET", f"v1/transcriptions/{job_id}/segments", params=params)
            ).json()
        )

    async def export(self, job_id: str, format: ExportFormat = "json") -> bytes:
        return (await self._request("GET", f"v1/transcriptions/{job_id}/exports/{format}")).content

    async def delete(self, job_id: str):
        await self._request("DELETE", f"v1/transcriptions/{job_id}")
