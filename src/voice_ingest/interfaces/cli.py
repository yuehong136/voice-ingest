import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import typer
from pydantic import BaseModel

from voice_ingest.client import AsyncVoiceClient, VoiceError
from voice_ingest.client.api import fingerprint, save_state
from voice_ingest.synthesis.contracts import SynthesisOptions
from voice_ingest.transcription.contracts import ExportFormat, TranscriptionOptions

app = typer.Typer(no_args_is_help=True, help="Durable offline audio transcription")
jobs = typer.Typer(no_args_is_help=True)
assets = typer.Typer(no_args_is_help=True)
app.add_typer(jobs, name="jobs")
app.add_typer(assets, name="assets")
syntheses = typer.Typer(no_args_is_help=True, help="Durable text-to-speech tasks")
app.add_typer(syntheses, name="syntheses")
configuration: dict[str, Any] = {}
FORMATS = {"json", "txt", "markdown", "srt", "vtt"}


@syntheses.command("submit")
def submit_synthesis(
    text_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    model: str = "qwen-audio-3.0-tts-flash",
    voice: str = "longanhuan_v3.6",
    deployment: str | None = None,
    format: str = "mp3",
    local_only: bool = False,
    idempotency_key: str = typer.Option(..., help="Reuse this key if submission is interrupted"),
):
    """Read UTF-8 text from a file and explicitly submit paid synthesis."""

    async def operation():
        options = SynthesisOptions.model_validate(
            dict(
                model=model,
                voice=voice,
                deployment_id=deployment,
                format=format,
                routing="local_only" if local_only else "any",
            )
        )
        async with client() as api:
            text = await asyncio.to_thread(text_file.read_text, encoding="utf-8")
            emit(await api.synthesize(text, options=options, idempotency_key=idempotency_key))

    run(operation())


@syntheses.command("voices")
def synthesis_voices(model: str = "qwen-audio-3.0-tts-flash", deployment: str | None = None):
    async def operation():
        async with client() as api:
            emit([v.model_dump() for v in await api.voices(model, deployment)])

    run(operation())


@syntheses.command("get")
def get_synthesis(job_id: str):
    async def operation():
        async with client() as api:
            emit(await api.get_synthesis(job_id))

    run(operation())


@syntheses.command("list")
def list_syntheses(cursor: str | None = None, limit: int = 50):
    async def operation():
        async with client() as api:
            emit(await api.list_syntheses(cursor, limit))

    run(operation())


@syntheses.command("cancel")
def cancel_synthesis(job_id: str):
    async def operation():
        async with client() as api:
            emit(await api.cancel_synthesis(job_id))

    run(operation())


@syntheses.command("retry")
def retry_synthesis(job_id: str, acknowledge_duplicate_risk: bool = False):
    async def operation():
        async with client() as api:
            emit(
                await api.retry_synthesis(
                    job_id, acknowledge_duplicate_risk=acknowledge_duplicate_risk
                )
            )

    run(operation())


@syntheses.command("result")
def synthesis_result(job_id: str):
    async def operation():
        async with client() as api:
            emit(await api.synthesis_result(job_id))

    run(operation())


@syntheses.command("download")
def download_synthesis(job_id: str, output: Path):
    async def operation():
        async with client() as api:
            data = await api.synthesis_audio(job_id)

            # Avoid silently overwriting an existing recording or artifact.
            def save():
                with output.open("xb") as target:
                    target.write(data)
                return str(output.resolve())

            emit({"job_id": job_id, "path": await asyncio.to_thread(save)})

    run(operation())


@syntheses.command("delete")
def delete_synthesis(job_id: str):
    async def operation():
        async with client() as api:
            await api.delete_synthesis(job_id)
            emit({"job_id": job_id, "deleted": True})

    run(operation())


@app.callback()
def configure(
    url: str = typer.Option("http://localhost:18080", envvar="VOICE_URL"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
):
    configuration.update(url=url, json=json_output)


def client() -> AsyncVoiceClient:
    key = os.getenv("VOICE_API_KEY", "")
    if not key:
        typer.echo("Set VOICE_API_KEY", err=True)
        raise typer.Exit(2)
    return AsyncVoiceClient(configuration["url"], key)


def emit(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    typer.echo(
        json.dumps(value, ensure_ascii=False, indent=None if configuration.get("json") else 2)
    )


def run(coroutine):
    try:
        return asyncio.run(coroutine)
    except VoiceError as exc:
        emit({"error": exc.error.model_dump()})
        raise typer.Exit(1) from None
    except TimeoutError:
        emit(
            {"error": {"code": "wait_timeout", "message": "Stopped waiting; server job continues"}}
        )
        raise typer.Exit(1) from None
    except (ValueError, OSError):
        emit(
            {
                "error": {
                    "code": "local_input_error",
                    "message": "Check the local path and arguments",
                }
            }
        )
        raise typer.Exit(2) from None
    except ExceptionGroup:
        emit(
            {
                "error": {
                    "code": "upload_failed",
                    "message": "Upload interrupted; run again to resume",
                }
            }
        )
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        typer.echo("Stopped waiting; submitted server jobs continue.", err=True)
        raise typer.Exit(130) from None


def export_format(value: str) -> ExportFormat:
    if value not in FORMATS:
        raise typer.BadParameter("Choose json, txt, markdown, srt or vtt")
    return value  # type: ignore[return-value]


async def submit_file(
    api: AsyncVoiceClient, file: Path, options: TranscriptionOptions, resume: bool
):
    identity = await asyncio.to_thread(fingerprint, file)
    scope = json.dumps(
        {
            "url": api.base_url,
            "path": str(await asyncio.to_thread(file.resolve)),
            "fingerprint": identity,
            "options": options.model_dump(),
        },
        sort_keys=True,
    )
    manifest = (
        Path.home()
        / ".local/state/voice-ingest/jobs"
        / (hashlib.sha256(scope.encode()).hexdigest() + ".json")
    )
    record: dict[str, Any] = {}
    if resume and manifest.exists():
        try:
            record = json.loads(await asyncio.to_thread(manifest.read_text))
        except ValueError:
            record = {}
    if record.get("job_id"):
        return await api.get(record["job_id"])
    record.setdefault("idempotency_key", uuid4().hex)
    await asyncio.to_thread(save_state, manifest, record)
    asset = await api.upload(file, resume=resume)
    job = await api.submit(asset.id, options=options, idempotency_key=record["idempotency_key"])
    record["job_id"] = job.id
    await asyncio.to_thread(save_state, manifest, record)
    return job


@app.command()
def transcribe(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    wait: bool = False,
    format: str = "markdown",
    resume: bool = True,
    model: str = "qwen-audio-3.0-asr-flash-filetrans",
    diarization: bool = False,
    language: Annotated[list[str] | None, typer.Option("--language")] = None,
    context: str | None = None,
    deployment: str | None = None,
    local_only: bool = False,
):
    """Upload a local file and submit recognition. --wait polls without holding server requests."""
    selected = export_format(format)

    async def execute():
        async with client() as api:
            typer.echo(f"Uploading {file.name}", err=True)
            job = await submit_file(
                api,
                file,
                TranscriptionOptions(
                    model=model,
                    diarization=diarization,
                    language_hints=language or [],
                    context=context,
                    deployment_id=deployment,
                    routing="local_only" if local_only else "any",
                ),
                resume,
            )
            if not wait:
                emit(job)
                return
            typer.echo(f"Waiting for {job.id}", err=True)
            job = await api.wait(job.id)
            if job.state != "succeeded":
                emit(job)
                raise typer.Exit(3)
            output = (await api.export(job.id, selected)).decode()
            if configuration.get("json"):
                emit({"job": job.model_dump(mode="json"), "format": selected, "content": output})
            else:
                typer.echo(output)

    run(execute())


@app.command()
def batch(
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    recursive: bool = False,
    resume: bool = False,
    model: str = "qwen-audio-3.0-asr-flash-filetrans",
    diarization: bool = False,
    deployment: str | None = None,
    local_only: bool = False,
):
    """Submit each audio file independently; --resume reuses recorded uploads and job IDs."""
    suffixes = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".amr", ".wma"}
    files = sorted(
        p
        for p in (directory.rglob("*") if recursive else directory.iterdir())
        if p.is_file() and p.suffix.lower() in suffixes
    )

    async def execute():
        failed = False
        async with client() as api:
            # Files are sequential; each file uses up to four concurrent part uploads.
            for file in files:
                try:
                    job = await submit_file(
                        api,
                        file,
                        TranscriptionOptions(
                            model=model,
                            diarization=diarization,
                            deployment_id=deployment,
                            routing="local_only" if local_only else "any",
                        ),
                        resume,
                    )
                    emit({"file": str(file), "job": job.model_dump(mode="json")})
                except (VoiceError, OSError, ValueError, ExceptionGroup):
                    failed = True
                    emit({"file": str(file), "error": "submission_failed", "resume": True})
        if failed:
            raise typer.Exit(3)

    run(execute())


@jobs.command("get")
def get_job(job_id: str):
    async def execute():
        async with client() as api:
            emit(await api.get(job_id))

    run(execute())


@jobs.command("list")
def list_jobs(cursor: str | None = None, limit: int = 50):
    async def execute():
        async with client() as api:
            emit(await api.list(cursor, limit))

    run(execute())


@jobs.command("cancel")
def cancel_job(job_id: str):
    async def execute():
        async with client() as api:
            emit(await api.cancel(job_id))

    run(execute())


@jobs.command("retry")
def retry_job(job_id: str, acknowledge_duplicate_risk: bool = False):
    async def execute():
        async with client() as api:
            emit(await api.retry(job_id, acknowledge_duplicate_risk=acknowledge_duplicate_risk))

    run(execute())


@jobs.command("delete")
def delete_job(job_id: str):
    async def execute():
        async with client() as api:
            await api.delete(job_id)
            emit({"id": job_id, "results_deleted": True})

    run(execute())


@assets.command("delete")
def delete_asset(asset_id: str):
    async def execute():
        async with client() as api:
            await api.delete_asset(asset_id)
            emit({"id": asset_id, "deleted": True})

    run(execute())


@app.command("models")
def models():
    async def execute():
        async with client() as api:
            emit([model.model_dump() for model in await api.models()])

    run(execute())


@app.command("export")
def export_job(job_id: str, format: str = "markdown", output: Path | None = None):
    selected = export_format(format)

    async def execute():
        async with client() as api:
            data = await api.export(job_id, selected)
            if output:
                await asyncio.to_thread(output.write_bytes, data)
                emit({"path": str(output)})
            elif configuration.get("json"):
                emit({"job_id": job_id, "format": selected, "content": data.decode()})
            else:
                typer.echo(data.decode())

    run(execute())


def main():
    app()
