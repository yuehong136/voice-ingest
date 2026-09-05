"""Opt-in local evaluation transport. Production should use durable public S3 URLs."""

import asyncio
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from voice_ingest.media.storage import S3Storage
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import DomainError, TranscriptionOptions


class AliyunTemporarySource:
    def __init__(
        self,
        storage: S3Storage,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ):
        self.storage, self.settings, self.transport = storage, settings, transport

    async def prepare(self, key: str, filename: str, options: TranscriptionOptions) -> str:
        suffix = Path(filename).suffix.lower()
        if not suffix[1:].isalnum() or len(suffix) > 10:
            suffix = ""
        with tempfile.TemporaryDirectory(prefix="voice-source-") as directory:
            path = Path(directory) / ("source" + suffix)
            await self.storage.download(key, path)
            # Streaming multipart reads happen in a thread, keeping heartbeat and memory bounded.
            upload = asyncio.create_task(asyncio.to_thread(self._upload, path, options.model))
            try:
                return await asyncio.shield(upload)
            except asyncio.CancelledError:
                # Do not remove the temporary source while the upload thread is still reading it.
                await asyncio.gather(upload, return_exceptions=True)
                raise

    def _upload(self, path: Path, model: str) -> str:
        try:
            with httpx.Client(
                transport=self.transport, timeout=30, follow_redirects=False
            ) as client:
                response = client.get(
                    self.settings.aliyun_base_url + "/uploads",
                    params={"action": "getPolicy", "model": model},
                    headers={
                        "Authorization": "Bearer " + self.settings.aliyun_api_key.get_secret_value()
                    },
                )
                self._check(response, "upload_policy_failed")
                data = response.json()["data"]
                host = data["upload_host"]
                parsed = urlparse(host)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or not parsed.hostname.endswith(".aliyuncs.com")
                    or parsed.username
                    or parsed.port not in {None, 443}
                ):
                    raise DomainError("invalid_upload_host", "Invalid provider upload destination")
                object_key = data["upload_dir"] + "/" + uuid4().hex + path.suffix
                fields = {
                    "OSSAccessKeyId": data["oss_access_key_id"],
                    "Signature": data["signature"],
                    "policy": data["policy"],
                    "key": object_key,
                    "x-oss-object-acl": data["x_oss_object_acl"],
                    "x-oss-forbid-overwrite": data["x_oss_forbid_overwrite"],
                    "success_action_status": "200",
                }
                with path.open("rb") as audio:
                    response = client.post(
                        host,
                        data=fields,
                        files={"file": (path.name, audio, "application/octet-stream")},
                        timeout=300,
                    )
                self._check(response, "temporary_upload_failed")
                return "oss://" + object_key
        except httpx.TransportError:
            # Source staging is not a billable ASR submission and may safely retry.
            raise DomainError(
                "temporary_upload_unavailable",
                "Temporary file upload failed; will retry",
                503,
                True,
            ) from None
        except (ValueError, KeyError, TypeError):
            raise DomainError(
                "invalid_upload_policy", "Provider returned an invalid file upload policy", 502
            ) from None

    @staticmethod
    def _check(response: httpx.Response, code: str):
        if not 200 <= response.status_code < 300:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise DomainError(
                code,
                "Provider file upload rejected; check credentials, region and file size",
                502,
                retryable,
            )
