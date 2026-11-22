import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def invoke(script: str, archive: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), str(archive)],
        cwd=archive.parent,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


def test_clip_skill_release_package_is_reproducible_and_runs_isolated(tmp_path):
    first = tmp_path / "voice-ingest-clip-checklist.zip"
    second = tmp_path / "repeat.zip"
    for archive in (first, second):
        build = invoke("build_clip_skill.py", archive)
        assert build.returncode == 0, build.stderr
    assert first.read_bytes() == second.read_bytes()

    checked = invoke("check_clip_skill_package.py", first)
    assert checked.returncode == 0, checked.stderr


def test_zip_smoke_rejects_an_unlisted_artifact(tmp_path):
    archive = tmp_path / "voice-ingest-clip-checklist.zip"
    build = invoke("build_clip_skill.py", archive)
    assert build.returncode == 0, build.stderr
    with ZipFile(archive, "a") as package:
        package.writestr("voice-ingest-clip-checklist/notes.txt", "Unreviewed extra file")

    checked = invoke("check_clip_skill_package.py", archive)
    assert checked.returncode != 0
    assert "text-file manifest" in checked.stderr


def test_zip_smoke_catches_undeclared_file_access(tmp_path):
    archive = tmp_path / "voice-ingest-clip-checklist.zip"
    changed = tmp_path / "changed.zip"
    build = invoke("build_clip_skill.py", archive)
    assert build.returncode == 0, build.stderr
    with ZipFile(archive) as original, ZipFile(changed, "w") as package:
        for member in original.infolist():
            data = original.read(member)
            if member.filename.endswith("/read_srt.py"):
                data += b'\nPath("private-config.json").read_bytes()\n'
            package.writestr(member, data)

    checked = invoke("check_clip_skill_package.py", changed)
    assert checked.returncode != 0
    assert "Read outside the explicit input" in checked.stderr
