"""Opt-in paid acceptance. Never creates resources, deletes data or retries inference."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from fastmcp import Client
from sqlalchemy import select

from voice_ingest.client import AsyncVoiceClient
from voice_ingest.interfaces.http import create_app
from voice_ingest.interfaces.mcp import create_mcp
from voice_ingest.runtime.container import Runtime
from voice_ingest.runtime.database import Job
from voice_ingest.runtime.settings import Settings
from voice_ingest.synthesis.contracts import SynthesisOptions
from voice_ingest.transcription.contracts import ACTIVE, TERMINAL

SCRIPT_PATH = Path(__file__).resolve()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Private acceptance dotenv file")
    parser.add_argument(
        "--allow-paid", action="store_true", help="Explicitly authorize Aliyun STT and TTS charges"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--audio", type=Path, help="User-authorized STT recording")
    source.add_argument(
        "--generated-source", action="store_true", help="Use this run's TTS audio as the STT input"
    )
    parser.add_argument("--output", type=Path, default=Path(".local/aliyun-acceptance"))
    parser.add_argument("--worker-tick", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def checked_settings(args):
    if not args.allow_paid:
        raise ValueError("Pass --allow-paid only after explicit paid acceptance authorization")
    settings = Settings(_env_file=args.config)
    if (
        settings.provider != "aliyun"
        or settings.deployments_file
        or not settings.database_url.endswith("/voice_acceptance")
        or not settings.s3_bucket.startswith("voice-acceptance-")
    ):
        raise ValueError(
            "Use Aliyun and independent voice_acceptance database / voice-acceptance-* bucket"
        )
    if settings.aliyun_source_mode != "temporary_upload":
        raise ValueError(
            "This isolated acceptance uses temporary_upload for private source delivery"
        )
    return settings


async def tick_process(args):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SCRIPT_PATH),
        "--config",
        str(args.config.resolve()),
        "--allow-paid",
        "--worker-tick",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(900):
            code = await process.wait()
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if code:
        raise RuntimeError("Worker process failed; inspect private job state before any retry")
    return process.pid


async def main(args):
    settings = checked_settings(args)
    runtime = Runtime(settings)
    try:
        if args.worker_tick:
            await runtime.worker.tick()
            return
        if not args.generated_source and (not args.audio or not args.audio.is_file()):
            raise ValueError("Provide --audio or explicitly choose --generated-source")
        async with runtime.sessions() as session:
            existing = await session.scalar(
                select(Job.id).where(Job.state.in_(ACTIVE) | Job.remote_may_run).limit(1)
            )
        if existing:
            raise ValueError("Resolve existing acceptance work before enabling another paid run")
        output = args.output.resolve() / uuid4().hex
        output.mkdir(parents=True, mode=0o700)
        report = {
            "status": "started",
            "started_at": datetime.now(UTC).isoformat(),
            "paid_calls_enabled": True,
            "worker_processes": [],
            "source": "generated_tts" if args.generated_source else "authorized_recording",
        }
        report_path = output / "evidence.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        # Public SDK -> HTTP use cases; local ASGI keeps this runner self-contained.
        # Worker steps run in separate OS processes, proving persisted restart recovery.
        async with AsyncVoiceClient(
            "http://acceptance",
            settings.api_key.get_secret_value(),
            transport=httpx.ASGITransport(create_app(settings, runtime)),
        ) as sdk:
            models = await sdk.models()
            if not any(m.id == "qwen-audio-3.0-tts-flash" for m in models):
                raise RuntimeError("Required acceptance deployment is unavailable")
            voices = await sdk.voices("qwen-audio-3.0-tts-flash", "default")
            if not any(v.id == "longanhuan_v3.6" for v in voices):
                raise RuntimeError("Acceptance preset voice unavailable")
            tts = await sdk.synthesize(
                "这是语音平台第一阶段的授权验收音频。",
                options=SynthesisOptions(deployment_id="default"),
                idempotency_key="accept-tts-" + output.name,
            )
            report["tts_job_id"] = tts.id
            report_path.write_text(json.dumps(report), encoding="utf-8")
            async with asyncio.timeout(1200):
                while True:
                    report["worker_processes"].append(await tick_process(args))
                    tts = await sdk.get_synthesis(tts.id)
                    if tts.state in TERMINAL:
                        break
                    await asyncio.sleep(settings.poll_seconds)
            if tts.state != "succeeded" or tts.attempt != 1:
                raise RuntimeError("TTS acceptance failed; inspect the original task")
            metadata = await sdk.synthesis_result(tts.id)
            (output / "speech.mp3").write_bytes(await sdk.synthesis_audio(tts.id))
            report.update(status="tts_succeeded", tts=metadata.model_dump(mode="json"))
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            source_audio = output / "speech.mp3" if args.generated_source else args.audio
            asset = await sdk.upload(source_audio, state_dir=output / "uploads")
            stt = await sdk.submit(asset.id, idempotency_key="accept-stt-" + output.name)
            report["stt_job_id"] = stt.id
            report_path.write_text(json.dumps(report), encoding="utf-8")
            report["worker_processes"].append(await tick_process(args))
            if (await sdk.get(stt.id)).state != "running":
                raise RuntimeError("STT did not reach the restart checkpoint; do not resubmit")
            async with asyncio.timeout(3600):
                while True:
                    await asyncio.sleep(settings.poll_seconds)
                    report["worker_processes"].append(await tick_process(args))
                    stt = await sdk.get(stt.id)
                    if stt.state in TERMINAL:
                        break
            if stt.state != "succeeded" or stt.attempt != 1:
                raise RuntimeError("STT acceptance failed; inspect the original task")
            for format in ("json", "txt", "markdown", "srt", "vtt"):
                (output / f"transcript.{format}").write_bytes(await sdk.export(stt.id, format))
            async with Client(create_mcp(runtime.transcriptions, runtime.syntheses)) as mcp:
                assert (
                    await mcp.call_tool("get_transcription", {"job_id": stt.id})
                ).structured_content["state"] == "succeeded"
                assert (
                    await mcp.call_tool("get_synthesis", {"job_id": tts.id})
                ).structured_content["state"] == "succeeded"
            report.update(
                status="automated_checks_passed",
                finished_at=datetime.now(UTC).isoformat(),
                stt=stt.model_dump(mode="json"),
                tts=metadata.model_dump(mode="json"),
                playback="pending_human_listening",
                billing="not_reconciled",
            )
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print("Automated paid checks passed. Review private evidence and listen to speech.mp3.")
    finally:
        await runtime.close()


if __name__ == "__main__":
    try:
        asyncio.run(main(arguments()))
    except Exception:
        # Exception strings and tracebacks can contain credentials, SQL parameters or text.
        print(
            "Acceptance stopped. Inspect the original private job; no automatic resubmission.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
