import runpy

import pytest

snapshot = runpy.run_path("deploy/storage_snapshot.py")


async def test_snapshot_integrity_and_nonempty_target_protection(env, tmp_path):
    storage = env.storage
    await storage.put("results/example/audio", b"synthetic audio", "audio/wav")
    directory = tmp_path / "snapshot"
    snapshot["backup"](storage, directory)
    with pytest.raises(ValueError, match="empty target"):
        snapshot["restore"](storage, directory)
    await storage.delete_prefix("")
    path = directory / "00000000.bin"
    original = path.read_bytes()
    path.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="integrity"):
        snapshot["restore"](storage, directory)
    assert not storage.internal.list_objects_v2(Bucket=storage.bucket).get("Contents")
    path.write_bytes(original)
    snapshot["restore"](storage, directory)
    assert await storage.read_bytes("results/example/audio", 1024) == original
    assert (await storage.head("results/example/audio"))["ContentType"] == "audio/wav"


async def test_snapshot_rejects_incomplete_uploads_and_versioning(env, tmp_path):
    storage = env.storage
    upload = await storage.begin("audio/unfinished/source", "a" * 64)
    with pytest.raises(ValueError, match="multipart"):
        snapshot["backup"](storage, tmp_path / "incomplete")
    await storage.abort("audio/unfinished/source", upload)
    storage.internal.put_bucket_versioning(
        Bucket=storage.bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    with pytest.raises(ValueError, match="Versioned"):
        snapshot["backup"](storage, tmp_path / "versioned")
