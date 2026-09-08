from voice_ingest.exports.render import render
from voice_ingest.jobs.service import JobService
from voice_ingest.transcription.contracts import (
    DomainError,
    ExportFormat,
    JobPage,
    JobView,
    Transcript,
    TranscriptPage,
)


class TranscriptionService(JobService[JobView, JobPage]):
    kind = "transcription"
    view_type = JobView
    page_type = JobPage

    async def result(self, job_id: str) -> Transcript:
        return Transcript.model_validate(await self.result_data(job_id))

    async def read(
        self,
        job_id: str,
        cursor: str | None = None,
        limit: int = 50,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> TranscriptPage:
        if not 1 <= limit <= 100:
            raise DomainError("invalid_limit", "Limit must be 1-100")
        try:
            offset = int(cursor or "0")
            if offset < 0:
                raise ValueError
        except ValueError:
            raise DomainError("invalid_cursor", "Invalid transcript cursor") from None
        if (
            (start_ms is not None and start_ms < 0)
            or (end_ms is not None and end_ms < 0)
            or (start_ms is not None and end_ms is not None and start_ms >= end_ms)
        ):
            raise DomainError("invalid_time_range", "Time range must be positive and increasing")
        result = await self.result(job_id)
        segments = [
            s
            for s in result.segments
            if (start_ms is None or (s.end_ms is not None and s.end_ms > start_ms))
            and (end_ms is None or (s.start_ms is not None and s.start_ms < end_ms))
        ]
        page = segments[offset : offset + limit]
        return TranscriptPage(
            job_id=job_id,
            segments=page,
            warnings=result.warnings,
            next_cursor=str(offset + limit) if offset + limit < len(segments) else None,
        )

    async def export(self, job_id: str, format: ExportFormat) -> bytes:
        transcript = await self.result(job_id)
        # Render on demand: concurrent deletion must not recreate private export objects.
        return render(transcript, format)
