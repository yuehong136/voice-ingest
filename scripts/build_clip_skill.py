"""Build the distributable clip checklist Skill from its UTF-8 text manifest."""

import argparse
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZipInfo

REPO = Path(__file__).resolve().parents[1]
SKILL = "voice-ingest-clip-checklist"
SKILL_DIR = REPO / "skills" / SKILL
FILES = (
    "LICENSE",
    "SKILL.md",
    "assets/example-checklist.md",
    "assets/interview-original.srt",
    "assets/interview-trim-5s.srt",
    "assets/paste-example.md",
    "scripts/read_srt.py",
)


def text_files() -> dict[str, bytes]:
    files = {}
    for relative in FILES:
        source = REPO / relative if relative == "LICENSE" else SKILL_DIR / relative
        if source.resolve() != source or not source.is_file():
            raise ValueError(f"Expected a regular package source file for {relative}")
        text = source.read_text(encoding="utf-8")
        if not text.strip() or "\0" in text:
            raise ValueError(f"Expected UTF-8 text for {relative}")
        files[f"{SKILL}/{relative}"] = text.encode("utf-8")
    return files


def build(output: Path) -> None:
    files = text_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        archive = Path(staging) / output.name
        with ZipFile(archive, "w") as package:
            for path, text in files.items():
                # ZipInfo fixes the archive timestamp. Stored bytes avoid compressor drift.
                member = ZipInfo(path)
                member.create_system = 3
                member.external_attr = (stat.S_IFREG | 0o644) << 16
                package.writestr(member, text)
        archive.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Destination for the release ZIP")
    args = parser.parse_args()
    try:
        build(args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Built {args.output} with {len(FILES)} UTF-8 files")


if __name__ == "__main__":
    main()
