import logging

from voice_ingest.jobs.worker import Worker
from voice_ingest.media.probe import MediaProbe
from voice_ingest.media.service import UploadService
from voice_ingest.media.storage import S3Storage
from voice_ingest.runtime.database import database
from voice_ingest.runtime.deployments import create_registry
from voice_ingest.runtime.settings import Settings
from voice_ingest.synthesis.service import SynthesisService
from voice_ingest.transcription.service import TranscriptionService


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # URL-bearing framework/network log records are never emitted by the service.
    for name in (
        "httpx",
        "httpcore",
        "httpx2",
        "httpcore2",
        "botocore",
        "boto3",
        "s3transfer",
        "sqlalchemy.engine",
        "websockets",
        "fastmcp",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine, self.sessions = database(settings.database_url)
        self.storage = S3Storage(settings)
        self.registry = create_registry(settings, self.storage)
        first = next(iter(self.registry.deployments.values()))
        self.provider = first.adapter
        self.uploads = UploadService(self.sessions, self.storage)
        self.transcriptions = TranscriptionService(
            self.sessions, self.storage, settings, self.registry
        )
        self.syntheses = SynthesisService(self.sessions, self.storage, settings, self.registry)
        self.worker = Worker(
            self.sessions,
            self.storage,
            self.registry,
            MediaProbe(self.storage, settings.ffprobe_binary),
            settings,
        )

    async def close(self):
        for deployment in self.registry.deployments.values():
            await deployment.adapter.close()
        await self.storage.close()
        await self.engine.dispose()
