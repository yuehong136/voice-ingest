# ADR 0001: capability modules with durable application jobs

Status: accepted

Context: long recordings outlive HTTP requests and MCP connections; the same task must be accessible
from a CLI, Python and agents. Aliyun's file interface already handles hour-long recordings.

Decision: one codebase organized by business capability. PostgreSQL persists jobs and leases, S3
stores audio/results, and separate workers use a small provider protocol. No initial audio slicing,
MCP Tasks dependency, Redis queue or knowledge-base coupling. FastMCP 4.0.2 supplies the MCP SDK v2
transport; it is not the application's persistence engine. Client-only installations stay lightweight.

Consequences: deploy PostgreSQL and S3; implement and test a deliberately small durable state machine.
Submission uncertainty cannot be eliminated without supplier-side idempotency. Expose it explicitly.
Future suppliers must declare their input limits and adapt into the ASR result contract. TTS gets its
own input/output contract rather than overloading transcription fields.
