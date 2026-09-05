from voice_ingest.transcription.contracts import DomainError, ExportFormat, Transcript

CONTENT_TYPES = {
    "json": "application/json",
    "txt": "text/plain",
    "markdown": "text/markdown",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
}
EXTENSIONS = {"json": "json", "txt": "txt", "markdown": "md", "srt": "srt", "vtt": "vtt"}


def timestamp(ms: int, separator: str = ".") -> str:
    seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{milliseconds:03}"


def render(transcript: Transcript, format: ExportFormat) -> bytes:
    if format == "json":
        return transcript.model_dump_json(indent=2).encode()
    if format == "txt":
        return (transcript.text + "\n").encode()
    if format == "markdown":
        lines = [f"# Transcript {transcript.job_id}", ""]
        for segment in transcript.segments:
            time = f"[{timestamp(segment.start_ms)}] " if segment.start_ms is not None else ""
            speaker = f"Speaker {segment.speaker_id}: " if segment.speaker_id is not None else ""
            lines.extend([time + speaker + segment.text, ""])
        if not transcript.segments:
            lines.append(transcript.text)
        return "\n".join(lines).encode()
    if not transcript.segments or any(
        s.start_ms is None or s.end_ms is None or s.start_ms >= s.end_ms
        for s in transcript.segments
    ):
        raise DomainError(
            "timestamps_unavailable", "Valid timestamps are required for subtitles", 409
        )
    lines = ["WEBVTT", ""] if format == "vtt" else []
    for index, segment in enumerate(transcript.segments, 1):
        assert segment.start_ms is not None and segment.end_ms is not None
        separator = "," if format == "srt" else "."
        speaker = f"Speaker {segment.speaker_id}: " if segment.speaker_id is not None else ""
        # A blank line must not terminate a cue embedded in recognized text.
        text = " ".join(segment.text.splitlines())
        lines.extend(
            [
                str(index),
                timestamp(segment.start_ms, separator)
                + " --> "
                + timestamp(segment.end_ms, separator),
                speaker + text,
                "",
            ]
        )
    return ("\n".join(lines) + "\n").encode()
