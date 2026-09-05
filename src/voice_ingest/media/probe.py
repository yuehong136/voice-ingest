import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from voice_ingest.media.storage import S3Storage
from voice_ingest.transcription.contracts import DomainError


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class MediaProbe:
    def __init__(self, storage: S3Storage, binary: str):
        self.storage = storage
        self.binary = binary

    async def inspect(self, key: str, expected_hash: str) -> dict[str, Any]:
        # Disk-backed input avoids putting hours of audio in RAM and allows a real content hash.
        with tempfile.TemporaryDirectory(prefix="voice-probe-") as directory:
            path = Path(directory) / "audio"
            await self.storage.download(key, path)
            actual = await asyncio.to_thread(file_hash, path)
            if actual != expected_hash:
                raise DomainError("checksum_mismatch", "Uploaded content does not match SHA-256")
            try:
                process = await asyncio.create_subprocess_exec(
                    self.binary,
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-show_entries",
                    "format=format_name,duration:stream=codec_type,codec_name,sample_rate,channels,duration",
                    "-of",
                    "json",
                    str(path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except FileNotFoundError:
                raise DomainError("ffprobe_missing", "ffprobe must be installed", 503) from None
            try:
                async with asyncio.timeout(60):
                    output, _ = await process.communicate()
            except BaseException:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            if process.returncode != 0:
                raise DomainError("invalid_audio", "Cannot decode audio metadata")
            info = json.loads(output)
            audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
            duration = info.get("format", {}).get("duration")
            if not audio or duration is None:
                raise DomainError("invalid_audio", "Audio stream and duration are required")
            duration_ms = int(float(duration) * 1000)
            if duration_ms <= 0:
                raise DomainError("invalid_audio", "Audio duration must be positive")
            return {
                "duration_ms": duration_ms,
                "format": info["format"]["format_name"],
                "streams": audio,
                "sha256_verified": True,
            }
