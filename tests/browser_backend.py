"""Dedicated synthetic browser backend; refuses application resources or paid providers."""

import asyncio

import uvicorn
from botocore.exceptions import ClientError
from test_integration import migrate_schema

from voice_ingest.interfaces.http import create_app
from voice_ingest.runtime.container import Runtime
from voice_ingest.runtime.settings import Settings


async def main():
    settings = Settings(_env_file=None)
    if (
        settings.provider != "mock"
        or settings.deployments_file
        or not settings.database_url.endswith("/voice_test")
        or settings.s3_bucket != "voice-browser-test"
    ):
        raise RuntimeError("Browser tests require dedicated synthetic resources")
    runtime = Runtime(settings)
    async with runtime.engine.begin() as connection:
        await connection.run_sync(migrate_schema)
    try:
        await runtime.storage.health()
    except Exception:
        try:
            await runtime.storage._call("create_bucket")
        except ClientError:
            raise RuntimeError("Cannot prepare isolated browser storage") from None
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, runtime),
            host="0.0.0.0",
            port=18080,
            access_log=False,
            log_level="warning",
        )
    )
    worker = asyncio.create_task(runtime.worker.run())
    try:
        await server.serve()
    finally:
        runtime.worker.stopping.set()
        await worker
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
