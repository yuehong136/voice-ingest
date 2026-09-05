from datetime import timedelta

import pytest
from sqlalchemy import select, update

from voice_ingest.jobs.worker import LeaseLost, Worker
from voice_ingest.providers.base import SubmissionUnknown
from voice_ingest.providers.mock import MockProvider
from voice_ingest.runtime.database import Attempt, Job, now
from voice_ingest.transcription.contracts import (
    CreateTranscription,
    DomainError,
    TranscriptionOptions,
)


async def due(env):
    async with env.sessions.begin() as session:
        await session.execute(update(Job).values(next_run_at=now() - timedelta(seconds=1)))


async def finish(env, job_id):
    for _ in range(8):
        await due(env)
        await env.worker.tick()
        job = await env.transcriptions.get(job_id)
        if job.state == "succeeded":
            return job
    pytest.fail(f"Job did not succeed: {job}")


async def test_idempotency_and_restart(env, asset):
    request = CreateTranscription(asset_id=asset)
    created = await env.transcriptions.create(request, "stable-key")
    repeated = await env.transcriptions.create(request, "stable-key")
    assert created.id == repeated.id
    with pytest.raises(DomainError, match="different parameters"):
        await env.transcriptions.create(
            CreateTranscription(asset_id=asset, options=TranscriptionOptions(diarization=True)),
            "stable-key",
        )
    await env.worker.tick()
    assert (await env.transcriptions.get(created.id)).state == "running"
    env.worker = Worker(env.sessions, env.storage, MockProvider(), env.worker.probe, env.settings)
    await finish(env, created.id)
    result = await env.transcriptions.result(created.id)
    assert result.duration_ms == 3_600_000
    assert result.segments[-1].end_ms == 3_600_000
    assert result.provider == "mock"
    async with env.sessions() as session:
        attempts = (await session.scalars(select(Attempt))).all()
    assert len(attempts) == 1
    assert attempts[0].raw_key and attempts[0].result_key


async def test_unknown_submit_is_not_retried(env, asset):
    class Unknown(MockProvider):
        calls = 0

        async def submit(self, *args):
            self.calls += 1
            raise SubmissionUnknown()

    provider = Unknown()
    env.worker.provider = provider
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "unknown")
    await env.worker.tick()
    assert (await env.transcriptions.get(job.id)).state == "needs_attention"
    await env.worker.tick()
    assert provider.calls == 1
    with pytest.raises(DomainError, match="acknowledge"):
        await env.transcriptions.retry(job.id)
    retried = await env.transcriptions.retry(job.id, True)
    assert retried.attempt == 2


async def test_crash_in_submitting_and_fencing(env, asset):
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "crash")
    claimed = await env.worker.claim()
    assert claimed
    await env.worker.checkpoint(claimed, "submitting")
    async with env.sessions.begin() as session:
        await session.execute(
            update(Job).where(Job.id == job.id).values(lease_until=now() - timedelta(seconds=1))
        )
    other = Worker(env.sessions, env.storage, env.provider, env.worker.probe, env.settings)
    recovered = await other.claim()
    assert recovered and recovered.generation > claimed.generation
    with pytest.raises(LeaseLost):
        await env.worker.checkpoint(claimed, "succeeded")
    with pytest.raises(SubmissionUnknown):
        await other.process(recovered)


async def test_cancel_during_submit_preserves_remote_id(env, asset):
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "cancel-race")

    class CancelDuringSubmit(MockProvider):
        async def submit(self, *args):
            await env.transcriptions.cancel(job.id)
            return await super().submit(*args)

    env.worker.provider = CancelDuringSubmit()
    await env.worker.tick()
    async with env.sessions() as session:
        saved = await session.get(Job, job.id)
        assert saved.state == "cancel_requested" and saved.provider_task_id
    await due(env)
    await env.worker.tick()
    cancelled = await env.transcriptions.get(job.id)
    assert cancelled.state == "cancelled" and not cancelled.remote_may_run


async def test_cancel_before_submit_never_calls_provider(env, asset):
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "cancel-before")

    class CancelProbe:
        async def inspect(self, *args):
            await env.transcriptions.cancel(job.id)
            return {"duration_ms": 1000, "format": "wav"}

    env.worker.probe = CancelProbe()
    await env.worker.tick()
    assert (await env.transcriptions.get(job.id)).state == "cancelled"


async def test_result_retry_does_not_resubmit(env, asset):
    class FlakyResult(MockProvider):
        submissions = 0
        downloads = 0

        async def submit(self, *args):
            self.submissions += 1
            return await super().submit(*args)

        async def fetch(self, *args):
            self.downloads += 1
            if self.downloads == 1:
                raise DomainError("result_download_failed", "Temporary failure", 502, True)
            return await super().fetch(*args)

    provider = FlakyResult()
    env.worker.provider = provider
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "fetch-retry")
    await finish(env, job.id)
    assert provider.submissions == 1 and provider.downloads == 2


async def test_max_inflight_and_delete_in_use(env, asset):
    for i in range(3):
        await env.transcriptions.create(CreateTranscription(asset_id=asset), str(i))
    first = await env.worker.claim()
    second = await env.worker.claim()
    assert first and second
    assert await env.worker.claim() is None
    with pytest.raises(DomainError, match="still use"):
        await env.uploads.delete_asset(asset)


async def test_deleted_results_stay_unavailable(env, asset):
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "delete")
    await finish(env, job.id)
    await env.transcriptions.export(job.id, "markdown")
    await env.transcriptions.delete(job.id)
    with pytest.raises(DomainError):
        await env.transcriptions.result(job.id)
    response = env.storage.internal.list_objects_v2(
        Bucket=env.settings.s3_bucket, Prefix=f"results/{job.id}/"
    )
    assert not response.get("Contents")


async def test_source_staging_retries_before_billable_submission(env, asset):
    class Source:
        calls = 0

        async def prepare(self, key, filename, options):
            self.calls += 1
            if self.calls == 1:
                raise DomainError("source_unavailable", "Retry source upload", 503, True)
            return "oss://temporary/staged-audio"

    source = Source()
    env.worker.source = source
    created = await env.transcriptions.create(CreateTranscription(asset_id=asset), "staging-retry")
    await env.worker.tick()
    current = await env.transcriptions.get(created.id)
    assert current.state == "preparing"
    async with env.sessions() as session:
        saved = await session.get(Job, created.id)
        assert saved.provider_task_id is None
    await finish(env, created.id)
    assert source.calls == 2


async def test_cancel_during_staging_does_not_submit_to_provider(env, asset):
    created = await env.transcriptions.create(CreateTranscription(asset_id=asset), "cancel-staging")

    class Source:
        async def prepare(self, key, filename, options):
            await env.transcriptions.cancel(created.id)
            return "oss://temporary/cancelled-audio"

    env.worker.source = Source()
    await env.worker.tick()
    assert (await env.transcriptions.get(created.id)).state == "cancelled"
    async with env.sessions() as session:
        saved = await session.get(Job, created.id)
        assert saved.provider_task_id is None
