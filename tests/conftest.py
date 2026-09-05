import hashlib
from types import SimpleNamespace

import httpx
import pytest
from moto import mock_aws
from pydantic import SecretStr

from voice_ingest.jobs.worker import Worker
from voice_ingest.media.service import UploadService
from voice_ingest.media.storage import S3Storage
from voice_ingest.providers.mock import MockProvider
from voice_ingest.runtime.database import Asset, Base, SchedulerLock, database, uid
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.service import TranscriptionService


class FixedProbe:
    async def inspect(self, key, expected_hash):
        return {"duration_ms": 3_600_000, "format": "wav", "sha256_verified": True}


@pytest.fixture
async def env(tmp_path):
    settings = Settings(
        _env_file=None,
        api_key=SecretStr("test-api-key"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        allow_sqlite_tests=True,
        s3_endpoint="https://s3.amazonaws.com",
        s3_public_endpoint="https://s3.amazonaws.com",
        s3_access_key=SecretStr("testing"),
        s3_secret_key=SecretStr("testing"),
        poll_seconds=0.1,
        enable_mcp=False,
    )
    engine, sessions = database(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions.begin() as session:
        session.add(SchedulerLock(id=1))
    with mock_aws():
        storage = S3Storage(settings)
        storage.internal.create_bucket(Bucket=settings.s3_bucket)
        provider = MockProvider()
        transcriptions = TranscriptionService(sessions, storage, settings)
        uploads = UploadService(sessions, storage)
        worker = Worker(sessions, storage, provider, FixedProbe(), settings)
        yield SimpleNamespace(
            settings=settings,
            engine=engine,
            sessions=sessions,
            storage=storage,
            provider=provider,
            transcriptions=transcriptions,
            uploads=uploads,
            worker=worker,
        )
        await storage.close()
    await engine.dispose()


@pytest.fixture
async def asset(env):
    asset_id = uid()
    data = b"test recording"
    async with env.sessions.begin() as session:
        session.add(
            Asset(
                id=asset_id,
                filename="meeting.wav",
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                object_key=f"audio/{asset_id}/source",
                ready=True,
            )
        )
    await env.storage.put(f"audio/{asset_id}/source", data, "audio/wav")
    return asset_id


def upload_transport(env):
    from urllib.parse import parse_qs, urlparse

    async def handler(request):
        assert "authorization" not in request.headers
        parsed = urlparse(str(request.url))
        query = parse_qs(parsed.query)
        _, bucket, key = parsed.path.split("/", 2)
        result = env.storage.internal.upload_part(
            Bucket=bucket,
            Key=key,
            UploadId=query["uploadId"][0],
            PartNumber=int(query["partNumber"][0]),
            Body=await request.aread(),
        )
        return httpx.Response(200, headers={"ETag": result["ETag"]})

    return httpx.MockTransport(handler)
