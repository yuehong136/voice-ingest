"""Durable output commit markers shared by Worker recovery and explicit retry."""

import hashlib
import json
from typing import Any

from voice_ingest.jobs.contracts import DomainError
from voice_ingest.media.storage import S3Storage


async def read_receipt(storage: S3Storage, key: str | None) -> dict[str, Any] | None:
    if not key:
        return None
    try:
        return await storage.read_json(key)
    except DomainError as exc:
        if exc.info.code != "storage_not_found":
            raise
    # The final marker can fail after complete raw/audio writes. Verify the intent's
    # digests before restoring that marker; a manifest alone never proves completion.
    prefix = key.removesuffix("/receipt.json")
    try:
        manifest = await storage.read_json(f"{prefix}/manifest.json")
        raw = await storage.read_bytes(manifest["raw_key"], 32 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != manifest["raw_sha256"]:
            return None
        if manifest.get("audio_key"):
            audio = await storage.read_bytes(manifest["audio_key"], 64 * 1024 * 1024)
            if (
                len(audio) != manifest["size"]
                or hashlib.sha256(audio).hexdigest() != manifest["sha256"]
            ):
                return None
    except DomainError as exc:
        if exc.info.code == "storage_not_found":
            return None
        raise
    await storage.put(key, json.dumps(manifest).encode(), "application/json")
    return manifest
