"""Smoke test the exact Skill ZIP as extracted files and as files fetched on demand."""

import argparse
import re
import stat
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from build_clip_skill import FILES, SKILL

READER = "scripts/read_srt.py"
PASTE_EXAMPLE = "assets/paste-example.md"
SOURCE = "Interview sequence, cut B"
START = "01:00:12,125"
END = "01:00:15,501"
QUOTE = "The queue dropped from 9 minutes to 4.\nWe measured it after launch."
REASON = "It gives a measurable result and when it was observed."

# Verify the shipped Python script can run unchanged without opening other files, importing
# user packages, making network connections, or consulting a repository or client config.
ISOLATED_RUNNER = """
import os
import runpy
import sys
import sysconfig
from pathlib import Path

script, subtitle = map(Path, sys.argv[1:3])
allowed = {script.resolve(), subtitle.resolve()}
stdlib = Path(sysconfig.get_path('stdlib')).resolve()

def audit(event, arguments):
    if event in ('open', 'os.listdir', 'os.scandir'):
        name = arguments[0]
        if not isinstance(name, int):
            path = Path(os.fsdecode(name)).resolve() if name is not None else None
            if path not in allowed and (path is None or not path.is_relative_to(stdlib)):
                raise RuntimeError('Read outside the explicit input and standard library')
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.exec'):
        raise RuntimeError('Attempted network or subprocess access')

sys.addaudithook(audit)
del sys.argv[0]
runpy.run_path(str(script), run_name='__main__')
"""


def read_text(package: ZipFile, path: str) -> str:
    text = package.read(f"{SKILL}/{path}").decode("utf-8")
    if not text.strip() or "\0" in text:
        raise ValueError(f"Expected UTF-8 text for {path}")
    return text


def check_clip(reader: Path, input_file: Path, cwd: Path) -> str:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            "utf8",
            "-c",
            ISOLATED_RUNNER,
            str(reader),
            str(input_file),
            "--source",
            SOURCE,
            "--timeline",
            "sequence",
            "--cue",
            "7",
            "--reason",
            REASON,
        ],
        cwd=cwd,
        env={},
        capture_output=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"The packaged reader failed in a clean directory: {result.stderr.strip()}"
        )
    text = result.stdout
    if (
        f"## Source\n\n{SOURCE}\n" not in text
        or f"sequence timeline · cue 7 · {START} → {END}" not in text
        or f"## Quote\n\n```text\n{QUOTE}\n```\n" not in text
        or f"## Reason\n\n{REASON}\n" not in text
    ):
        raise ValueError("The clip checklist did not preserve source, times, quote and reason")
    return text


def check(archive: Path) -> None:
    with TemporaryDirectory(prefix="voice-ingest-skill-") as folder, ZipFile(archive) as package:
        paths = [f"{SKILL}/{path}" for path in FILES]
        if package.namelist() != paths or any(
            not stat.S_ISREG(member.external_attr >> 16) for member in package.infolist()
        ):
            raise ValueError("The ZIP does not match the release text-file manifest")

        root = Path(folder).resolve()
        input_dir = root / "input"
        input_dir.mkdir()
        subtitle = input_dir / "supplied-interview.srt"
        subtitle.write_text(f"7\n{START} --> {END}\n{QUOTE}\n", encoding="utf-8")
        clean = root / "empty"
        clean.mkdir()

        extracted = root / "unpacked"
        package.extractall(extracted)
        local = check_clip(extracted / SKILL / READER, subtitle, clean)

        # Local analogue of get_skill returning instructions + an index, then serving only
        # the requested file. Materialize the reader alone as a temporary standalone script.
        skill = read_text(package, "SKILL.md")
        frontmatter = skill.split("---", 2)
        if len(frontmatter) != 3 or not re.search(rf"^name: {SKILL}$", frontmatter[1], re.M):
            raise ValueError("Invalid Skill name in the entrypoint")
        if not re.search(r"^description: .+", frontmatter[1], re.M):
            raise ValueError("Missing Skill discovery description")
        index = {
            path.removeprefix(f"{SKILL}/")
            for path in package.namelist()
            if not path.endswith("/SKILL.md")
        }
        references = set(re.findall(r"\]\(([^)]+)\)", frontmatter[2]))
        if not {READER, PASTE_EXAMPLE} <= index & references:
            raise ValueError("The instructions do not resolve the required on-demand files")
        paste = read_text(package, PASTE_EXAMPLE)
        original = read_text(package, "assets/interview-original.srt")
        match = re.search(r"```text\n(.+?)\n```", paste, re.S)
        if match is None or match[1] not in original:
            raise ValueError("The on-demand paste example does not match the downloadable SRT")
        lazy = root / "lazy"
        lazy.mkdir()
        script = lazy / "downloaded.py"
        script.write_text(read_text(package, READER), encoding="utf-8")
        downloaded = check_clip(script, subtitle, clean)
        if downloaded != local:
            raise ValueError("The extracted and on-demand checklists differ")

        for relative in FILES:
            read_text(package, relative)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Exact candidate ZIP to check")
    args = parser.parse_args()
    try:
        check(args.archive)
    except (BadZipFile, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.error(str(exc))
    print("Verified ZIP manifest, isolated checklist runs, on-demand reader and paste example")


if __name__ == "__main__":
    main()
