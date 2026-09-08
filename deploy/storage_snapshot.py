"""Offline object backup/restore. Stop all writers and back up PostgreSQL in the same window."""

import argparse
import hashlib
import json
from pathlib import Path

from voice_ingest.media.storage import S3Storage
from voice_ingest.runtime.settings import Settings


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def backup(storage: S3Storage, directory: Path):
    client, bucket = storage.internal, storage.bucket
    if client.get_bucket_versioning(Bucket=bucket).get("Status"):
        raise ValueError("Versioned buckets require a version-aware backup procedure")
    if client.list_multipart_uploads(Bucket=bucket).get("Uploads"):
        raise ValueError("Finish or abort multipart uploads before backup")
    directory.mkdir(exist_ok=False, parents=True)
    objects = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for item in page.get("Contents", []):
            key = item["Key"]
            head = client.head_object(Bucket=bucket, Key=key)
            path = directory / f"{len(objects):08d}.bin"
            client.download_file(bucket, key, str(path))
            if path.stat().st_size != head["ContentLength"]:
                raise ValueError("Object changed during backup; keep all writers stopped")
            objects.append(
                {
                    "key": key,
                    "file": path.name,
                    "size": path.stat().st_size,
                    "sha256": digest(path),
                    "content_type": head.get("ContentType", "application/octet-stream"),
                    "metadata": head.get("Metadata", {}),
                }
            )
    # Only this final manifest makes an export complete. Contents are private data.
    (directory / "manifest.json").write_text(
        json.dumps({"version": 1, "objects": objects}), encoding="utf-8"
    )
    print(f"Object backup complete: {len(objects)} objects")


def restore(storage: S3Storage, directory: Path):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1:
        raise ValueError("Unsupported snapshot version")
    objects = manifest["objects"]
    # Validate every byte before writing to the empty target. Never accept paths from a manifest.
    keys = set()
    for index, item in enumerate(objects):
        path = directory / f"{index:08d}.bin"
        if (
            item["file"] != path.name
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != item["size"]
            or digest(path) != item["sha256"]
            or item["key"] in keys
        ):
            raise ValueError("Snapshot failed integrity checks")
        keys.add(item["key"])
    client, bucket = storage.internal, storage.bucket
    if client.get_bucket_versioning(Bucket=bucket).get("Status"):
        raise ValueError("Restore requires an unversioned target bucket")
    if client.list_objects_v2(Bucket=bucket, MaxKeys=1).get("Contents"):
        raise ValueError("Restore requires an empty target bucket")
    if client.list_multipart_uploads(Bucket=bucket).get("Uploads"):
        raise ValueError("Restore target contains multipart uploads")
    for item in objects:
        client.upload_file(
            str(directory / item["file"]),
            bucket,
            item["key"],
            ExtraArgs={"ContentType": item["content_type"], "Metadata": item["metadata"]},
        )
    print(f"Object restore complete: {len(objects)} objects")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        storage = S3Storage(Settings())
        {"backup": backup, "restore": restore}[args.operation](storage, args.directory)
    except Exception:
        # SDK exceptions can contain private object names and signed URLs.
        parser.exit(1, "Snapshot failed; check offline state, target emptiness and integrity.\n")
