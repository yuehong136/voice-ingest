import asyncio
import os
import signal

from voice_ingest.runtime.container import Runtime, configure_logging
from voice_ingest.runtime.settings import Settings


def serve():
    import uvicorn

    uvicorn.run(
        "voice_ingest.interfaces.http:create_app",
        factory=True,
        host=os.getenv("VOICE_HOST", "127.0.0.1"),
        port=int(os.getenv("VOICE_PORT", "18080")),
        access_log=False,
    )


async def run_worker():
    configure_logging()
    runtime = Runtime(Settings())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, runtime.worker.stopping.set)
    try:
        await runtime.worker.run()
    finally:
        await runtime.close()


def worker():
    asyncio.run(run_worker())
