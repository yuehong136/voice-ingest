"""Shared durable lifecycle; capabilities supply their own public views and results."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_ingest.jobs.contracts import ACTIVE, Contract, DomainError
from voice_ingest.jobs.receipts import read_receipt
from voice_ingest.media.storage import S3Storage
from voice_ingest.providers.registry import Registry
from voice_ingest.providers.speech import SpeechRequest
from voice_ingest.runtime.database import Asset, Attempt, Event, Job, now, uid
from voice_ingest.runtime.settings import Settings


class JobService[V: Contract, P: Contract]:
    kind: str
    view_type: type[V]
    page_type: type[P]

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        storage: S3Storage,
        settings: Settings,
        registry: Registry,
    ):
        self.sessions, self.storage, self.settings = sessions, storage, settings
        self.registry = registry

    def models(self):
        return self.registry.models()

    def voices(self, model: str, deployment_id: str | None = None):
        matches = [
            m
            for m in self.models()
            if m.id == model
            and m.kind == "synthesis"
            and (deployment_id is None or m.deployment_id == deployment_id)
        ]
        if not matches:
            raise DomainError("unsupported_model", "Select an available synthesis deployment")
        return [
            v.model_copy(update={"deployment_id": m.deployment_id})
            for m in matches
            for v in self.registry.deployments[m.deployment_id].adapter.voices(model)
        ]

    def _view(self, job: Job) -> V:
        return self.view_type.model_validate(job)

    def _idempotent(self, job: Job, digest: str) -> V:
        if job.kind != self.kind or job.request_digest != digest:
            raise DomainError(
                "idempotency_conflict", "This key was used with different parameters", 409
            )
        return self._view(job)

    async def create(self, request: Any, idempotency_key: str) -> V:
        if not 1 <= len(idempotency_key) <= 200:
            raise DomainError("invalid_idempotency_key", "Idempotency-Key must be 1-200 characters")
        digest = hashlib.sha256(
            json.dumps(request.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        # Existing idempotent requests do not reroute when deployments change.
        async with self.sessions() as session:
            existing = await session.scalar(
                select(Job).where(Job.idempotency_key == idempotency_key)
            )
            if existing:
                return self._idempotent(existing, digest)
        data = {"text": request.text} if self.kind == "synthesis" else {}
        speech = SpeechRequest(self.kind, request.options.model_dump(), data)
        deployment = self.registry.select(speech)
        options = {**speech.options, "deployment_id": deployment.id}
        try:
            async with self.sessions.begin() as session:
                asset_id = getattr(request, "asset_id", None)
                if asset_id:
                    asset = await session.get(Asset, asset_id, with_for_update=True)
                    if not asset or not asset.ready or asset.deleted:
                        raise DomainError("asset_not_ready", "Upload a ready asset first", 409)
                    speech.duration_ms = asset.duration_ms or 0
                    deployment.adapter.validate(speech, size=asset.size)
                job = Job(
                    id=uid(),
                    asset_id=asset_id,
                    kind=self.kind,
                    deployment_id=deployment.id,
                    input=data,
                    options=options,
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                )
                session.add(job)
                await session.flush()
                session.add(self._attempt(job, deployment.snapshot()))
                session.add(Event(job_id=job.id, state="queued"))
                return self._view(job)
        except IntegrityError:
            async with self.sessions() as session:
                existing = await session.scalar(
                    select(Job).where(Job.idempotency_key == idempotency_key)
                )
                if not existing:
                    raise
                return self._idempotent(existing, digest)

    def _attempt(self, job: Job, snapshot: dict[str, Any]) -> Attempt:
        return Attempt(
            job_id=job.id,
            number=job.attempt,
            provider=snapshot["adapter"],
            region=snapshot["configuration"].get("region", "local"),
            deployment=snapshot,
            request={"options": job.options, "input": job.input, "asset_id": job.asset_id},
        )

    async def _load(self, session: AsyncSession, job_id: str, lock=False) -> Job:
        job = await session.get(Job, job_id, with_for_update=lock)
        if not job or job.kind != self.kind:
            raise DomainError("job_not_found", "Speech task not found", 404)
        return job

    async def get(self, job_id: str) -> V:
        async with self.sessions() as session:
            return self._view(await self._load(session, job_id))

    async def list(self, cursor: str | None = None, limit: int = 50) -> P:
        if not 1 <= limit <= 100:
            raise DomainError("invalid_limit", "Limit must be 1-100")
        async with self.sessions() as session:
            query = select(Job).where(Job.kind == self.kind).order_by(Job.id).limit(limit + 1)
            if cursor:
                query = query.where(Job.id > cursor)
            jobs = list((await session.scalars(query)).all())
        return self.page_type.model_validate(
            {
                "items": [self._view(j) for j in jobs[:limit]],
                "next_cursor": jobs[limit - 1].id if len(jobs) > limit else None,
            }
        )

    async def cancel(self, job_id: str) -> V:
        async with self.sessions.begin() as session:
            job = await self._load(session, job_id, True)
            if job.state in {"queued", "preparing"} and not job.provider_task_id:
                job.state = "cancelled"
                job.generation += 1
                job.lease_owner = job.lease_until = None
            elif job.state in {"submitting", "running", "finalizing", "needs_attention"}:
                job.state = "cancel_requested"
            job.updated_at = job.next_run_at = now()
            session.add(Event(job_id=job.id, state=job.state))
            return self._view(job)

    async def retry(self, job_id: str, acknowledge_duplicate_risk: bool = False) -> V:
        async with self.sessions() as session:
            before = await self._load(session, job_id)
            capture_key = before.capture_key
        receipt = await read_receipt(self.storage, capture_key)
        async with self.sessions.begin() as session:
            job = await self._load(session, job_id, True)
            if job.capture_key != capture_key:
                raise DomainError("job_changed", "Task changed; read its status again", 409)
            if job.state not in {"failed", "needs_attention", "cancelled"}:
                raise DomainError("not_retryable", "Task is not in a retryable state", 409)
            if job.lease_until and job.lease_until.timestamp() > now().timestamp():
                raise DomainError("worker_still_active", "Wait for the active worker lease", 409)
            if job.asset_id:
                asset = await session.get(Asset, job.asset_id, with_for_update=True)
                if not asset or asset.deleted:
                    raise DomainError(
                        "asset_not_found", "Original audio is no longer available", 409
                    )
            code = (job.error or {}).get("code")
            if (job.raw_key or job.result_url) and code != "result_expired":
                job.state = "finalizing"
            elif receipt and (receipt.get("kind") == "completed" or job.state == "needs_attention"):
                # A receipt may exist even when the DB checkpoint was lost. Always inspect it
                # before considering a second submission, including after an explicit retry.
                job.state = "submitting"
            elif job.provider_task_id and code in {
                "provider_unavailable",
                "provider_rate_limited",
                "invalid_provider_response",
            }:
                job.state = "running"
            else:
                if (
                    job.state == "needs_attention" or job.remote_may_run
                ) and not acknowledge_duplicate_risk:
                    raise DomainError(
                        "duplicate_risk",
                        "Explicitly acknowledge possible duplicate processing and charges",
                        409,
                    )
                previous = await session.get(Attempt, (job.id, job.attempt))
                if not previous:
                    raise DomainError(
                        "legacy_attempt", "Review and pin the historical deployment first", 409
                    )
                if not previous.deployment:
                    previous.deployment = self.registry.match_historical(
                        previous.provider, previous.region, previous.request
                    ).snapshot()
                self.registry.restore(previous.deployment)
                job.attempt += 1
                job.state = "queued"
                job.provider_task_id = job.result_url = job.result_key = job.raw_key = None
                job.audio_key = job.capture_key = None
                job.remote_may_run = False
                session.add(self._attempt(job, previous.deployment))
            job.generation += 1
            job.lease_owner = job.lease_until = None
            job.error, job.retry_count = None, 0
            job.updated_at = job.next_run_at = job.attempt_started_at = now()
            session.add(Event(job_id=job.id, state=job.state, code="manual_retry"))
            return self._view(job)

    async def result_data(self, job_id: str) -> dict[str, Any]:
        async with self.sessions() as session:
            job = await self._load(session, job_id)
            if job.state != "succeeded" or not job.result_key:
                raise DomainError("result_not_ready", "Speech task is not complete", 409)
        return await self.storage.read_json(job.result_key)

    async def delete(self, job_id: str):
        async with self.sessions.begin() as session:
            job = await self._load(session, job_id, True)
            if job.state in ACTIVE or job.remote_may_run:
                raise DomainError("job_in_use", "Task may still be running", 409)
            job.state, job.result_key = "failed", None
            job.raw_key = job.result_url = job.audio_key = job.capture_key = None
            job.input = {}
            job.error = {
                "code": "result_deleted",
                "message": "Results explicitly deleted",
                "retryable": False,
            }
            attempts = await session.scalars(select(Attempt).where(Attempt.job_id == job.id))
            for attempt in attempts:
                attempt.request = {"options": job.options, "asset_id": job.asset_id}
                attempt.capture_key = attempt.raw_key = attempt.result_key = None
            session.add(Event(job_id=job.id, state="failed", code="result_deleted"))
        await self.storage.delete_prefix(f"results/{job_id}/")
