from voice_ingest.jobs.service import JobService
from voice_ingest.synthesis.contracts import SynthesisJob, SynthesisPage, SynthesisResult
from voice_ingest.transcription.contracts import DomainError


class SynthesisService(JobService[SynthesisJob, SynthesisPage]):
    kind = "synthesis"
    view_type = SynthesisJob
    page_type = SynthesisPage

    async def result(self, job_id: str) -> SynthesisResult:
        return SynthesisResult.model_validate(await self.result_data(job_id))

    async def audio(self, job_id: str) -> bytes:
        async with self.sessions() as session:
            job = await self._load(session, job_id)
            if job.state != "succeeded" or not job.audio_key:
                raise DomainError("result_not_ready", "Audio is not complete", 409)
        return await self.storage.read_bytes(job.audio_key, 64 * 1024 * 1024)
