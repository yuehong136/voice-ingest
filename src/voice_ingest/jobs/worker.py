import asyncio
import contextlib
import json
import logging
import random
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_ingest.media.probe import MediaProbe
from voice_ingest.media.service import UploadService
from voice_ingest.media.storage import S3Storage
from voice_ingest.providers.base import ASRProvider, SubmissionUnknown, normalize, validate_options
from voice_ingest.runtime.database import (
    Asset,
    Attempt,
    Event,
    Job,
    SchedulerLock,
    WorkerHeartbeat,
    now,
    uid,
)
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import ACTIVE, DomainError, TranscriptionOptions

logger = logging.getLogger("voice_ingest.worker")


class LeaseLost(Exception):
    pass


class Worker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        storage: S3Storage,
        provider: ASRProvider,
        probe: MediaProbe,
        settings: Settings,
    ):
        self.sessions, self.storage, self.provider = sessions, storage, provider
        self.probe, self.settings, self.id = probe, settings, uid()
        self.stopping = asyncio.Event()

    async def claim(self) -> Job | None:
        async with self.sessions.begin() as session:
            # A tiny scheduler lock makes provider slot reservation atomic across workers.
            scheduler = await session.scalar(
                select(SchedulerLock).where(SchedulerLock.id == 1).with_for_update()
            )
            if scheduler is None:
                raise RuntimeError("Scheduler lock missing; run database migrations")
            timestamp = now()
            slots = await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    or_(
                        Job.state.in_(
                            ["preparing", "submitting", "running", "finalizing", "cancel_requested"]
                        ),
                        Job.remote_may_run,
                    )
                )
            )
            eligible = set(ACTIVE)
            if (slots or 0) >= self.settings.max_inflight:
                eligible.discard("queued")
            query = (
                select(Job)
                .where(
                    or_(
                        Job.state.in_(eligible),
                        Job.state.in_(["cancelled", "failed"])
                        & Job.remote_may_run
                        & Job.provider_task_id.is_not(None),
                    ),
                    Job.next_run_at <= timestamp,
                    or_(Job.lease_until.is_(None), Job.lease_until < timestamp),
                )
                .order_by(Job.next_run_at, Job.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = await session.scalar(query)
            if not job:
                return None
            job.generation += 1
            job.lease_owner = self.id
            job.lease_until = timestamp + timedelta(seconds=self.settings.lease_seconds)
            if job.state == "queued":
                job.state = "preparing"
            await session.flush()
            return job

    async def checkpoint(
        self,
        claimed: Job,
        state: str,
        *,
        expected: str | None = None,
        delay: float = 0,
        **values: Any,
    ) -> bool:
        async with self.sessions.begin() as session:
            current = await session.get(Job, claimed.id, with_for_update=True)
            if (
                not current
                or current.generation != claimed.generation
                or current.lease_owner != self.id
                or not current.lease_until
                or current.lease_until.timestamp() <= now().timestamp()
            ):
                raise LeaseLost
            if expected and current.state != expected:
                return False
            # A cancellation arriving during provider I/O must not be overwritten.
            cancelled = current.state == "cancel_requested" and state != "cancelled"
            current.state = "cancel_requested" if cancelled else state
            for name, value in values.items():
                setattr(current, name, value)
                setattr(claimed, name, value)
            current.updated_at, current.next_run_at = now(), now() + timedelta(seconds=delay)
            attempt = await session.get(Attempt, (claimed.id, claimed.attempt))
            if attempt:
                for key in ("provider_task_id", "raw_key", "result_key"):
                    if key in values:
                        setattr(attempt, key, values[key])
            session.add(
                Event(
                    job_id=current.id, state=current.state, code=(current.error or {}).get("code")
                )
            )
            claimed.state = current.state
            return not cancelled

    async def _heartbeat(self, job: Job | None = None):
        async with self.sessions.begin() as session:
            await session.merge(WorkerHeartbeat(id=self.id, seen_at=now()))
            if job:
                await session.execute(
                    update(Job)
                    .where(
                        Job.id == job.id,
                        Job.generation == job.generation,
                        Job.lease_owner == self.id,
                        Job.lease_until > now(),
                    )
                    .values(lease_until=now() + timedelta(seconds=self.settings.lease_seconds))
                )

    async def _keep_alive(self, job: Job):
        while True:
            await asyncio.sleep(self.settings.lease_seconds / 3)
            await self._heartbeat(job)

    async def tick(self) -> bool:
        await self._heartbeat()
        job = await self.claim()
        if not job:
            return False
        heartbeat = asyncio.create_task(self._keep_alive(job))
        try:
            await self.process(job)
        except LeaseLost:
            logger.info("lease_lost job_id=%s", job.id)
        except SubmissionUnknown as exc:
            await self._safe_checkpoint(
                job, "needs_attention", error=exc.info.model_dump(), remote_may_run=True
            )
        except DomainError as exc:
            retries = job.retry_count + 1
            if exc.info.retryable and retries <= self.settings.max_retry_count:
                state = "preparing" if job.state == "submitting" else job.state
                await self._safe_checkpoint(
                    job,
                    state,
                    delay=min(300, 2**retries) + random.random(),
                    retry_count=retries,
                    error=exc.info.model_dump(),
                )
            else:
                await self._safe_checkpoint(job, "failed", delay=300, error=exc.info.model_dump())
        except Exception:
            # No exception traceback: network/client exceptions can contain secrets and URLs.
            logger.error("worker_failure job_id=%s stage=%s", job.id, job.state)
            error = {
                "code": "internal_error",
                "message": "Worker operation failed",
                "retryable": False,
            }
            state = "needs_attention" if job.state == "submitting" else "failed"
            await self._safe_checkpoint(
                job,
                state,
                error=error,
                remote_may_run=job.state == "submitting" or job.remote_may_run,
            )
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            async with self.sessions.begin() as session:
                await session.execute(
                    update(Job)
                    .where(
                        Job.id == job.id,
                        Job.generation == job.generation,
                        Job.lease_owner == self.id,
                    )
                    .values(lease_owner=None, lease_until=None)
                )
        return True

    async def _safe_checkpoint(self, job: Job, state: str, **values: Any):
        with contextlib.suppress(LeaseLost):
            await self.checkpoint(job, state, **values)

    async def process(self, job: Job):
        async with self.sessions() as session:
            asset = await session.get(Asset, job.asset_id)
            attempt = await session.get(Attempt, (job.id, job.attempt))
        assert asset and attempt
        if attempt.provider != self.provider.name or attempt.region != self.settings.aliyun_region:
            raise DomainError(
                "provider_configuration_changed",
                "Restore the provider configuration used by this task",
                409,
            )
        options = TranscriptionOptions.model_validate(job.options)
        if job.state in {"cancelled", "failed"} and job.remote_may_run:
            assert job.provider_task_id
            result = await self.provider.poll(job.provider_task_id)
            await self.checkpoint(
                job,
                job.state,
                remote_may_run=result.state == "pending",
                delay=min(60, self.settings.poll_seconds * 4),
            )
            return
        if job.state == "cancel_requested":
            remote_may_run = job.remote_may_run
            if job.provider_task_id and job.result_url is None:
                try:
                    remote_may_run = not await self.provider.cancel(job.provider_task_id)
                except DomainError:
                    remote_may_run = True
            await self.checkpoint(job, "cancelled", remote_may_run=remote_may_run)
            return
        if job.state == "submitting":
            raise SubmissionUnknown()
        elapsed = now().timestamp() - job.attempt_started_at.timestamp()
        if elapsed > self.settings.job_deadline_seconds:
            raise DomainError(
                "task_deadline", "Task deadline reached; inspect remote status before retry", 504
            )
        if job.state == "preparing":
            if not asset.media_info:
                info = await self.probe.inspect(asset.object_key, asset.sha256)
                async with self.sessions.begin() as session:
                    saved = await session.get(Asset, asset.id, with_for_update=True)
                    assert saved
                    saved.media_info, saved.duration_ms = info, info["duration_ms"]
                asset.media_info, asset.duration_ms = info, info["duration_ms"]
            validate_options(options, asset.duration_ms, asset.size, asset.media_info["format"])
            url = self.storage.sign_download(asset.object_key)
            if not await self.checkpoint(job, "submitting", expected="preparing", error=None):
                return
            task_id = await self.provider.submit(url, options, asset.duration_ms or 0)
            await self.checkpoint(
                job,
                "running",
                provider_task_id=task_id,
                remote_may_run=True,
                retry_count=0,
                delay=self.settings.poll_seconds,
            )
            return
        if job.state == "running":
            assert job.provider_task_id
            result = await self.provider.poll(job.provider_task_id)
            if result.state == "pending":
                await self.checkpoint(
                    job,
                    "running",
                    delay=self.settings.poll_seconds * random.uniform(1, 1.3),
                    retry_count=0,
                    error=None,
                )
            elif result.state == "succeeded":
                await self.checkpoint(
                    job,
                    "finalizing",
                    result_url=result.result_url,
                    remote_may_run=False,
                    retry_count=0,
                    error=None,
                )
            elif result.state == "cancelled":
                await self.checkpoint(job, "cancelled", remote_may_run=False)
            else:
                await self.checkpoint(
                    job,
                    "failed",
                    remote_may_run=False,
                    error={
                        "code": result.error_code or "provider_failed",
                        "message": "Provider could not transcribe this file",
                        "retryable": False,
                    },
                )
            return
        if job.state == "finalizing":
            prefix = f"results/{job.id}/{job.attempt}/{job.generation}"
            if job.raw_key:
                raw = await self.storage.read_json(job.raw_key)
            else:
                assert job.result_url
                raw = await self.provider.fetch(job.result_url)
                await self.storage.put(
                    f"{prefix}/raw.json", json.dumps(raw).encode(), "application/json"
                )
                if not await self.checkpoint(job, "finalizing", raw_key=f"{prefix}/raw.json"):
                    return
            transcript = normalize(
                raw,
                job_id=job.id,
                asset_id=asset.id,
                provider=self.provider.name,
                options=options,
                duration_ms=asset.duration_ms or 0,
            )
            result_key = f"{prefix}/transcript.json"
            await self.storage.put(
                result_key, transcript.model_dump_json().encode(), "application/json"
            )
            await self.checkpoint(
                job,
                "succeeded",
                result_key=result_key,
                result_url=None,
                retry_count=0,
                error=None,
                remote_may_run=False,
            )

    async def run(self):
        maintenance_at = 0.0
        while not self.stopping.is_set():
            try:
                worked = await self.tick()
                if now().timestamp() - maintenance_at > 60:
                    await UploadService(self.sessions, self.storage).cleanup()
                    maintenance_at = now().timestamp()
                if worked:
                    continue
            except Exception:
                logger.error("worker_loop_unavailable")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), timeout=1)
