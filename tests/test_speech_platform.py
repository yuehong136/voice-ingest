"""Behavior contracts for protocol-independent execution, recovery and routing."""

import hashlib
import io
import json
import wave
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from fastmcp import Client
from sqlalchemy import update

from voice_ingest.client import AsyncVoiceClient
from voice_ingest.interfaces.http import create_app
from voice_ingest.interfaces.local_mcp import create_local_mcp
from voice_ingest.interfaces.mcp import create_mcp
from voice_ingest.jobs.worker import LeaseLost, Worker
from voice_ingest.providers.base import PollResult
from voice_ingest.providers.registry import Deployment, Registry
from voice_ingest.providers.speech import Accepted, Completed, SpeechRequest
from voice_ingest.runtime.database import Attempt, Job, now
from voice_ingest.synthesis.contracts import CreateSynthesis, SynthesisOptions, Voice
from voice_ingest.transcription.contracts import (
    CreateTranscription,
    DomainError,
    ModelCapability,
    TranscriptionOptions,
)


def options(**kwargs):
    return SynthesisOptions(model="mock-tts", voice="mock-voice", format="wav", **kwargs)


async def test_every_application_http_route_is_v1(env):
    app = create_app(env.settings, env)
    assert all(route.path.startswith("/v1/") for route in app.routes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-api-key"},
    ) as http:
        models = (await http.get("/v1/models?capability=synthesis")).json()
        assert len(models) == 1 and models[0]["kind"] == "synthesis"
        assert (await http.get("/health/live")).status_code == 404


async def test_historical_attempt_recovery_matches_recorded_configuration(env, asset):
    created = await env.transcriptions.create(CreateTranscription(asset_id=asset), "historical")
    async with env.sessions.begin() as session:
        attempt = await session.get(Attempt, (created.id, 1))
        attempt.deployment = None
        attempt.request = {
            "options": attempt.request["options"],
            "asset_id": asset,
            "source_mode": "signed_url",
            "endpoint": "mock",
        }
    assert (await advance(env, created.id, env.transcriptions)).state == "succeeded"
    async with env.sessions() as session:
        attempt = await session.get(Attempt, (created.id, 1))
        assert attempt.deployment["id"] == "default"


async def advance(env, job_id, service=None):
    service = service or env.syntheses
    for _ in range(8):
        async with env.sessions.begin() as session:
            await session.execute(update(Job).values(next_run_at=now()))
        await env.worker.tick()
        job = await service.get(job_id)
        if job.state in {"succeeded", "failed", "needs_attention", "cancelled"}:
            return job
    pytest.fail("Task did not reach a terminal state")


async def test_synthesis_cross_entrypoints_and_private_audio(env):
    app = create_app(env.settings, env)
    async with AsyncVoiceClient(
        "http://test", "test-api-key", transport=httpx.ASGITransport(app)
    ) as sdk:
        models = await sdk.models()
        assert {m.kind for m in models} == {"transcription", "synthesis"}
        assert all(m.provider == "mock" for m in models)
        assert (await sdk.voices("mock-tts"))[0].id == "mock-voice"
        async with Client(create_mcp(env.transcriptions, env.syntheses)) as mcp:
            created = await mcp.call_tool(
                "submit_synthesis",
                {
                    "text": "Synthetic test text",
                    "options": options().model_dump(),
                    "idempotency_key": "cross-entrypoints",
                },
            )
            job_id = created.structured_content["id"]
            assert (await sdk.get_synthesis(job_id)).state == "queued"
            assert (await advance(env, job_id)).state == "succeeded"
            meta = await sdk.synthesis_result(job_id)
            audio = await sdk.synthesis_audio(job_id)
            assert hashlib.sha256(audio).hexdigest() == meta.sha256
            with wave.open(io.BytesIO(audio)) as decoded:
                assert decoded.getnframes() == 22050
            assert meta.audio_path == f"/v1/syntheses/{job_id}/audio"
            answer = await mcp.call_tool("get_synthesis_result", {"job_id": job_id})
            assert answer.structured_content["model"] == "mock-tts"
            assert "text" not in (await sdk.get_synthesis(job_id)).model_dump()
            assert not (await sdk.list()).items
            assert len((await sdk.list_syntheses()).items) == 1
            response = await sdk.http.get(f"v1/transcriptions/{job_id}")
            assert response.status_code == 404
            await sdk.delete_synthesis(job_id)
            assert (await sdk.http.get(f"v1/syntheses/{job_id}/audio")).status_code == 409
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as http:
        assert (await http.get(f"/v1/syntheses/{job_id}/audio")).status_code == 401


async def test_local_mcp_synthesis_uses_public_sdk(env, tmp_path):
    sdk = AsyncVoiceClient(
        "http://test", "test-api-key", transport=httpx.ASGITransport(create_app(env.settings, env))
    )
    async with Client(create_local_mcp(sdk, [tmp_path])) as local:
        result = await local.call_tool(
            "submit_synthesis",
            {
                "text": "local MCP test",
                "options": options().model_dump(),
                "idempotency_key": "local-tts",
            },
        )
        job_id = result.structured_content["id"]
        assert (await advance(env, job_id)).state == "succeeded"
        metadata = await local.call_tool("get_synthesis_result", {"job_id": job_id})
        assert metadata.structured_content["audio_path"] == f"/v1/syntheses/{job_id}/audio"


@pytest.mark.parametrize("kind", ["transcription", "synthesis"])
async def test_deleted_tasks_cannot_be_retried_or_recreated(env, asset, kind, monkeypatch):
    service = env.transcriptions if kind == "transcription" else env.syntheses
    request = (
        CreateTranscription(asset_id=asset)
        if kind == "transcription"
        else CreateSynthesis(text="deletion fixture", options=options())
    )
    created = await service.create(request, "deletion-tombstone")
    assert (await advance(env, created.id, service)).state == "succeeded"
    original_delete = env.storage.delete_prefix

    async def unavailable(prefix):
        raise DomainError("storage_unavailable", "Synthetic storage failure", 503, True)

    monkeypatch.setattr(env.storage, "delete_prefix", unavailable)
    with pytest.raises(DomainError, match="Synthetic storage failure"):
        await service.delete(created.id)
    for acknowledgement in (False, True):
        with pytest.raises(DomainError, match="Deleted tasks cannot be retried"):
            await service.retry(created.id, acknowledgement)
    repeated = await service.create(request, "deletion-tombstone")
    assert repeated.id == created.id and repeated.attempt == 1
    assert repeated.error.code == "result_deleted"
    assert await env.worker.claim() is None
    monkeypatch.setattr(env.storage, "delete_prefix", original_delete)
    await service.delete(created.id)
    await service.delete(created.id)
    assert not env.storage.internal.list_objects_v2(
        Bucket=env.storage.bucket, Prefix=f"results/{created.id}/"
    ).get("Contents")


async def test_delete_waits_for_worker_and_fences_expired_owner(env):
    created = await env.syntheses.create(
        CreateSynthesis(text="lease deletion", options=options()), "lease-delete"
    )
    claimed = await env.worker.claim()
    await env.worker.checkpoint(claimed, "failed")
    with pytest.raises(DomainError, match="active worker lease"):
        await env.syntheses.delete(created.id)
    async with env.sessions.begin() as session:
        await session.execute(
            update(Job).where(Job.id == created.id).values(lease_until=now() - timedelta(seconds=1))
        )
    await env.syntheses.delete(created.id)
    with pytest.raises(LeaseLost):
        await env.worker.checkpoint(claimed, "succeeded", result_key="stale-result")


async def test_completed_receipt_survives_lost_checkpoint_without_inference(env, monkeypatch):
    adapter = env.worker.registry.deployments["default"].adapter
    original_start = adapter.start
    calls = 0

    async def start(request):
        nonlocal calls
        calls += 1
        return await original_start(request)

    monkeypatch.setattr(adapter, "start", start)
    original_checkpoint = env.worker.checkpoint

    async def crash(claimed, state, **kwargs):
        if state == "finalizing":
            raise LeaseLost()
        return await original_checkpoint(claimed, state, **kwargs)

    monkeypatch.setattr(env.worker, "checkpoint", crash)
    created = await env.syntheses.create(
        CreateSynthesis(text="receipt", options=options()), "receipt"
    )
    await env.worker.tick()
    assert (await env.syntheses.get(created.id)).state == "submitting"
    env.worker = Worker(
        env.sessions,
        env.storage,
        env.worker.registry,
        env.worker.probe,
        env.settings,
    )
    assert (await advance(env, created.id)).state == "succeeded"
    assert calls == 1
    async with env.sessions() as session:
        attempt = await session.get(Attempt, (created.id, 1))
        assert attempt.deployment["revision"] == "1" and attempt.capture_key
        assert attempt.request["options"]["voice"] == "mock-voice"


async def test_normalization_failure_resumes_only_saved_audio(env, monkeypatch):
    adapter = env.worker.registry.deployments["default"].adapter
    original = adapter.normalize
    created = await env.syntheses.create(CreateSynthesis(text="saved", options=options()), "saved")
    await env.worker.tick()

    def failure(*args):
        raise DomainError("normalize_failed", "Result processing failed")

    monkeypatch.setattr(adapter, "normalize", failure)
    assert (await advance(env, created.id)).state == "failed"

    async def no_more_inference(*args):
        pytest.fail("Persisted audio must not be synthesized again")

    monkeypatch.setattr(adapter, "start", no_more_inference)
    monkeypatch.setattr(adapter, "normalize", original)
    assert (await env.syntheses.retry(created.id)).attempt == 1
    assert (await advance(env, created.id)).state == "succeeded"


async def test_storage_marker_failure_recovers_complete_objects(env, monkeypatch):
    original_put = env.storage.put
    adapter = env.worker.registry.deployments["default"].adapter
    original_start = adapter.start
    calls = 0
    failed = False

    async def start(request):
        nonlocal calls
        calls += 1
        return await original_start(request)

    async def put(key, body, content_type):
        nonlocal failed
        if key.endswith("/receipt.json") and not failed:
            failed = True
            raise DomainError("storage_unavailable", "Simulated marker failure", 503, True)
        await original_put(key, body, content_type)

    monkeypatch.setattr(adapter, "start", start)
    monkeypatch.setattr(env.storage, "put", put)
    created = await env.syntheses.create(
        CreateSynthesis(text="recover marker", options=options()), "marker"
    )
    assert (await advance(env, created.id)).state == "succeeded"
    assert calls == 1 and failed


async def test_retry_receipt_inspection_racing_with_delete_is_read_only(env, monkeypatch):
    created = await env.syntheses.create(
        CreateSynthesis(text="read-only recovery", options=options()), "inspect-delete"
    )
    assert (await advance(env, created.id)).state == "succeeded"
    async with env.sessions.begin() as session:
        job = await session.get(Job, created.id)
        job.state = "failed"
        capture_key = job.capture_key
    await env.storage.delete(capture_key)
    original = env.storage.read_bytes
    raced = False

    async def read_then_delete(key, limit):
        nonlocal raced
        data = await original(key, limit)
        if key.endswith("/audio") and not raced:
            raced = True
            await env.syntheses.delete(created.id)
        return data

    monkeypatch.setattr(env.storage, "read_bytes", read_then_delete)
    with pytest.raises(DomainError):
        await env.syntheses.retry(created.id)
    assert raced
    assert not env.storage.internal.list_objects_v2(
        Bucket=env.storage.bucket, Prefix=f"results/{created.id}/"
    ).get("Contents")


@pytest.mark.parametrize("audio", [None, b"", b"truncated"])
async def test_incomplete_audio_cannot_publish(env, monkeypatch, audio):
    adapter = env.worker.registry.deployments["default"].adapter

    async def incomplete(request):
        return Completed({"complete": False}, audio)

    class RejectProbe:
        async def inspect(self, *args):
            raise DomainError("invalid_audio", "Cannot decode incomplete audio")

    monkeypatch.setattr(adapter, "start", incomplete)
    env.worker.probe = RejectProbe()
    created = await env.syntheses.create(
        CreateSynthesis(text="partial", options=options()), "partial"
    )
    assert (await advance(env, created.id)).state != "succeeded"
    with pytest.raises(DomainError):
        await env.syntheses.audio(created.id)


async def test_synthesis_cancel_during_stream_saves_complete_output_but_does_not_publish(
    env, monkeypatch
):
    adapter = env.worker.registry.deployments["default"].adapter
    original = adapter.start
    created = await env.syntheses.create(
        CreateSynthesis(text="cancel", options=options()), "cancel"
    )

    async def cancel(request):
        await env.syntheses.cancel(created.id)
        return await original(request)

    monkeypatch.setattr(adapter, "start", cancel)
    job = await advance(env, created.id)
    assert job.state == "cancelled" and not job.remote_may_run
    with pytest.raises(DomainError):
        await env.syntheses.audio(job.id)
    assert (await env.syntheses.retry(job.id)).attempt == 1
    assert (await advance(env, job.id)).state == "succeeded"


async def test_deployment_capacity_configuration_pinning_and_local_policy(env):
    base = env.worker.registry.deployments["default"]
    cloud = replace(base, id="cloud", location="cloud", max_inflight=1)
    local = replace(base, id="local", location="local", max_inflight=1)
    registry = Registry([cloud, local])
    env.worker.registry = env.syntheses.registry = registry
    with pytest.raises(DomainError, match="explicit deployment"):
        await env.syntheses.create(
            CreateSynthesis(text="ambiguous", options=options()), "ambiguous"
        )
    with pytest.raises(DomainError, match="No deployment"):
        await env.syntheses.create(
            CreateSynthesis(
                text="private", options=options(deployment_id="cloud", routing="local_only")
            ),
            "private",
        )
    created = []
    for deployment in ("cloud", "cloud", "local", "local"):
        created.append(
            await env.syntheses.create(
                CreateSynthesis(text="capacity", options=options(deployment_id=deployment)),
                f"capacity-{len(created)}",
            )
        )
    claims = [await env.worker.claim(), await env.worker.claim()]
    assert {c.deployment_id for c in claims} == {"cloud", "local"}
    assert await env.worker.claim() is None
    cloud.configuration = {**cloud.configuration, "endpoint": "changed"}
    claimed = next(c for c in claims if c.deployment_id == "cloud")
    with pytest.raises(DomainError, match="Restore the deployment revision"):
        await env.worker.process(claimed)
    # Idempotent lookup still returns the original attempt despite a routing change.
    repeated = await env.syntheses.create(
        CreateSynthesis(text="capacity", options=options(deployment_id="cloud")), "capacity-0"
    )
    assert repeated.id == created[0].id


class IndependentAdapter:
    """Does not inherit or emit the Aliyun result schema."""

    name = "independent-test"

    def __init__(self, asynchronous=False):
        self.asynchronous = asynchronous
        self.starts = 0

    def models(self):
        return [
            ModelCapability(
                id="independent-asr",
                provider=self.name,
                execution="direct",
                diarization=False,
                context=False,
            )
        ]

    def voices(self, model) -> list[Voice]:
        return []

    def validate(self, request: SpeechRequest, **kwargs):
        if request.options.get("diarization"):
            raise DomainError("unsupported_diarization", "No diarization support")

    async def start(self, request):
        self.starts += 1
        return (
            Accepted("independent-remote", {"accepted": True})
            if self.asynchronous
            else Completed({"words": "independent result"})
        )

    async def poll(self, task_id):
        return PollResult("succeeded", "opaque-independent-reference")

    async def fetch(self, reference):
        assert reference == "opaque-independent-reference"
        return Completed({"words": "independent result"})

    def normalize(self, raw, request, context):
        return dict(
            job_id=context["job_id"],
            asset_id=context["asset_id"],
            provider=self.name,
            model="independent-asr",
            duration_ms=request.duration_ms,
            text=raw["words"],
            segments=[],
            warnings=["no_timestamps"],
        )

    async def cancel(self, task_id):
        return False

    async def close(self):
        pass


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_independent_adapter_direct_and_remote_without_scheduler_changes(
    env, asset, asynchronous
):
    adapter = IndependentAdapter(asynchronous)
    registry = Registry([Deployment("independent", adapter, location="local")])
    env.worker.registry = env.transcriptions.registry = registry
    with pytest.raises(DomainError, match="No diarization"):
        await env.transcriptions.create(
            CreateTranscription(
                asset_id=asset,
                options=TranscriptionOptions(model="independent-asr", diarization=True),
            ),
            "unsupported",
        )
    assert adapter.starts == 0
    created = await env.transcriptions.create(
        CreateTranscription(
            asset_id=asset,
            options=TranscriptionOptions(model="independent-asr", routing="local_only"),
        ),
        "independent",
    )
    assert (await advance(env, created.id, env.transcriptions)).state == "succeeded"
    assert (await env.transcriptions.result(created.id)).text == "independent result"
    assert adapter.starts == 1


@pytest.mark.parametrize(
    "ending", ["task-finished", "task-failed", "disconnect", "wrong-id", "empty"]
)
async def test_aliyun_stream_protocol_requires_matching_completion(
    env, monkeypatch, caplog, ending
):
    from voice_ingest.providers import aliyun_tts

    class Socket:
        sent = []
        sequence = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, packet):
            self.sent.append(json.loads(packet))

        async def recv(self):
            self.sequence += 1
            task_id = self.sent[0]["header"]["task_id"]
            if self.sequence == 1:
                return json.dumps({"header": {"event": "task-started", "task_id": task_id}})
            if self.sequence == 2 and ending != "empty":
                return b"audio-frame"
            if ending == "disconnect":
                raise ConnectionError("secret transport URL")
            return json.dumps(
                {
                    "header": {
                        "event": "task-finished" if ending in {"wrong-id", "empty"} else ending,
                        "task_id": "wrong" if ending == "wrong-id" else task_id,
                    }
                }
            )

    socket = Socket()
    monkeypatch.setattr(aliyun_tts, "connect", lambda *args, **kwargs: socket)
    provider = aliyun_tts.AliyunTTS(env.settings)
    if ending == "task-finished":
        result = await provider.synthesize("private-body-canary", SynthesisOptions())
        assert result.audio == b"audio-frame" and result.raw["complete"]
    else:
        with pytest.raises(DomainError):
            await provider.synthesize("private-body-canary", SynthesisOptions())
    assert [p["header"]["action"] for p in socket.sent[-3:]] == [
        "run-task",
        "continue-task",
        "finish-task",
    ]
    assert "private-body-canary" not in caplog.text
    assert "secret transport URL" not in caplog.text
