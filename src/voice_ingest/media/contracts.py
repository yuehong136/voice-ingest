from datetime import datetime

from pydantic import Field

from voice_ingest.transcription.contracts import Contract

PART_SIZE = 16 * 1024 * 1024


class CreateUpload(Contract):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=2_000_000_000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class UploadedPart(Contract):
    number: int = Field(ge=1, le=10000)
    etag: str
    size: int


class UploadView(Contract):
    id: str
    asset_id: str
    state: str
    filename: str
    size: int
    sha256: str
    part_size: int = PART_SIZE
    expires_at: datetime
    parts: list[UploadedPart] = Field(default_factory=list)


class SignedPart(Contract):
    url: str
    expires_in: int
