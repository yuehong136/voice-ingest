import math
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_ingest.media.contracts import PART_SIZE, CreateUpload, SignedPart, UploadView
from voice_ingest.media.storage import S3Storage
from voice_ingest.runtime.database import Asset, Job, Upload, now, uid
from voice_ingest.transcription.contracts import ACTIVE, AssetView, DomainError


class UploadService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], storage: S3Storage):
        self.sessions = sessions
        self.storage = storage

    async def create(self, request: CreateUpload) -> UploadView:
        asset_id, upload_id = uid(), uid()
        key = f"audio/{asset_id}/source"
        async with self.sessions.begin() as session:
            session.add(
                Asset(
                    id=asset_id,
                    filename=request.filename,
                    size=request.size,
                    sha256=request.sha256,
                    object_key=key,
                )
            )
            await session.flush()
            session.add(
                Upload(id=upload_id, asset_id=asset_id, expires_at=now() + timedelta(hours=24))
            )
        multipart_id = await self.storage.begin(key, request.sha256)
        async with self.sessions.begin() as session:
            upload = await session.get(Upload, upload_id, with_for_update=True)
            assert upload is not None
            upload.multipart_id, upload.state = multipart_id, "uploading"
        return await self.get(upload_id)

    async def _load(self, session: AsyncSession, upload_id: str, lock: bool = False):
        upload = await session.get(Upload, upload_id, with_for_update=lock)
        if not upload:
            raise DomainError("upload_not_found", "Upload not found", 404)
        asset = await session.get(Asset, upload.asset_id)
        assert asset is not None
        return upload, asset

    async def get(self, upload_id: str) -> UploadView:
        async with self.sessions() as session:
            upload, asset = await self._load(session, upload_id)
        parts = []
        if upload.state == "uploading" and upload.multipart_id:
            parts = await self.storage.parts(asset.object_key, upload.multipart_id)
        return UploadView(
            id=upload.id,
            asset_id=asset.id,
            state=upload.state,
            filename=asset.filename,
            size=asset.size,
            sha256=asset.sha256,
            expires_at=upload.expires_at,
            parts=parts,
        )

    async def sign(self, upload_id: str, part: int) -> SignedPart:
        async with self.sessions.begin() as session:
            upload, asset = await self._load(session, upload_id, True)
            expired = upload.expires_at.timestamp() <= now().timestamp()
            if upload.state != "uploading" or expired or not upload.multipart_id:
                raise DomainError("upload_not_writable", "Upload is closed or expired", 409)
            if not 1 <= part <= math.ceil(asset.size / PART_SIZE):
                raise DomainError("invalid_part", "Part number is outside this file")
            url = self.storage.sign_part(asset.object_key, upload.multipart_id, part)
        return SignedPart(url=url, expires_in=self.storage.settings.upload_url_ttl)

    async def complete(self, upload_id: str) -> UploadView:
        # Completing is durable. Replays recover a completed object after a process crash.
        token = uid()
        async with self.sessions.begin() as session:
            upload, asset = await self._load(session, upload_id, True)
            if upload.state == "complete":
                done = True
            else:
                done = False
                if upload.state not in {"uploading", "completing"} or not upload.multipart_id:
                    raise DomainError("upload_not_writable", "Upload cannot be completed", 409)
                if upload.expires_at.timestamp() <= now().timestamp():
                    raise DomainError("upload_expired", "Upload has expired", 409)
                if upload.operation_until and upload.operation_until > now():
                    raise DomainError(
                        "upload_busy", "Upload completion is still in progress", 409, True
                    )
                upload.state = "completing"
                upload.operation_token = token
                upload.operation_until = now() + timedelta(minutes=5)
        if done:
            return await self.get(upload_id)
        assert upload.multipart_id
        try:
            head = await self.storage.head(asset.object_key)
        except DomainError as exc:
            if exc.info.code != "storage_not_found":
                raise
            parts = await self.storage.parts(asset.object_key, upload.multipart_id)
            count = math.ceil(asset.size / PART_SIZE)
            valid = len(parts) == count and all(
                p.number == index + 1 and p.size == min(PART_SIZE, asset.size - index * PART_SIZE)
                for index, p in enumerate(parts)
            )
            if not valid:
                async with self.sessions.begin() as session:
                    record = await session.get(Upload, upload_id, with_for_update=True)
                    assert record
                    if record.state == "completing" and record.operation_token == token:
                        record.state = "uploading"
                        record.operation_until = None
                raise DomainError(
                    "incomplete_upload", "Upload all expected file parts first", 409
                ) from None
            await self.storage.complete(asset.object_key, upload.multipart_id, parts)
            head = await self.storage.head(asset.object_key)
        if (
            head["ContentLength"] != asset.size
            or head.get("Metadata", {}).get("sha256") != asset.sha256
        ):
            raise DomainError("object_mismatch", "Uploaded object metadata differs", 409)
        async with self.sessions.begin() as session:
            upload, asset = await self._load(session, upload_id, True)
            if upload.state != "completing" or upload.operation_token != token:
                raise DomainError("upload_state_changed", "Upload state changed", 409)
            upload.state, asset.ready = "complete", True
            upload.operation_until = None
        return await self.get(upload_id)

    async def abort(self, upload_id: str):
        async with self.sessions.begin() as session:
            upload, asset = await self._load(session, upload_id, True)
            if upload.state == "complete":
                raise DomainError("upload_complete", "Delete the asset instead", 409)
            if upload.operation_until and upload.operation_until > now():
                raise DomainError(
                    "upload_busy", "Upload completion is still in progress", 409, True
                )
            upload.state = "aborting"
        if upload.multipart_id:
            await self.storage.abort(asset.object_key, upload.multipart_id)
        await self.storage.delete(asset.object_key)
        async with self.sessions.begin() as session:
            upload, asset = await self._load(session, upload_id, True)
            upload.state, asset.deleted = "aborted", True

    async def cleanup(self):
        async with self.sessions() as session:
            ids = (
                await session.scalars(
                    select(Upload.id)
                    .where(Upload.expires_at < now(), Upload.state.not_in(["complete", "aborted"]))
                    .limit(50)
                )
            ).all()
        for upload_id in ids:
            try:
                await self.abort(upload_id)
            except DomainError as exc:
                if exc.info.code != "upload_busy":
                    raise

    async def get_asset(self, asset_id: str) -> AssetView:
        async with self.sessions() as session:
            asset = await session.get(Asset, asset_id)
            if not asset or not asset.ready or asset.deleted:
                raise DomainError("asset_not_found", "Ready asset not found", 404)
            return AssetView.model_validate(asset)

    async def delete_asset(self, asset_id: str):
        async with self.sessions.begin() as session:
            asset = await session.get(Asset, asset_id, with_for_update=True)
            if not asset:
                raise DomainError("asset_not_found", "Asset not found", 404)
            active = await session.scalar(
                select(Job.id)
                .where(
                    Job.asset_id == asset_id,
                    (Job.state.in_(ACTIVE)) | Job.remote_may_run,
                )
                .limit(1)
            )
            if active:
                raise DomainError(
                    "asset_in_use", "A local or remote task may still use this asset", 409
                )
            asset.deleted = True
        await self.storage.delete(asset.object_key)
