"""Generate the synthetic preview interview with the pinned CPU ONNX voices."""

import argparse
import hashlib
import json
import runpy
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from huggingface_hub import snapshot_download
from kittenml import KittenTTS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/voice-ingest-clip-checklist"
MODELS = {
    "pico": ("a5632deac7d92f6178db814d933eba746a97f2dc", "Eleanor"),
    "nano": ("0843ae614780b04e4260c91b601e374c4b81250d", "Edith"),
}
FFMPEG = ["ffmpeg", "-v", "error", "-nostdin", "-y"]


def probe_duration(path: Path) -> float:
    return float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            text=True,
        )
    )


def source_media(output: Path, cache_dir: Path, offline: bool) -> None:
    cue_reader = runpy.run_path(str(SKILL / "scripts/read_srt.py"))
    read_cues, milliseconds = cue_reader["read_cues"], cue_reader["milliseconds"]
    srt = SKILL / "assets/interview-original.srt"
    cues = read_cues(srt.read_text(encoding="utf-8"))
    if len(cues) != 3:
        raise ValueError("The preview expects its three synthetic interview cues")

    engines = {}
    provenance = {}
    for flavor, (revision, voice) in MODELS.items():
        repo_id = f"KittenML/kitten-tts-2-{flavor}"
        snapshot = snapshot_download(
            repo_id,
            revision=revision,
            cache_dir=cache_dir,
            local_files_only=offline,
            allow_patterns=[
                "config.json",
                "vocab.json",
                "voices_en.npz",
                "g2p/**",
                f"kitten_tts_2_{flavor}_en.onnx",
            ],
        )
        engines[flavor] = KittenTTS(snapshot, backend="onnx", device="cpu", weights="int8")
        provenance[flavor] = {"model": repo_id, "revision": revision, "voice": voice}

    with TemporaryDirectory(prefix="voice-demo-speech-") as temp:
        original = output / "interview-original.mp4"
        trimmed = output / "interview-trim-5s.mp4"
        args = [*FFMPEG, "-f", "lavfi", "-i", "color=c=0x142631:s=640x360:r=24:d=16"]
        filters = []
        boxes = []
        colors = ("0xdba864", "0x62d7b4", "0x86a9d5")
        for i, (cue, flavor, color) in enumerate(
            zip(cues, ("pico", "nano", "pico"), colors, strict=True), 1
        ):
            path = Path(temp) / f"{i}.wav"
            voice = MODELS[flavor][1]
            engines[flavor].generate_to_file(cue["quote"], path, voice=voice, language="en")
            start = milliseconds(cue["start"])
            end = milliseconds(cue["end"])
            duration = probe_duration(path)
            available = (end - start) / 1000 - 0.18
            tempo = max(1, duration / available)
            args.extend(("-i", str(path)))
            filters.append(f"[{i}:a]atempo={tempo:.8f},adelay={start}:all=1[a{i}]")
            enable = f"gte(t,{start / 1000})*lt(t,{end / 1000})"
            boxes.append(f"drawbox=x=0:y=h-14:w=iw:h=14:c={color}:t=fill:enable='{enable}'")
        filters.extend(
            ("[a1][a2][a3]amix=inputs=3:normalize=0,apad[a]", "[0:v]" + ",".join(boxes) + "[v]")
        )
        codec = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"]
        subprocess.run(
            [
                *args,
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-t",
                "16",
                *codec,
                str(original),
            ],
            check=True,
        )
        subprocess.run(
            [*FFMPEG, "-ss", "5", "-i", str(original), "-t", "11", *codec, str(trimmed)],
            check=True,
        )
    inputs = [original, trimmed, srt, SKILL / "assets/interview-trim-5s.srt"]
    manifest = {
        "voices": provenance,
        "runtime": "kittenml 0.9.8 / CPU ONNX int8",
        "synthetic": True,
        "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
    }
    (output / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    cli.add_argument("--cache-dir", type=Path, required=True)
    cli.add_argument("--offline", action="store_true", help="Read model snapshots from the cache")
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source_media(args.output, args.cache_dir, args.offline)


if __name__ == "__main__":
    main()
