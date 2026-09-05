import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_ingest.exports.render import CONTENT_TYPES, render
from voice_ingest.media.storage import S3Storage
from voice_ingest.providers.base import MODELS, validate_options
from voice_ingest.runtime.database import Asset, Attempt, Event, Job, now, uid
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import (
    ACTIVE,
    CreateTranscription,
    DomainError,
    ExportFormat,
    JobPage,
    JobState,
    JobView,
    Transcript,
    TranscriptPage,
)


class TranscriptionService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], storage: S3Storage, settings: Settings
    ):
        self.sessions, self.storage, self.settings = sessions, storage, settings

    def models(self):
        return [m.model_copy(update={"provider": self.settings.provider}) for m in MODELS]

    async def create(self, request: CreateTranscription, idempotency_key: str) -> JobView:
        if not 1 <= len(idempotency_key) <= 200:
            raise DomainError("invalid_idempotency_key", "Idempotency-Key must be 1-200 characters")
        validate_options(request.options)
        digest = hashlib.sha256(
            json.dumps(request.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        try:
            async with self.sessions.begin() as session:
                existing = await session.scalar(
                    select(Job).where(Job.idempotency_key == idempotency_key)
                )
                if existing:
                    return self._idempotent(existing, digest)
                asset = await session.get(Asset, request.asset_id, with_for_update=True)
                if not asset or not asset.ready or asset.deleted:
                    raise DomainError("asset_not_ready", "Upload a ready asset first", 409)
                validate_options(request.options, asset.duration_ms, asset.size)
                job = Job(
                    id=uid(),
                    asset_id=asset.id,
                    options=request.options.model_dump(),
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                )
                session.add(job)
                await session.flush()
                session.add(self._attempt(job))
                session.add(Event(job_id=job.id, state="queued"))
                return JobView.model_validate(job)
        except IntegrityError:
            async with self.sessions() as session:
                existing = await session.scalar(
                    select(Job).where(Job.idempotency_key == idempotency_key)
                )
                if not existing:
                    raise
                return self._idempotent(existing, digest)

    def _attempt(self, job: Job) -> Attempt:
        return Attempt(
            job_id=job.id,
            number=job.attempt,
            provider=self.settings.provider,
            region=self.settings.aliyun_region,
            request={
                "options": job.options,
                "source_mode": self.settings.aliyun_source_mode,
                "asset_id": job.asset_id,
                "endpoint": self.settings.aliyun_base_url
                if self.settings.provider == "aliyun"
                else "mock",
            },
        )

    @staticmethod
    def _idempotent(job: Job, digest: str) -> JobView:
        if job.request_digest != digest:
            raise DomainError(
                "idempotency_conflict", "This key was used with different parameters", 409
            )
        return JobView.model_validate(job)

    async def get(self, job_id: str) -> JobView:
        async with self.sessions() as session:
            job = await self._load(session, job_id)
            return JobView.model_validate(job)

    async def _load(self, session: AsyncSession, job_id: str, lock=False) -> Job:
        job = await session.get(Job, job_id, with_for_update=lock)
        if not job:
            raise DomainError("job_not_found", "Transcription not found", 404)
        return job

    async def list(self, cursor: str | None = None, limit: int = 50) -> JobPage:
        if not 1 <= limit <= 100:
            raise DomainError("invalid_limit", "Limit must be 1-100")
        async with self.sessions() as session:
            query = select(Job).order_by(Job.id).limit(limit + 1)
            if cursor:
                query = query.where(Job.id > cursor)
            jobs = list((await session.scalars(query)).all())
        return JobPage(
            items=[JobView.model_validate(j) for j in jobs[:limit]],
            next_cursor=jobs[limit - 1].id if len(jobs) > limit else None,
        )

    async def cancel(self, job_id: str) -> JobView:
        async with self.sessions.begin() as session:
            job = await self._load(session, job_id, True)
            if job.state in {"queued", "preparing"} and not job.provider_task_id:
                job.state = "cancelled"
                job.generation += 1
                job.lease_owner = job.lease_until = None
            elif job.state in {"submitting", "running", "finalizing", "needs_attention"}:
                job.state = "cancel_requested"
                job.remote_may_run = job.result_url is None
            job.updated_at, job.next_run_at = now(), now()
            session.add(Event(job_id=job.id, state=job.state))
            return JobView.model_validate(job)

    async def retry(self, job_id: str, acknowledge_duplicate_risk: bool = False) -> JobView:
        async with self.sessions.begin() as session:
            job = await self._load(session, job_id, True)
            if job.state not in {"failed", "needs_attention", "cancelled"}:
                raise DomainError("not_retryable", "Task is not in a retryable state", 409)
            if job.lease_until and job.lease_until.timestamp() > now().timestamp():
                raise DomainError("worker_still_active", "Wait for the active worker lease", 409)
            if (
                job.state == "needs_attention" or job.remote_may_run
            ) and not acknowledge_duplicate_risk:
                raise DomainError(
                    "duplicate_risk",
                    "Explicitly acknowledge possible duplicate processing and charges",
                    409,
                )
            asset = await session.get(Asset, job.asset_id, with_for_update=True)
            if not asset or asset.deleted:
                raise DomainError("asset_not_found", "Original audio is no longer available", 409)
            code = (job.error or {}).get("code")
            if (job.raw_key or job.result_url) and code != "result_expired":
                job.state = "finalizing"
            elif job.provider_task_id and code in {
                "provider_unavailable",
                "provider_rate_limited",
                "invalid_provider_response",
            }:
                job.state = "running"
            else:
                job.attempt += 1
                job.state = "queued"
                job.provider_task_id = job.result_url = job.result_key = job.raw_key = None
                job.remote_may_run = False
                session.add(self._attempt(job))
            job.generation += 1
            job.lease_owner = job.lease_until = None
            job.error, job.retry_count = None, 0
            job.updated_at = job.next_run_at = job.attempt_started_at = now()
            session.add(Event(job_id=job.id, state=job.state, code="manual_retry"))
            return JobView.model_validate(job)

    async def result(self, job_id: str) -> Transcript:
        async with self.sessions() as session:
            job = await self._load(session, job_id)
            if job.state != "succeeded" or not job.result_key:
                raise DomainError("result_not_ready", "Transcription is not complete", 409)
        return Transcript.model_validate(await self.storage.read_json(job.result_key))

    async def read(
        self,
        job_id: str,
        cursor: str | None = None,
        limit: int = 50,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> TranscriptPage:
        if not 1 <= limit <= 100:
            raise DomainError("invalid_limit", "Limit must be 1-100")
        try:
            offset = int(cursor or "0")
            if offset < 0:
                raise ValueError
        except ValueError:
            raise DomainError("invalid_cursor", "Invalid transcript cursor") from None
        if (
            (start_ms is not None and start_ms < 0)
            or (end_ms is not None and end_ms < 0)
            or (start_ms is not None and end_ms is not None and start_ms >= end_ms)
        ):
            raise DomainError("invalid_time_range", "Time range must be positive and increasing")
        result = await self.result(job_id)
        segments = [
            s
            for s in result.segments
            if (start_ms is None or (s.end_ms is not None and s.end_ms > start_ms))
            and (end_ms is None or (s.start_ms is not None and s.start_ms < end_ms))
        ]
        page = segments[offset : offset + limit]
        return TranscriptPage(
            job_id=job_id,
            segments=page,
            warnings=result.warnings,
            next_cursor=str(offset + limit) if offset + limit < len(segments) else None,
        )

    async def export(self, job_id: str, format: ExportFormat) -> bytes:
        transcript = await self.result(job_id)
        body = render(transcript, format)
        async with self.sessions() as session:
            job = await self._load(session, job_id)
        await self.storage.put(
            f"results/{job.id}/{job.attempt}/export.{format}", body, CONTENT_TYPES[format]
        )
        return body

    async def delete(self, job_id: str):
        # Keep the idempotency tombstone and event history; remove all content artifacts.
        async with self.sessions.begin() as session:
            job = await self._load(session, job_id, True)
            if job.state in ACTIVE or job.remote_may_run:
                raise DomainError("job_in_use", "Task may still be running", 409)
            job.state, job.result_key = JobState.FAILED, None
            job.raw_key = job.result_url = None
            job.error = {
                "code": "result_deleted",
                "message": "Results explicitly deleted",
                "retryable": False,
            }
            session.add(Event(job_id=job.id, state="failed", code="result_deleted"))
        await self.storage.delete_prefix(f"results/{job_id}/")
