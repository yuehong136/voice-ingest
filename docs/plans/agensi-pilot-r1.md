# Agensi 剪辑清单首轮验收

2026-11-22 · 以 `acf8120` 为基线。范围和锁定版本见[首轮调研与取舍](../references/agensi-pilot-r1.md)。

## 从素材到剪辑清单

- **已有任务**。打开任务并点「复制给 Agent」，粘贴到已连接同一 Voice Ingest 工作区的会话。也可继续复制单独的任务 ID。Agent 按 ID 查状态和分页结果，使用记录中的 `asset_id`。需要文件时再走原任务导出。原生 SRT 要求所有句段时码有效，失败后可在 Web 直接下载 JSON。
- **已有 SRT**。给 Agent 附上字幕，说明对应的媒体文件版本或序列版本与时间基准。路径不可读时，改用附件或粘贴完整编号、起止时间和正文。可从[无凭据合成示例](../../skills/voice-ingest-clip-checklist/assets/example-checklist.md)开始，或使用 [Skill 的本地 SRT 读取脚本](../../skills/voice-ingest-clip-checklist/scripts/read_srt.py)。它读取标准 UTF-8 SRT，保留毫秒与多行原话，发现无效时间时报告 cue 位置。
- **交付物**。清单每条给出原话、入点、出点、素材或序列标识和选段理由。时间不完整或来源未确认的候选单列为待核对。剪辑师在自己的编辑器打开对应素材版本。历史任务的 Web 页面没有源音频回听入口。

## 已验证

`make check` 通过，59 项测试通过。独立 PostgreSQL/Silo 上的 Docker 测试共 64 项通过。Web 类型检查、构建和 Chrome 用例均通过，共 13 项浏览器测试。Skill 本地结构校验通过。

| 验收 | 本地证据 |
| --- | --- |
| 原任务接续与原生 SRT | Chromium 在独立 PostgreSQL 和 Silo 上，以合成 WAV 创建一个 mock 任务，实际下载并打开 `.srt`。随后两个新 HTTP MCP 会话凭同一 ID 找回原话、`asset_id` 和 `0–1000 ms`。带鉴权下载并打开原生 SRT，句段与时码匹配，任务列表相同，仍只一个任务和一次 Attempt。独立自动化用例也断言 provider `submit` 仅执行一次。 |
| 104 段混合样本 | 从真实服务逻辑分页读取 `100 + 4`，找到第 102 段 `The reading was 4,9, then 99.` 及 `101000–101750 ms`。第 103 段缺少结束时间，第 104 段逆序。现有归一化把无效范围的两端置空。MCP 拒绝原生 SRT，HTTP 返回 `409 timestamps_unavailable`。下载的 JSON 有全部 104 段、任务及素材 ID，并保留缺失值和原文。 |
| 剪贴板与下载降级 | 真实 Chrome 验证复制成功、API 不可用和 `NotAllowedError`。降级文本直接显示，可键盘选取。提示只带选中任务 ID 和指令。切换任务后另一个任务的文本不残留。浏览器另以固定的 409/JSON 响应验证 JSON 下载按钮及文件内容。 |
| 已有 SRT | 两版字幕、带 BOM 的 UTF-8/CRLF、多行、`4,9`、序列时码和无效时间均经过可运行的本地脚本验证。输入字幕和编辑器所开版本由使用者确认。 |

### 素材版本与本地播放

用同一段合成配音制作一条 16 秒原片，再裁掉开头 5 秒。清单打开前已在 QuickTime 载入每次对应的文件。计时从 TextEdit 点开清单开始，经读取该版本的入点、设置 QuickTime 播放位置，到界面确认开始播放。各记录一次自动化操作耗时。

| 素材版本 | 对应 SRT 时间 | 清单打开至确认播放 |
| --- | --- | --- |
| `interview-original.mp4` | `00:00:07,000` 至 `00:00:09,750` | 2.22 秒 |
| `interview-trim-5s.mp4` | `00:00:02,000` 至 `00:00:04,750` | 2.68 秒 |

两版均进入绿色的目标句画面。FFmpeg 按清单时间解码各段，与生成时的目标句音轨做 8 kHz 单声道 PCM 归一化内积，分别为 `0.9997` 和 `0.9992`。交叉使用另一版的入点时，解码结果对应设置句或后续句，验证素材版本确实影响定位。

## 未验证

- 剪辑师在实际日常编辑器中的定位、入出点标记、人工听辨和操作用时。iMovie 停在首次启动许可页，本轮只取得 QuickTime 播放和合成声轨证据。
- 已上架的 Skill 运行、Agensi 与 Voice Ingest MCP 在同一目标客户端的连接、真实客户端鉴权、定向试用和客户素材的实际选段质量。本地 MCP 用 FastMCP 客户端独立核对。mock 验证覆盖工作流，真实识别质量未测。
- 本轮验证使用独立本地资源和合成素材，平台联系、公开部署、上架、真实录音采集及付费 ASR 均未发生。

## 复现命令

从仓库根目录执行。Docker 命令仅用于这套独立测试 Compose 项目，先确认同名测试项目可用。

```bash
uv sync --all-extras --frozen
make check
uv run pytest -q tests/test_clip_handoff.py
npm ci --prefix web
npm --prefix web run check
npm --prefix web run build

docker compose -f deploy/compose.test.yaml build tests
docker compose -f deploy/compose.test.yaml up -d postgres s3
docker compose -f deploy/compose.test.yaml run --rm tests
docker compose -f deploy/compose.test.yaml --profile browser up -d browser
curl --retry 10 --retry-connrefused -fsS http://127.0.0.1:18089/v1/health/ready
VOICE_API_TARGET=http://127.0.0.1:18089 VOICE_WEB_TEST_KEY=browser-test-key \
  npm --prefix web test
```

最后一条用本机 Chrome。没有 Chrome 时可用仓库锁定 Playwright 的 `npx playwright install chrome`，在 `web` 目录执行。新会话取浏览器用例产生的任务，连接本地 `/v1/mcp/`，通过测试 Bearer 调用 `get_transcription`、`read_transcript` 和 `export_transcript`，再用同一 Bearer 下载返回的 SRT 路径。完成后可停止本轮测试资源。

```bash
docker compose -f deploy/compose.test.yaml --profile browser down --volumes
```

无凭据的字幕读取与合成媒体演示可直接运行。后半段命令用于带 `say` 和 FFmpeg 的 macOS，生成媒体留在 Git 忽略目录。

```bash
skill=skills/voice-ingest-clip-checklist
for stem in interview-original interview-trim-5s; do
  python3 "$skill/scripts/read_srt.py" "$skill/assets/$stem.srt" \
    --source "$stem.mp4" --timeline media
done

mkdir -p .local/agensi-pilot
(
  cd .local/agensi-pilot
  say -v Samantha -r 230 -o setup.aiff 'This is the setup, before the cut.'
  say -v Samantha -r 230 -o result.aiff 'We lowered the review time from nine hours to four.'
  say -v Samantha -r 230 -o followup.aiff 'Next, we checked it against the original.'
  ffmpeg -f lavfi -i 'color=c=gray:s=640x360:r=24:d=16' \
    -i setup.aiff -i result.aiff -i followup.aiff \
    -filter_complex "[0:v]drawbox=c=orange:t=fill:enable='between(t,2,4.749)',drawbox=c=green:t=fill:enable='between(t,7,9.749)',drawbox=c=blue:t=fill:enable='between(t,12,14.749)'[v];[1:a]adelay=2000:all=1[a];[2:a]adelay=7000:all=1[b];[3:a]adelay=12000:all=1[c];[a][b][c]amix=inputs=3:normalize=0,apad[audio]" \
    -map '[v]' -map '[audio]' -t 16 -c:v libx264 -pix_fmt yuv420p -c:a aac interview-original.mp4
  ffmpeg -ss 5 -i interview-original.mp4 \
    -c:v libx264 -pix_fmt yuv420p -c:a aac interview-trim-5s.mp4
)
```

## 下一轮

先在有代表性的剪辑器里用合成素材让剪辑师从打开清单开始计时，记录是否一次定位到对应版本的原话和卡在哪里。并行验证目标 Agent 客户端的独立 MCP 连接、鉴权与本地 Skill 运行。只复查这些验证实际触及的参考。试点获准后，以用户自己的素材产出首份经本人确认能在其编辑器定位的清单为首次成功，之后 7 天内用不同的第二份素材产出另一份可用清单为复用。样例体验、浏览量和点赞不计入。
