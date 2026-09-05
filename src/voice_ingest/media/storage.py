"""S3 calls are bounded and run outside the event loop; signing uses the public origin."""

import asyncio
import json
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from voice_ingest.media.contracts import UploadedPart
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import DomainError


class S3Storage:
    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.settings = settings
        kwargs = dict(
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=10,
                read_timeout=60,
                retries={"max_attempts": 3, "mode": "standard"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        self.internal = boto3.client("s3", endpoint_url=settings.s3_endpoint, **kwargs)
        self.public = boto3.client("s3", endpoint_url=settings.s3_public_endpoint, **kwargs)

    async def _call(self, operation: str, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(
                getattr(self.internal, operation), Bucket=self.bucket, **kwargs
            )
        except (ClientError, BotoCoreError) as exc:
            # SDK error strings may include signed request details. Do not propagate them.
            if isinstance(exc, ClientError):
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"NoSuchKey", "404", "NoSuchUpload"}:
                    raise DomainError(
                        "storage_not_found", "Object or upload not found", 404
                    ) from None
            raise DomainError(
                "storage_unavailable", "Object storage operation failed", 503, True
            ) from None

    async def health(self):
        await self._call("head_bucket")

    async def begin(self, key: str, sha256: str) -> str:
        response = await self._call(
            "create_multipart_upload",
            Key=key,
            ContentType="application/octet-stream",
            Metadata={"sha256": sha256},
        )
        return response["UploadId"]

    async def parts(self, key: str, upload_id: str) -> list[UploadedPart]:
        parts = []
        marker = 0
        while True:
            response = await self._call(
                "list_parts", Key=key, UploadId=upload_id, PartNumberMarker=marker
            )
            parts.extend(
                UploadedPart(number=p["PartNumber"], etag=p["ETag"], size=p["Size"])
                for p in response.get("Parts", [])
            )
            if not response.get("IsTruncated"):
                return parts
            marker = response["NextPartNumberMarker"]

    def sign_part(self, key: str, upload_id: str, part: int) -> str:
        return self.public.generate_presigned_url(
            "upload_part",
            Params={"Bucket": self.bucket, "Key": key, "UploadId": upload_id, "PartNumber": part},
            ExpiresIn=self.settings.upload_url_ttl,
        )

    def sign_download(self, key: str, *, internal: bool = False, ttl: int | None = None) -> str:
        client = self.internal if internal else self.public
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl or self.settings.download_url_ttl,
        )

    async def complete(self, key: str, upload_id: str, parts: list[UploadedPart]):
        await self._call(
            "complete_multipart_upload",
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": [{"PartNumber": p.number, "ETag": p.etag} for p in parts]},
        )

    async def head(self, key: str) -> dict[str, Any]:
        return await self._call("head_object", Key=key)

    async def abort(self, key: str, upload_id: str):
        try:
            await self._call("abort_multipart_upload", Key=key, UploadId=upload_id)
        except DomainError as exc:
            if exc.info.code != "storage_not_found":
                raise

    async def delete(self, key: str):
        await self._call("delete_object", Key=key)

    async def delete_prefix(self, prefix: str):
        while True:
            response = await self._call("list_objects_v2", Prefix=prefix, MaxKeys=1000)
            objects = response.get("Contents", [])
            if not objects:
                return
            result = await self._call(
                "delete_objects",
                Delete={"Objects": [{"Key": item["Key"]} for item in objects], "Quiet": True},
            )
            if result.get("Errors"):
                raise DomainError("storage_unavailable", "Object deletion failed", 503, True)

    async def put(self, key: str, body: bytes, content_type: str):
        await self._call("put_object", Key=key, Body=body, ContentType=content_type)

    async def read_json(self, key: str) -> dict[str, Any]:
        response = await self._call("get_object", Key=key)
        body = response["Body"]
        try:
            content = await asyncio.to_thread(body.read, 32 * 1024 * 1024 + 1)
            if len(content) > 32 * 1024 * 1024:
                raise DomainError("result_too_large", "Result exceeds the 32 MiB limit")
            return json.loads(content)
        finally:
            body.close()

    async def download(self, key: str, path: Path):
        try:
            await asyncio.to_thread(self.internal.download_file, self.bucket, key, str(path))
        except (ClientError, BotoCoreError):
            raise DomainError("storage_unavailable", "Audio download failed", 503, True) from None

    async def close(self):
        self.internal.close()
        self.public.close()
