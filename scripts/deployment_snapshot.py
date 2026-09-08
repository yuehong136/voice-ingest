"""Offline Compose snapshot. Restore only into a separate, empty deployment."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], **kwargs):
    return subprocess.run(command, check=True, stderr=subprocess.PIPE, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    env_file = args.env_file.resolve()
    compose = [
        "docker",
        "compose",
        "--project-name",
        args.project,
        "--env-file",
        str(env_file),
        "-f",
        str(ROOT / "deploy/compose.yaml"),
        "-f",
        str(ROOT / "deploy/compose.web.yaml"),
    ]
    # The runtime env_file and interpolation env_file must refer to the same explicit file.
    os.environ["VOICE_ENV_FILE"] = str(env_file)
    active = set(
        run(compose + ["ps", "--services", "--status", "running"], stdout=subprocess.PIPE)
        .stdout.decode()
        .split()
    )
    writers = sorted(active & {"api", "worker", "web"})
    if not {"postgres", "s3"} <= active:
        raise ValueError("Start only the target PostgreSQL and S3 first")
    user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "10001:10001"
    helper = compose + [
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--user",
        user,
        "-v",
        f"{directory}:/snapshot" + (":ro" if args.operation == "restore" else ""),
        "storage-init",
        "python",
        "deploy/storage_snapshot.py",
    ]
    sql = compose + ["exec", "-T", "postgres", "psql", "-U", "voice", "-d", "voice", "-Atc"]
    if args.operation == "backup":
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        if writers:
            run(compose + ["stop", "--timeout", "180", *writers], stdout=subprocess.PIPE)
        unfinished = run(
            sql + ["SELECT count(*) FROM uploads WHERE state NOT IN ('complete','aborted')"],
            stdout=subprocess.PIPE,
        ).stdout.strip()
        if unfinished != b"0":
            raise ValueError("Finish or abort uploads first; writers remain stopped")
        with (directory / "database.dump").open("xb") as output:
            run(
                compose
                + [
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "-U",
                    "voice",
                    "-d",
                    "voice",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                ],
                stdout=output,
            )
        run(helper + ["backup", "/snapshot/objects"], stdout=subprocess.PIPE)
        manifest = {
            "version": 1,
            "source_project": args.project,
            "database_sha256": file_digest(directory / "database.dump"),
            "objects_manifest_sha256": file_digest(directory / "objects/manifest.json"),
        }
        (directory / "snapshot.json").write_text(json.dumps(manifest), encoding="utf-8")
        if writers:
            run(compose + ["start", *writers], stdout=subprocess.PIPE)
        print("Offline database and object backup complete; prior services restarted")
    else:
        manifest = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
        if (
            manifest["version"] != 1
            or args.project == manifest["source_project"]
            or writers
            or file_digest(directory / "database.dump") != manifest["database_sha256"]
            or file_digest(directory / "objects/manifest.json")
            != manifest["objects_manifest_sha256"]
        ):
            raise ValueError("Use an intact snapshot and a separate target with writers stopped")
        tables = run(
            sql + ["SELECT count(*) FROM pg_tables WHERE schemaname='public'"],
            stdout=subprocess.PIPE,
        ).stdout.strip()
        if tables != b"0":
            raise ValueError("Restore requires an empty target database; never overwrites tables")
        run(helper + ["restore", "/snapshot/objects"], stdout=subprocess.PIPE)
        with (directory / "database.dump").open("rb") as source:
            run(
                compose
                + [
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "-U",
                    "voice",
                    "-d",
                    "voice",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "--single-transaction",
                ],
                stdin=source,
                stdout=subprocess.PIPE,
            )
        print("Database and objects restored; keep writers stopped until configuration is reviewed")


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError):
        # Do not echo Compose configuration, connection strings or object names.
        raise SystemExit(
            "Snapshot failed. Check prerequisites and integrity; writers may remain stopped. "
            "No automatic restore cleanup or restart was performed."
        ) from None
