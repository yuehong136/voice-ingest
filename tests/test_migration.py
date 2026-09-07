"""Incremental upgrade retains old assets, attempts and results in an isolated schema."""

import os
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from test_integration import migrate_schema

from voice_ingest.runtime.database import Base, now

pytestmark = pytest.mark.integration


async def test_incremental_upgrade_preserves_data_and_matches_models():
    url = os.getenv("VOICE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated test database required")
    assert url.split("?")[0].endswith("/voice_test")
    schema = "voice_migration_" + uuid4().hex
    bootstrap = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: migrate_schema(c, "0001"))

            def seed(c):
                metadata = MetaData()
                assets = Table("assets", metadata, autoload_with=c)
                jobs = Table("jobs", metadata, autoload_with=c)
                attempts = Table("attempts", metadata, autoload_with=c)
                c.execute(
                    assets.insert().values(
                        id="old-asset",
                        filename="retained.wav",
                        size=10,
                        sha256="0" * 64,
                        object_key="retained/source",
                        ready=True,
                        deleted=False,
                        created_at=now(),
                    )
                )
                c.execute(
                    jobs.insert().values(
                        id="old-job",
                        asset_id="old-asset",
                        state="succeeded",
                        options={"model": "fun-asr"},
                        idempotency_key="historical-key",
                        request_digest="1" * 64,
                        attempt=1,
                        provider_task_id="retained-remote",
                        result_key="retained/result",
                        raw_key="retained/raw",
                        remote_may_run=False,
                        generation=7,
                        next_run_at=now(),
                        retry_count=0,
                        created_at=now(),
                        updated_at=now(),
                        attempt_started_at=now(),
                    )
                )
                c.execute(
                    attempts.insert().values(
                        job_id="old-job",
                        number=1,
                        provider="aliyun",
                        region="beijing",
                        request={"options": {"model": "fun-asr"}},
                        created_at=now(),
                    )
                )

            await connection.run_sync(seed)
            await connection.run_sync(migrate_schema)

            def verify(c):
                jobs = Base.metadata.tables["jobs"]
                row = c.execute(select(jobs).where(jobs.c.id == "old-job")).mappings().one()
                assert row["result_key"] == "retained/result" and row["generation"] == 7
                assert row["kind"] == "transcription" and row["deployment_id"] == "default"
                assert row["input"] == {} and row["asset_id"] == "old-asset"
                assert compare_metadata(MigrationContext.configure(c), Base.metadata) == []

            await connection.run_sync(verify)
    finally:
        await engine.dispose()
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()
