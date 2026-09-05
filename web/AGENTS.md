# Web workspace

- React + TypeScript SPA consumes the existing HTTP contracts. Do not recreate job orchestration in the browser.
- Generate `src/schema.d.ts` with `npm run types:generate`; the generator has isolated dependencies in `tools/` because its peer range is TypeScript 5.
- Keep the application on current stable TypeScript; do not bypass dependency checks with force flags.
- Demo fixtures must remain clearly labeled and contain no user recordings or transcripts.
- Keep credentials in memory only. Signed upload requests must never receive the service Authorization header.
- Hash in a worker, use bounded chunks, persist resume identifiers before mutations, and disable automatic mutation retries.
- All new UI copy needs English and Chinese. Keep keyboard focus, semantic labels, narrow layouts and reduced motion supported.
- Run `npm run build` and `npm test`. Automated browser tests use only the mock provider and dedicated local infrastructure. Real ASR acceptance is separate and requires explicit user authorization.
