# Voice Ingest preview release checklist

The preview helps people try a self-hosted transcription service and use an interview clip checklist in the editor they already know. Its three entry paths are watching an example, using subtitles with a Skill, and transcribing a recording or reading an existing task. The bilingual [example](../examples/clip-checklist.md) and [homepages](../../README.md) explain how to choose a path.

## Prepare the release candidate

- [ ] Record the candidate commit. Build input files and documentation from a clean checkout of that commit. Record commands, results, and artifact SHA-256 digests against it. Keep historical pilot evidence separate from candidate evidence. [Round 1](agensi-pilot-r1.md) · [Round 2](agensi-pilot-r2.md)
- [ ] Build `voice-ingest-clip-checklist.zip`. With the exact ZIP, start in an empty directory and supply the SRT explicitly. Confirm that the Skill can use it independently of the checkout, user configuration, or transcription backend. Exercise loading the instructions and individually retrieving the text example and reader. Require the exact source reference, quote and times, and a separate editorial reason. [Agensi file loading](https://www.agensi.io/docs/how-agents-load-skills) · [Packaging reference](https://www.agensi.io/docs/packaging)
- [ ] Open `clip-demo.html` offline and unpack `voice-ingest-clip-demo.zip` in a new directory. Play original and trimmed media, open their SRTs and checklist, and verify the referenced range on each version. Watch the short `clip-checklist-demo.mp4` demonstration with sound. The recording illustrates the workflow and uses synthetic speech.
- [ ] Verify that the standalone `interview-original.srt`, `interview-trim-5s.srt`, and demonstration MP4 match the corresponding ZIP members. Check that public media is synthetic and cleared for redistribution. Record the generator, model revision and license, source hashes, the trim offset, and the verification for the actual release files. The first two pilot rounds' locally voiced media and renders are historical evidence. Confirm the archive listings and notes contain no private paths, real recordings, credentials, signed URLs, or internal deployment data. [Pico model license](https://huggingface.co/KittenML/kitten-tts-2-pico/tree/a5632deac7d92f6178db814d933eba746a97f2dc) · [Nano model license](https://huggingface.co/KittenML/kitten-tts-2-nano/tree/0843ae614780b04e4260c91b601e374c4b81250d)
- [ ] Complete the [existing CI checks](../../.github/workflows/check.yml) on this commit, including `make check`, SDK-only wheel install in a fresh environment, PostgreSQL and S3 integration, generated Web types, Web build and browser tests. Exercise the documented mock quickstart and read an existing job over an authenticated MCP connection. Check interruption and resume, original job ID reuse, and the handling of an uncertain provider submission. Use independent resources and keep actual ASR a separate acceptance item. [Deployment rehearsal](../operations/deployment-rehearsal.md)
- [ ] Verify long transcript pagination, missing or malformed timing, and both the matched and mismatched original/trim cases. Cover a sequence-origin or fractional frame rate case. Compare outputs for the same model, prompt and 3–5 public or synthetic inputs in fresh sessions with and without the Skill. Check exact source references, quotes and timing before scoring human preference, omitted context, duplication, or how many of the first three suggestions an editor would retain. Record actual evaluation coverage and who reviewed the choices. [Agent Skills evaluation guide](https://agentskills.io/skill-creation/evaluating-skills)
- [ ] Check the English and Chinese README entry points, the existing screenshots and [capture commands](../assets/screenshots/README.md), sample links, self-host and MCP instructions, and the issue template. Sync changes between languages. Check that the homepages report only the compatibility established in the table below.

Run the following commands in the candidate checkout to build and verify the Skill ZIP.

```bash
python3 scripts/build_clip_skill.py dist/voice-ingest-clip-checklist.zip
python3 scripts/check_clip_skill_package.py dist/voice-ingest-clip-checklist.zip
```

## Compatibility evidence

Record results by operation for the exact release files. For an inclusive out point, inspect the final included frame separately from the end boundary in the checklist. Where a cut tool offers lossless mode, verify the first rendered frame as well as the selected in point.

| Editor and input | Locate by checklist | Import SRT | Build selection automatically | Render and check |
| --- | --- | --- | --- | --- |
| Shotcut 26.11.15, local pilot 24 fps original and 5-second trim | Verified in Round 2 | Unverified | Unverified | Verified the manually marked pilot ranges in Round 2 |
| Shotcut, preview release files | Record candidate result | Unverified | Unverified | Record candidate result |
| Tester's preferred editor | Record during trial | Unverified | Unverified | Unverified |

Use the trial to choose whether to verify another editor or an optional selection import. For any SRT-to-selection test use an export of the actual selected candidates. Keep the original whole transcript SRT available separately.

## First-run trial protocol

Recruit 3–5 people who have not seen the demonstration. Tell them what data a remote provider or agent can receive and let them choose material they have permission to process. Use the demo for orientation, then end the sample session before starting the own-media task. Let the tester choose an SRT route or the recording workflow based on what they have. A mock result can help debug onboarding. It does not count as a usable quote from someone's recording.

1. With the release instructions and materials, ask the participant to find a useful quote from their own material and play it in their usual editor. Do not coach them on which entry, time base, or control to choose. If they ask for help, record the point and the minimum help provided.
2. Start timing when the participant has their material and opens the workflow instructions. Stop at the first playback they confirm matches a usable checklist entry. Record setup and provider wait time within that interval, route, source type, editor/version, frame rate and time origin if known, whether help was needed, and whether the quoted words and timing matched. Keep unsuccessful runs with their stopping point. If the participant can compare with their normal process, record its start-to-first-playback duration and differences in steps or problems. Note differences in setup or materials when comparing routes.
3. Keep only observations with a participant code and a sanitized description. Use synthetic reproductions when reporting issues. Track whether the same participant voluntarily uses another piece of material within 7 days of their first success and confirms a second usable clip. An orientation sample, view, click, or generated but unverified output does not count.

For the next iteration, look for at least **3 unaided participants** who play a usable quote from their own material, with no quote or timecode errors. Report the counts and failure modes by route. For example, if existing subtitles work and recording uploads fail, investigate transcription access or upload before changing the selection workflow.

## Publish and maintain

- [ ] Tag the exact checked commit for the preview. Attach the paired media package, standalone HTML, MP4, SRTs, Skill ZIP and checksums to that prerelease. Include changes, tested scope, deployment and upgrade notes, and remaining gaps. Open the published assets from a clean browser session and verify the downloads against their digests. [GitHub Releases](https://github.com/yuehong136/voice-ingest/releases) · [Deployment](../deployment.md) · [Upgrade and recovery](../operations/deployment-rehearsal.md)
- [ ] Describe the project in GitHub About as self-hosted transcription and use focused Topics such as `transcription`, `mcp`, and `self-hosted`. Add an external homepage only when it is reachable and has a maintainer. Keep the sample bundle, both READMEs, screenshots, and compatibility table on the release checklist.
- [ ] Route feedback through the repository issue template. Use a separate PR when a dependency update fixes a reproduced issue or an applicable security problem. The current resolved versions are FastMCP 4.0.2 and Playwright 1.63.0. [Python lockfile](../../uv.lock) · [Web lockfile](../../web/package-lock.json)
- [ ] Treat Agensi publication as its own acceptance. Verify OAuth, Skill discovery, on-demand text files, and a separately configured Voice Ingest MCP in the actual environment before representing that distribution as available. Local MCP and loading fixtures are evidence for the local paths. [Agensi sign-in and MCP](https://www.agensi.io/docs/mcp-server)
