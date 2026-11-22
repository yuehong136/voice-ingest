"""Read UTF-8 SubRip cues locally with their original timestamps and text."""

import argparse
import json
import re
from pathlib import Path

STAMP = r"[0-9]{2,}:[0-5][0-9]:[0-5][0-9],[0-9]{3}"
TIMING = re.compile(rf"\s*({STAMP})[ \t]+-->[ \t]+({STAMP})[ \t]*")


def milliseconds(stamp: str) -> int:
    clock, fraction = stamp.split(",")
    hours, minutes, seconds = map(int, clock.split(":"))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(fraction)


def read_cues(text: str) -> list[dict[str, str]]:
    # Path.read_text uses universal newlines. Remove only the file's outer blank lines.
    blocks = re.split(r"\n(?:[ \t]*\n)+", text.strip("\n"))
    cues = []
    for position, block in enumerate(blocks, 1):
        index, _, cue = block.partition("\n")
        timing, _, quote = cue.partition("\n")
        bounds = TIMING.fullmatch(timing)
        if not index.strip().isascii() or not index.strip().isdigit() or not bounds:
            raise ValueError(f"Cue {position} needs a numeric ID and two valid SRT timestamps.")
        start, end = bounds.groups()
        if not quote.strip() or milliseconds(start) >= milliseconds(end):
            raise ValueError(f"Cue {position} needs text and an end later than its start.")
        cues.append({"cue": index.strip(), "start": start, "end": end, "quote": quote})
    return cues


def render_entry(source: str, timeline: str, cue: dict[str, str], reason: str) -> str:
    quote = cue["quote"]
    backtick_runs = re.findall(r"`+", quote)
    fence = "`" * max(3, 1 + max(map(len, backtick_runs), default=0))
    return (
        "# Clip checklist\n\n"
        f"## Source\n\n{source}\n\n"
        "## Time range\n\n"
        f"{timeline} timeline · cue {cue['cue']} · {cue['start']} → {cue['end']}\n\n"
        f"## Quote\n\n{fence}text\n{quote}\n{fence}\n\n"
        f"## Reason\n\n{reason}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--source", required=True, help="Exact media filename/version or sequence")
    parser.add_argument("--timeline", choices=("media", "sequence"), required=True)
    parser.add_argument("--cue", help="Render a Markdown entry for this cue number, with --reason")
    parser.add_argument("--reason", help="Editorial selection reason for --cue")
    args = parser.parse_args()
    if not args.source.strip():
        parser.error("Give the exact media or sequence identifier.")
    if (args.cue is None) != (args.reason is None) or (
        args.reason is not None and not args.reason.strip()
    ):
        parser.error("Give both --cue and a non-empty --reason to render a checklist entry.")
    try:
        cues = read_cues(args.path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError):
        parser.error("Could not read the SRT as UTF-8. Save a UTF-8 copy or paste complete cues.")
    except ValueError as exc:
        parser.error(str(exc))
    if args.cue is None:
        print(
            json.dumps(
                {"source": args.source, "timeline": args.timeline, "cues": cues}, ensure_ascii=True
            )
        )
        return
    selected = [cue for cue in cues if cue["cue"] == args.cue]
    if len(selected) != 1:
        parser.error("The selected cue must occur exactly once in the supplied SRT.")
    print(render_entry(args.source, args.timeline, selected[0], args.reason.strip()), end="")


if __name__ == "__main__":
    main()
