"""Build the offline screen-recording page or the full synthetic demo bundle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import runpy
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/voice-ingest-clip-checklist"
PAGE = ROOT / "docs/examples/clip-demo.html"
INPUTS = {
    "original": ("interview-original", 16, 1),
    "trimmed": ("interview-trim-5s", 11, 0),
}
WALKTHROUGH = "clip-checklist-demo.mp4"


def data_url(content: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"


def zip_files(output: Path, files: dict[str, bytes]) -> None:
    with ZipFile(output, "w") as archive:
        for name, content in sorted(files.items()):
            entry = ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content, compress_type=ZIP_DEFLATED)


def check_inputs(media_dir: Path, files: dict[str, bytes]) -> dict:
    manifest = json.loads((media_dir / "provenance.json").read_text(encoding="utf-8"))
    digests = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    if manifest.get("synthetic") is not True or manifest.get("sha256") != digests:
        raise ValueError("The generated sources and SRTs must match the synthetic provenance")
    voices = {}
    for flavor, voice in (("pico", "Eleanor"), ("nano", "Edith")):
        model = f"KittenML/kitten-tts-2-{flavor}"
        record = manifest["voices"][flavor]
        revision = record["revision"]
        if (
            record["model"] != model
            or record["voice"] != voice
            or not re.fullmatch(r"[a-f0-9]{40}", revision)
        ):
            raise ValueError("The generated sources must use the expected synthetic voice profiles")
        voices[flavor] = {"model": model, "voice": voice, "revision": revision}
    return {
        "synthetic": True,
        "runtime": "kittenml 0.9.8 / CPU ONNX int8",
        "sha256": digests,
        "voices": voices,
    }


def build(
    media_dir: Path, output: Path, walkthrough: Path | None, source_sha: str | None = None
) -> None:
    cue_reader = runpy.run_path(str(SKILL / "scripts/read_srt.py"))
    read_cues, milliseconds = cue_reader["read_cues"], cue_reader["milliseconds"]
    files = {}
    data = {}
    versions = {}
    for key, (stem, duration, index) in INPUTS.items():
        video = (media_dir / f"{stem}.mp4").read_bytes()
        srt = (SKILL / f"assets/{stem}.srt").read_bytes()
        versions[key] = read_cues(srt.decode("utf-8"))
        cue = versions[key][index]
        files[f"{stem}.mp4"] = video
        files[f"{stem}.srt"] = srt
        data[key] = {
            "file": f"{stem}.mp4",
            "duration": duration,
            "cue": cue,
            "start": milliseconds(cue["start"]) / 1000,
            "end": milliseconds(cue["end"]) / 1000,
            "media": data_url(video, "video/mp4"),
            "srt": data_url(srt, "application/x-subrip"),
        }
    for original, trimmed in zip(versions["original"][1:], versions["trimmed"], strict=True):
        if original["quote"] != trimmed["quote"] or any(
            milliseconds(original[bound]) - milliseconds(trimmed[bound]) != 5000
            for bound in ("start", "end")
        ):
            raise ValueError("The paired clips must preserve each quote and its five-second offset")
    provenance = check_inputs(media_dir, files)
    files["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    files["example-checklist.md"] = (SKILL / "assets/example-checklist.md").read_bytes()
    data["checklist"] = data_url(files["example-checklist.md"], "text/markdown;charset=utf-8")
    if walkthrough is not None:
        if source_sha is None or not re.fullmatch(r"[a-f0-9]{40}", source_sha):
            raise ValueError("A full source commit is required for the release bundle")
        provenance["source_commit"] = source_sha
        files[WALKTHROUGH] = walkthrough.read_bytes()
        data["walkthrough"] = data_url(files[WALKTHROUGH], "video/mp4")
    files["provenance.json"] = (json.dumps(provenance, indent=2) + "\n").encode("utf-8")
    fixtures = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    page = PAGE.read_text(encoding="utf-8")
    if page.count("@@FIXTURES@@") != 1:
        raise ValueError("The preview page needs one fixture placeholder")
    files["clip-demo.html"] = page.replace("@@FIXTURES@@", fixtures).encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    (output / "clip-demo.html").write_bytes(files["clip-demo.html"])
    if walkthrough is None:
        return

    for name in (
        WALKTHROUGH,
        "example-checklist.md",
        "interview-original.srt",
        "interview-trim-5s.srt",
    ):
        (output / name).write_bytes(files[name])
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n"
        for name, content in sorted(files.items())
    ).encode("ascii")
    zip_files(output / "voice-ingest-clip-demo.zip", files)


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("media_dir", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--walkthrough", type=Path, help="Include the recorded MP4 and create the ZIP")
    cli.add_argument("--source-sha", help="Full commit for the release assets")
    args = cli.parse_args()
    build(args.media_dir, args.output, args.walkthrough, args.source_sha)


if __name__ == "__main__":
    main()
