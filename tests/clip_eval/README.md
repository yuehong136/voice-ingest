# Clip checklist comparison

Three self-authored synthetic transcript fixtures cover a trimmed media version, a bilingual
sequence with a nonzero origin, and a Voice Ingest JSON export with a missing endpoint.
[cases.json](cases.json) contains the public input, request, and the author's reference beats,
context requirements and duplicate groups. There are no recordings or transcripts from users.

The hard checks compare each selected cue with the actual input. The quote, both endpoints
and the source timebase must match. A Voice Ingest row must identify the asset or its job.
An incomplete cue stays in the verification section with the missing endpoint unset. Each row
has its own separate reason. The evaluator uses one cue per row and up to three candidates.
That makes the reported counts comparable and limits what this test establishes.

The editorial checks count represented reference beats, missing context and duplicate beats.
They use recognizable exact quotes even when a row fails the source/time checks. The references
were written by the fixture author before the runs. The comparison does not measure an
independent editor's preferences.

## Recorded comparison

On 2026-11-22, Codex CLI 0.171.0-alpha.13 ran six fresh one-turn sessions against
`gpt-6.1-terra` with low reasoning. Each pair had the same request, input and output schema.
The Skill arm also received `SKILL.md`. The evaluated bytes match the file in the checked release
ZIP. Each run used an empty temporary directory with user config, hooks, apps, shell and web
disabled. The model received transcript text as pasted input, so this comparison measures the
instructions and does not demonstrate platform Skill loading. [Structured outputs and scores](preview-result.json)

| Fixture | Hard checks without Skill | Hard checks with Skill | In the recorded comparison |
| --- | --- | --- | --- |
| Trimmed media | Pass | Pass | Both used the selected v2 media version and its cue times. |
| Bilingual sequence | Fail | Pass | Without Skill, all three intervals had an incorrect conversion from the sequence clock to milliseconds. |
| Missing timestamps | Fail | Pass | Without Skill, the returned source was the JSON export file, including the row flagged for verification. With Skill, the asset was traceable and the missing endpoint stayed unset. |

Both arms returned nine verbatim quotes and all nine author-reference beats. Neither omitted
a required context beat nor repeated a beat in this run. Three of nine candidate rows without
Skill and nine of nine with Skill had both exact timecodes and valid source attribution.
This is a single pair per synthetic case. It supports a provenance improvement on these inputs.

The reported data contains structured responses and scores. Codex event logs and session IDs
are excluded. Local logs of the first grading pass were kept separately. The preserved response
bytes were scored again to separate editorial checks from timecoded readiness. No rows or runs
were omitted.

## Reproduce

Use the project's Python environment, an authenticated Codex CLI that supports the flags in the
evaluator, and a model supported by that account. The evaluator makes actual text model requests
on the synthetic inputs. It does not call Voice Ingest or a speech provider.

```bash
uv run --no-sync python scripts/build_clip_skill.py /tmp/voice-ingest-clip-checklist.zip
uv run --no-sync python scripts/evaluate_clip_skill.py \
  --codex "$(command -v codex)" \
  --model gpt-6.1-terra \
  --skill-zip /tmp/voice-ingest-clip-checklist.zip \
  --output .local/clip-eval/another-run
```

The output directory must be new. The evaluator writes one response and grade per run plus a
summary with the input and Skill hashes. A hard failure in the Skill arm gives a nonzero exit
status. No editorial result is reported for real users or for a second editor.

## Regression scope

- The 24 fps fixture renders addressable synthetic frames using FFmpeg. The original and the
  five-second trim both render exactly 66 matching source frames, and the wrong offset does not.
  A 30000/1001 fps sequence preserves its 01:00:00 clock origin and renders exactly frames 15–29.
  These run when FFmpeg is installed and are independent of the earlier Shotcut acceptance.
  [Clip tests](../test_clip_handoff.py)
- The opted-in browser case allows real part 1 to complete on the dedicated Silo backend, aborts
  the second PUT, and reloads the page. Re-selecting the same WAV resumes the same upload ID
  and sends only part 2. A job is created once, after explicit confirmation.
  [Browser tests](../../web/tests/workspace.spec.ts)
- The paired process follows the baseline and clean-context pattern in the official evaluation
  guide. The digit/comma and missing endpoint regression design borrows the shape of WhisperX
  tests. This code installs neither WhisperX nor a speech model to run the checks.
  [Agent Skills evaluation](https://agentskills.io/skill-creation/evaluating-skills) ·
  [WhisperX v3.8.6 tests](https://github.com/m-bain/whisperX/blob/v3.8.6/tests/test_word_timestamp_interpolation.py) ·
  [WhisperX v3.8.6 alignment](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py)
