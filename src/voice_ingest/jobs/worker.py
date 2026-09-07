import asyncio
import contextlib
import hashlib
import json
import logging
import random
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_ingest.jobs.receipts import read_receipt
from voice_ingest.media.probe import MediaProbe
from voice_ingest.media.service import UploadService
from voice_ingest.media.source import SignedSource, SourcePreparer
from voice_ingest.media.storage import S3Storage
from voice_ingest.providers.base import SubmissionUnknown
from voice_ingest.providers.registry import Registry
from voice_ingest.providers.speech import Accepted, Completed, SpeechRequest
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
        registry: Registry,
        probe: MediaProbe,
        settings: Settings,
        source: SourcePreparer | None = None,
    ):
        self.sessions, self.storage, self.registry = sessions, storage, registry
        self.probe, self.settings, self.id = probe, settings, uid()
        self.source = source or SignedSource(storage)
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
            # Capacity counts unresolved submissions too and is isolated per deployment.
            available = []
            for deployment in self.registry.deployments.values():
                slots = await session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.deployment_id == deployment.id,
                        or_(
                            Job.state.in_(
                                [
                                    "preparing",
                                    "submitting",
                                    "running",
                                    "finalizing",
                                    "cancel_requested",
                                ]
                            ),
                            Job.remote_may_run,
                        ),
                    )
                )
                if (slots or 0) < deployment.max_inflight:
                    available.append(deployment.id)
            eligible = set(ACTIVE) - {"queued"}
            query = (
                select(Job)
                .where(
                    or_(
                        Job.state.in_(eligible),
                        (Job.state == "queued") & Job.deployment_id.in_(available),
                        (Job.state == "queued")
                        & Job.deployment_id.not_in(list(self.registry.deployments)),
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
                for key in ("provider_task_id", "raw_key", "result_key", "capture_key"):
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
                state = job.state
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

    async def _receipt(self, job: Job) -> dict[str, Any] | None:
        return await read_receipt(self.storage, job.capture_key)

    async def _save_outcome(self, job: Job, outcome: Accepted | Completed):
        assert job.capture_key
        prefix = job.capture_key.removesuffix("/receipt.json")
        raw_key = f"{prefix}/raw.json"
        raw_bytes = json.dumps(outcome.raw).encode()
        receipt: dict[str, Any] = {"job_id": job.id, "attempt": job.attempt, "raw_key": raw_key}
        receipt["raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        if isinstance(outcome, Accepted):
            receipt.update(kind="accepted", task_id=outcome.task_id)
        else:
            receipt["kind"] = "completed"
            if outcome.audio is not None:
                if not outcome.audio or len(outcome.audio) > 64 * 1024 * 1024:
                    raise DomainError("invalid_audio", "Audio result is empty or too large")
                audio_key = f"{prefix}/audio"
                receipt.update(
                    audio_key=audio_key,
                    size=len(outcome.audio),
                    sha256=hashlib.sha256(outcome.audio).hexdigest(),
                )
        await self.storage.put(
            f"{prefix}/manifest.json", json.dumps(receipt).encode(), "application/json"
        )
        await self.storage.put(raw_key, raw_bytes, "application/json")
        if isinstance(outcome, Completed) and outcome.audio is not None:
            await self.storage.put(receipt["audio_key"], outcome.audio, "application/octet-stream")
        # Receipt is the commit marker, written only after every complete object is durable.
        await self.storage.put(job.capture_key, json.dumps(receipt).encode(), "application/json")
        await self._apply_receipt(job, receipt)

    async def _apply_receipt(self, job: Job, receipt: dict[str, Any]):
        if receipt.get("job_id") != job.id or receipt.get("attempt") != job.attempt:
            raise DomainError("invalid_receipt", "Result receipt does not match this attempt")
        if receipt["kind"] == "accepted":
            await self.checkpoint(
                job,
                "running",
                provider_task_id=receipt["task_id"],
                remote_may_run=True,
                retry_count=0,
                error=None,
                delay=self.settings.poll_seconds,
            )
        elif receipt["kind"] == "completed":
            await self.checkpoint(
                job,
                "finalizing",
                raw_key=receipt["raw_key"],
                audio_key=receipt.get("audio_key"),
                remote_may_run=False,
                retry_count=0,
                error=None,
            )
        else:
            raise DomainError("invalid_receipt", "Unknown result receipt kind")

    async def process(self, job: Job):
        async with self.sessions() as session:
            asset = await session.get(Asset, job.asset_id) if job.asset_id else None
            attempt = await session.get(Attempt, (job.id, job.attempt))
        assert attempt
        if not attempt.deployment:
            historical = self.registry.match_historical(
                attempt.provider, attempt.region, attempt.request
            )
            snapshot = historical.snapshot()
            async with self.sessions.begin() as session:
                current = await session.get(Job, job.id, with_for_update=True)
                if (
                    not current
                    or current.generation != job.generation
                    or current.lease_owner != self.id
                    or not current.lease_until
                    or current.lease_until <= now()
                ):
                    raise LeaseLost
                saved_attempt = await session.get(Attempt, (job.id, job.attempt))
                assert saved_attempt
                saved_attempt.deployment = snapshot
            attempt.deployment = snapshot
        deployment = self.registry.restore(attempt.deployment)
        adapter = deployment.adapter
        request = SpeechRequest(
            job.kind,
            attempt.request["options"],
            attempt.request.get("input", {}),
            duration_ms=(asset.duration_ms or 0) if asset else 0,
        )
        if job.state in {"cancelled", "failed"} and job.remote_may_run:
            assert job.provider_task_id
            result = await adapter.poll(job.provider_task_id)
            await self.checkpoint(
                job,
                job.state,
                remote_may_run=result.state == "pending",
                delay=min(60, self.settings.poll_seconds * 4),
            )
            return
        if job.state == "cancel_requested":
            receipt = await self._receipt(job)
            if receipt:
                await self._apply_receipt(job, receipt)
            remote_may_run = job.remote_may_run
            if job.provider_task_id and job.result_url is None and remote_may_run:
                try:
                    remote_may_run = not await adapter.cancel(job.provider_task_id)
                except DomainError:
                    remote_may_run = True
            await self.checkpoint(job, "cancelled", remote_may_run=remote_may_run)
            return
        if job.state == "submitting":
            receipt = await self._receipt(job)
            if not receipt:
                raise SubmissionUnknown()
            await self._apply_receipt(job, receipt)
            return
        elapsed = now().timestamp() - job.attempt_started_at.timestamp()
        if elapsed > self.settings.job_deadline_seconds and job.state != "finalizing":
            raise DomainError(
                "task_deadline", "Task deadline reached; inspect remote status before retry", 504
            )
        if job.state == "preparing":
            if asset:
                if not asset.media_info:
                    info = await self.probe.inspect(asset.object_key, asset.sha256)
                    async with self.sessions.begin() as session:
                        current = await session.get(Job, job.id, with_for_update=True)
                        if (
                            not current
                            or current.generation != job.generation
                            or current.lease_owner != self.id
                            or not current.lease_until
                            or current.lease_until.timestamp() <= now().timestamp()
                        ):
                            raise LeaseLost
                        saved = await session.get(Asset, asset.id, with_for_update=True)
                        assert saved
                        saved.media_info, saved.duration_ms = info, info["duration_ms"]
                    asset.media_info, asset.duration_ms = info, info["duration_ms"]
                request.duration_ms = asset.duration_ms or 0
                adapter.validate(request, size=asset.size, format_name=asset.media_info["format"])
                source = deployment.source or self.source
                request.source_url = await source.prepare(
                    asset.object_key,
                    asset.filename,
                    TranscriptionOptions.model_validate(request.options),
                )
            else:
                adapter.validate(request)
            prefix = f"results/{job.id}/{job.attempt}/{job.generation}"
            if not await self.checkpoint(
                job,
                "submitting",
                expected="preparing",
                error=None,
                capture_key=f"{prefix}/receipt.json",
                remote_may_run=True,
            ):
                return
            try:
                outcome = await adapter.start(request)
            except SubmissionUnknown as exc:
                await self._capture_failure(job, exc)
                raise
            except DomainError as exc:
                await self._capture_failure(job, exc)
                # Only explicit pre-submission/rejection errors permit automatic retry.
                await self.checkpoint(
                    job,
                    "preparing" if exc.info.retryable else "failed",
                    capture_key=None,
                    remote_may_run=False,
                )
                raise
            await self._save_outcome(job, outcome)
            return
        if job.state == "running":
            assert job.provider_task_id
            result = await adapter.poll(job.provider_task_id)
            if result.raw:
                await self.storage.put(
                    f"results/{job.id}/{job.attempt}/{job.generation}/poll.json",
                    json.dumps(result.raw).encode(),
                    "application/json",
                )
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
                        "message": "Provider task failed",
                        "retryable": False,
                    },
                )
            return
        if job.state == "finalizing":
            prefix = f"results/{job.id}/{job.attempt}/{job.generation}"
            if not job.raw_key:
                receipt = await self._receipt(job)
                if receipt and receipt.get("kind") == "completed":
                    await self._apply_receipt(job, receipt)
                    if job.state == "cancel_requested":
                        return
            if not job.raw_key:
                assert job.result_url
                # Persist complete fetched output with the same receipt mechanism.
                await self.checkpoint(job, "finalizing", capture_key=f"{prefix}/receipt.json")
                await self._save_outcome(job, await adapter.fetch(job.result_url))
                if job.state == "cancel_requested":
                    return
            assert job.raw_key
            raw = await self.storage.read_json(job.raw_key)
            context: dict[str, Any] = {
                "job_id": job.id,
                "asset_id": job.asset_id,
                "deployment_id": deployment.id,
                "deployment_revision": deployment.revision,
            }
            if job.kind == "synthesis":
                receipt = await self._receipt(job)
                if not receipt or not job.audio_key:
                    raise DomainError("incomplete_audio", "Complete audio receipt is required")
                info = await self.probe.inspect(job.audio_key, receipt["sha256"])
                expected_format = request.options["format"]
                if expected_format not in info["format"].split(",") or info["duration_ms"] <= 0:
                    raise DomainError("invalid_audio", "Audio does not match the requested format")
                streams = info.get("streams", [])
                if (
                    len(streams) != 1
                    or int(streams[0].get("sample_rate", 0)) != request.options["sample_rate"]
                ):
                    raise DomainError(
                        "invalid_audio", "Audio sample rate does not match the request"
                    )
                context.update(
                    size=receipt["size"], sha256=receipt["sha256"], duration_ms=info["duration_ms"]
                )
            normalized = adapter.normalize(raw, request, context)
            result_key = f"{prefix}/result.json"
            await self.storage.put(result_key, json.dumps(normalized).encode(), "application/json")
            await self.checkpoint(
                job,
                "succeeded",
                result_key=result_key,
                result_url=None,
                retry_count=0,
                error=None,
                remote_may_run=False,
            )

    async def _capture_failure(self, job: Job, error: DomainError):
        if error.raw is not None and job.capture_key:
            prefix = job.capture_key.removesuffix("/receipt.json")
            await self.storage.put(
                f"{prefix}/failure.json", json.dumps(error.raw).encode(), "application/json"
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
