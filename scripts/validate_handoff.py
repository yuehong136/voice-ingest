"""Check repository handoff links and optional byte-identical personal skill copies."""

import argparse
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [
    ROOT / "docs/references/voice-ai-open-source-research.md",
    ROOT / "docs/design/voice-platform-v1.md",
    ROOT / "docs/plans/phase-1-aliyun-stt-tts.md",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path)
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    for document in [*DOCUMENTS, ROOT / "AGENTS.md", ROOT / "docs/architecture.md"]:
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if re.match(r"(?:https?://|#|[A-Za-z]:)", target):
                continue
            path = (document.parent / unquote(target.split("#")[0])).resolve()
            assert path.exists(), f"Broken local link: {document.name}: {target}"
    if args.skill_dir:
        for document in DOCUMENTS:
            destination = args.skill_dir / "references" / document.name
            if args.sync:
                destination.write_bytes(document.read_bytes())
            assert destination.read_bytes() == document.read_bytes(), (
                f"Stale skill copy: {document.name}"
            )
            print(document.name, hashlib.sha256(document.read_bytes()).hexdigest())
    print("Handoff links and requested reference copies are valid")


if __name__ == "__main__":
    main()
