"""Prepare provider-readable sources before the billable submission boundary."""

from typing import Protocol

from voice_ingest.media.storage import S3Storage
from voice_ingest.transcription.contracts import TranscriptionOptions


class SourcePreparer(Protocol):
    async def prepare(self, key: str, filename: str, options: TranscriptionOptions) -> str: ...


class SignedSource:
    def __init__(self, storage: S3Storage):
        self.storage = storage

    async def prepare(self, key: str, filename: str, options: TranscriptionOptions) -> str:
        return self.storage.sign_download(key)
