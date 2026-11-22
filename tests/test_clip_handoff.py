import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from test_jobs import finish

from voice_ingest.interfaces.http import create_app
from voice_ingest.interfaces.mcp import create_mcp
from voice_ingest.transcription.contracts import CreateTranscription

SKILL = Path(__file__).resolve().parents[1] / "skills" / "voice-ingest-clip-checklist"


async def test_resume_existing_job_in_fresh_mcp_session_and_open_native_srt(
    env, asset, tmp_path, monkeypatch
):
    submit = AsyncMock(wraps=env.provider.submit)
    monkeypatch.setattr(env.provider, "submit", submit)
    async with Client(create_mcp(env.transcriptions, env.syntheses)) as initial:
        created = await initial.call_tool("submit_transcription", {"asset_id": asset})
        job_id = created.structured_content["id"]
    await finish(env, job_id)

    arguments = {"job_id": job_id}
    async with Client(create_mcp(env.transcriptions, env.syntheses)) as fresh:
        job = (await fresh.call_tool("get_transcription", arguments)).structured_content
        assert (job["id"], job["asset_id"], job["state"], job["attempt"]) == (
            job_id,
            asset,
            "succeeded",
            1,
        )
        page = (await fresh.call_tool("read_transcript", arguments)).structured_content
        first = page["segments"][0]
        quote = "[MOCK] Synthetic segment 1; not speech recognition."
        assert (first["text"], first["start_ms"], first["end_ms"]) == (quote, 0, 1000)
        export = await fresh.call_tool("export_transcript", {**arguments, "format": "srt"})

    app = create_app(env.settings, env)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as http:
        path = export.structured_content["path"]
        assert (await http.get(path)).status_code == 401
        response = await http.get(path, headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="transcript.srt"'
    downloaded = tmp_path / "transcript.srt"
    downloaded.write_bytes(response.content)
    cues = json.loads(read_srt(downloaded, asset).stdout)["cues"]
    assert cues[0] == {
        "cue": "1",
        "start": "00:00:00,000",
        "end": "00:00:01,000",
        "quote": quote,
    }
    assert cues[-1]["end"] == "01:00:00,000"
    assert submit.await_count == 1
    assert [item.id for item in (await env.transcriptions.list()).items] == [job_id]


async def test_mixed_104_segment_job_reaches_late_quote_and_falls_back_to_json(
    env, asset, tmp_path, monkeypatch
):
    late_quote = "The reading was 4,9, then 99."
    missing_quote = "This line still needs a time check."
    raw_segments = [
        {"begin_time": i * 1000, "end_time": i * 1000 + 750, "text": f"Synthetic line {i + 1}."}
        for i in range(104)
    ]
    raw_segments[101]["text"] = late_quote
    raw_segments[102] = {"begin_time": 102000, "text": missing_quote}
    raw_segments[103]["end_time"] = 102_000
    monkeypatch.setattr(
        env.provider,
        "fetch",
        AsyncMock(return_value={"transcripts": [{"sentences": raw_segments}]}),
    )
    job = await env.transcriptions.create(CreateTranscription(asset_id=asset), "mixed-104")
    await finish(env, job.id)

    async with Client(create_mcp(env.transcriptions, env.syntheses)) as agent:
        args = {"job_id": job.id, "limit": 100}
        first = (await agent.call_tool("read_transcript", args)).structured_content
        assert len(first["segments"]) == 100 and first["next_cursor"]
        last = (
            await agent.call_tool("read_transcript", {**args, "cursor": first["next_cursor"]})
        ).structured_content
        assert len(last["segments"]) == 4 and not last.get("next_cursor")
        late = last["segments"][1]
        assert (late["text"], late["start_ms"], late["end_ms"]) == (late_quote, 101000, 101750)
        with pytest.raises(ToolError, match="Valid timestamps"):
            await agent.call_tool("export_transcript", {"job_id": job.id, "format": "srt"})
        fallback = await agent.call_tool("export_transcript", {"job_id": job.id, "format": "json"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(env.settings, env)),
        base_url="http://test",
        headers={"Authorization": "Bearer test-api-key"},
    ) as http:
        srt = await http.get(f"/v1/transcriptions/{job.id}/exports/srt")
        assert srt.status_code == 409 and srt.json()["error"]["code"] == "timestamps_unavailable"
        response = await http.get(fallback.structured_content["path"])
    assert response.status_code == 200
    downloaded = tmp_path / "transcript.json"
    downloaded.write_bytes(response.content)
    result = json.loads(downloaded.read_text(encoding="utf-8"))
    assert (result["job_id"], result["asset_id"], len(result["segments"])) == (job.id, asset, 104)
    assert result["segments"][101]["text"] == late_quote
    missing = result["segments"][102]
    assert (missing["text"], missing["start_ms"], missing["end_ms"], missing["speaker_id"]) == (
        missing_quote,
        None,
        None,
        None,
    )
    assert result["segments"][103]["start_ms"] is result["segments"][103]["end_ms"] is None


def read_srt(path: Path, source: str, timeline: str = "media"):
    return subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts" / "read_srt.py"),
            str(path),
            "--source",
            source,
            "--timeline",
            timeline,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_srt_reader_keeps_version_time_base_and_cue_numbers(tmp_path):
    versions = []
    for stem, cue in (("interview-original", 1), ("interview-trim-5s", 0)):
        source = f"{stem}.mp4"
        result = read_srt(SKILL / "assets" / f"{stem}.srt", source)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert (data["source"], data["timeline"]) == (source, "media")
        versions.append(data["cues"][cue])
    original, trimmed = versions
    assert (
        original["quote"]
        == trimmed["quote"]
        == ("We lowered the review time from nine hours to four.")
    )
    assert (original["start"], original["end"]) == ("00:00:07,000", "00:00:09,750")
    assert (trimmed["start"], trimmed["end"]) == ("00:00:02,000", "00:00:04,750")

    sequence = tmp_path / "sequence.srt"
    sequence.write_bytes(
        "\ufeff008\r\n01:00:07,125 --> 01:00:09,980\r\n读数 4,9\r\n下一行\r\n".encode()
    )
    data = json.loads(read_srt(sequence, "Sequence v2", "sequence").stdout)
    assert data == {
        "source": "Sequence v2",
        "timeline": "sequence",
        "cues": [
            {
                "cue": "008",
                "start": "01:00:07,125",
                "end": "01:00:09,980",
                "quote": "读数 4,9\n下一行",
            }
        ],
    }


@pytest.mark.parametrize("bounds", ["00:00:07,000 -->", "00:00:07,000 --> 00:00:04,750"])
def test_srt_reader_does_not_invent_timing(tmp_path, bounds):
    source = tmp_path / "invalid.srt"
    source.write_text(f"1\n{bounds}\nSynthetic line.\n", encoding="utf-8")
    result = read_srt(source, "Source v1")
    assert result.returncode != 0 and not result.stdout
    assert "Cue 1" in result.stderr


def ordinal_frame(stamp: str, origin_ms: int, fps: Fraction) -> int:
    """Translate the millisecond-rounded boundary of a known frame into a frame index."""
    hour, minute, second = stamp.replace(",", ":").split(":")[:3]
    stamp_ms = ((int(hour) * 60 + int(minute)) * 60 + int(second)) * 1000
    stamp_ms += int(stamp.rsplit(",", 1)[1])
    frame = round(Fraction(stamp_ms - origin_ms, 1000) * fps)
    assert abs(Fraction(frame * 1000, fps) - (stamp_ms - origin_ms)) <= Fraction(1, 2)
    return frame


def render_frame_range(clip: bytes, fps: Fraction, first: int, end: int) -> bytes:
    return subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            "2x2",
            "-framerate",
            str(fps),
            "-i",
            "pipe:0",
            "-vf",
            f"trim=start_frame={first}:end_frame={end}",
            "-fps_mode",
            "passthrough",
            "-threads:v",
            "1",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        input=clip,
        capture_output=True,
        check=True,
    ).stdout


def numbered_frames(count: int) -> list[bytes]:
    return [bytes((i % 256, i // 256, 100)) * 4 for i in range(count)]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Frame rendering requires ffmpeg")
def test_original_and_five_second_trim_render_the_same_66_source_frames():
    fps = Fraction(24)
    frames = numbered_frames(16 * 24)
    original = b"".join(frames)
    trimmed = render_frame_range(original, fps, 120, len(frames))
    selected = []
    for stem, cue_index, clip in (
        ("interview-original", 1, original),
        ("interview-trim-5s", 0, trimmed),
    ):
        path = SKILL / "assets" / f"{stem}.srt"
        data = json.loads(read_srt(path, f"{stem}.mp4").stdout)
        cue = data["cues"][cue_index]
        assert data["source"] == f"{stem}.mp4"
        first = ordinal_frame(cue["start"], 0, fps)
        end = ordinal_frame(cue["end"], 0, fps)
        selected.append(render_frame_range(clip, fps, first, end))
    assert selected[0] == selected[1] == b"".join(frames[168:234])
    assert render_frame_range(trimmed, fps, 168, 234) == b"".join(frames[288:354])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Frame rendering requires ffmpeg")
def test_fractional_frame_rate_and_nonzero_sequence_origin_render_the_marked_frames(tmp_path):
    srt = tmp_path / "sequence.srt"
    srt.write_text(
        "3\n01:00:00,501 --> 01:00:01,001\n复核 4,9 的读数。\n",
        encoding="utf-8",
    )
    result = json.loads(read_srt(srt, "Sequence 03 export", "sequence").stdout)
    assert result["timeline"] == "sequence"
    cue = result["cues"][0]
    assert (cue["start"], cue["end"], cue["quote"]) == (
        "01:00:00,501",
        "01:00:01,001",
        "复核 4,9 的读数。",
    )
    fps = Fraction(30_000, 1001)
    first = ordinal_frame(cue["start"], 3_600_000, fps)
    end = ordinal_frame(cue["end"], 3_600_000, fps)
    frames = numbered_frames(45)
    assert (first, end) == (15, 30)
    assert render_frame_range(b"".join(frames), fps, first, end) == b"".join(frames[15:30])
