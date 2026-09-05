# Working on Voice Ingest

- Read docs/architecture.md before cross-module changes. Business capabilities own their contracts and behavior.
- Core capabilities must not import HTTP, MCP or CLI modules. CLI and local MCP use the public async SDK.
- Keep SDK-only installation free of server dependencies. Do not import optional frameworks at package import.
- Durable jobs are PostgreSQL state machines. Never use an HTTP background task or MCP session as durable state.
- Network side effects happen outside transactions. Fence worker writes by execution generation and lease ownership.
- A provider submission with unknown outcome must never be automatically resubmitted. Preserve original responses.
- Never log credentials, signed URLs, transcript text or user request bodies. Never commit .env or recordings.
- Do not modify existing remote knowledge-base deployments. All deployment examples use independent resources.
- Run `make check` and relevant tests. Integration tests use only dedicated test resources; real ASR is opt-in and paid.
- Keep contract changes and recovery semantics documented and covered by behavior tests.
