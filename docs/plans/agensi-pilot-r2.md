# Agensi 剪辑清单第二轮本地验证

2026-11-22 · 沿用[首轮试点工作区](agensi-pilot-r1.md)和配对合成素材。目标 Agent 客户端选用本机 ChatGPT 随附的 Codex CLI `0.171.0-alpha.13`。试验只使用独立本地资源与合成音频。

## 本轮查证与取舍

| 参考 | 适用前提与决定 |
| --- | --- |
| Shotcut `26.11.15` [正式发行](https://github.com/mltframework/shotcut/releases/tag/v26.11.15)、[快捷键](https://shotcut.org/howtos/keyboard-shortcuts/#entering-time-values)、[源监视器实现](https://github.com/mltframework/shotcut/blob/v26.11.15/src/player.cpp) | 直接用实际源监视器定位及标记。需先确认所开源文件和帧率，输出工程 XML 时包含 Out 所指帧。由编辑器保存的区间交给同一发行包的 MLT 渲染器复核。 |
| Codex [MCP 连接配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[App Server 协议](https://learn.chatgpt.com/docs/app-server)和本机二进制生成的 JSON Schema | 用两个 Streamable HTTP 回环地址以及两个独立的 `bearer_token_env_var`。进程参数覆盖现有配置，在发现工具前检查实际生效的地址和服务。使用 `mcpServerStatus/list` 和 `mcpServer/tool/call`，无需发起模型推理。 |
| KittenTTS 2 [Pico](https://huggingface.co/KittenML/kitten-tts-2-pico/tree/a5632deac7d92f6178db814d933eba746a97f2dc)、[Nano](https://huggingface.co/KittenML/kitten-tts-2-nano/tree/0843ae614780b04e4260c91b601e374c4b81250d)、[分派实现](https://github.com/KittenML/KittenTTS/blob/5802f6b956844919ecf210f4e55f4750a6ad7c6f/kittenml/get_model.py)和[本地模型测试](https://github.com/KittenML/KittenTTS/blob/5802f6b956844919ecf210f4e55f4750a6ad7c6f/tests/test_kittentts2_tiny.py) | 使用内置音色和 CPU ONNX 生成补充样本。提前下载固定版本的英文权重、词表、音色与发音文件。`kittenml==0.9.8` 的 Pico int4 试跑访问了默认 int8 文件，改用两种 int8 权重。无意改变项目的语音提供商或依赖。 |

## Shotcut 入出点检查

在 Shotcut 源监视器中逐版载入文件，用清单中的素材名匹配条目。计时从 TextEdit 点开清单开始，到 Shotcut 播放位置发生变化为止。两次均已载入对应素材，每版记录一次自动化操作。标入、标出和保存工程另行操作。

| 素材 | 清单入点与结束边界 | Shotcut 入点与包含式 Out | 实际选区 | 定位至确认播放 |
| --- | --- | --- | --- | --- |
| `interview-original.mp4` | `07.000–09.750 s` | 第 168–233 帧，`07.000–09.708 s` | 66 帧，2.750 秒 | 2.336 秒 |
| `interview-trim-5s.mp4` | `02.000–04.750 s` | 第 48–113 帧，`02.000–04.708 s` | 66 帧，2.750 秒 | 2.215 秒 |

两版均为 24 fps，源时间从零开始数帧。SRT 的结束边界正好落在下一帧，Shotcut 标出点时取前一帧。按 `⌘T` 输入零基帧号并确认位置，暂停后用 `I` 和 `O` 标记，`⌘S` 保存源选区。将两份 MLT 交给 Shotcut 随附的 `melt`，实渲染均为 66 帧。解码音轨与目标句 “We lowered the review time from nine hours to four.” 的合成参考波形相似度为 `0.9997` 和 `0.9992`。交换时间码后相似度分别为 `-0.0545` 和 `-0.1152`，确认使用错误版本会落到其他原话。

本机证据路径为 `.local/agensi-pilot-r2/`，可打开 `original-selection.mlt`、`trim-5s-selection.mlt`、对应 `.mkv` 和 `shotcut-round2.json`。工程引用首轮保留在 `.local/agensi-pilot/` 的合成 MP4。

## Codex 双 MCP 与鉴权

用两份独立 Bearer 配置在同一临时 Codex App Server 会话初始化。Voice Ingest 用仓库内的 `/v1/mcp/`、独立 PostgreSQL/Silo 和 mock worker。另一个端点是本地 Skill 分发替身，唯一工具 `get_pilot_skill` 返回仓库里的 `SKILL.md`。本地探针只做初始化和工具调用。Codex 的状态接口还返回其他状态条目，判定依据是两项回环 MCP 配置、对应的实际工具发现和工具调用结果。

| 测试条件 | Voice Ingest | 本地 Skill 替身 |
| --- | --- | --- |
| 各自有效的 Bearer | 发现并调用 `get_transcription`、`read_transcript` 和 `export_transcript` | 发现并调用 `get_pilot_skill`，收到本地 Skill 内容 |
| 用 Voice Ingest 的 Token 访问 Skill 替身 | 正常初始化，三个工具可见 | 初始化失败，工具列表空。直接 HTTP 请求为 401 |
| 用 Skill 替身的 Token 访问 Voice Ingest | 初始化失败，工具列表空。直接 HTTP 请求为 401 | 正常初始化，工具可见 |
| 直接向两个 HTTP 端点发送无 Token 请求 | 401 | 401 |

Voice Ingest 的同一 mock 任务由 SDK 预置，上传的是本轮合成 WAV。Codex 按原 ID 取回素材 ID、原样 mock 句段和 `0–1000 ms` 的起止时间，导出工具返回鉴权下载路径，并用 SDK 打开了原生 SRT。测试后仍只有一个任务、一次 Attempt。Codex 在两种失败用例的状态里仍显示 `bearerToken`，因此通过初始化结果和有效工具列表判定鉴权。运行凭据仅用于本地测试，未写入报告。证据为 `codex-dual-mcp.json` 和 `codex-native-export.srt`。

## 新合成样本

KittenTTS 2 Pico 和 Nano 的 CPU ONNX int8 推理使用各自的内置英语音色 Eleanor 与 Edith，生成 4 个话轮，合成为 14.500 秒、24 kHz、单声道的 `kitten-two-voice.wav`。`kitten-two-voice.srt` 的时间来自合成片段在 WAV 中的实际样本位置，已用 Skill 的读取脚本打开核对。两个文件都在 `.local/agensi-pilot-r2/generated/`，模型版本和各句时间见 `generation.json`。这份音频的 mock 转写另有自己的合成结果，参考字幕不用于评价 ASR。

## 复现与边界

以下命令从仓库根目录执行。`generate_kitten.py` 和 `validate_codex_mcp.py` 是保存在 `.local/agensi-pilot-r2/` 的本地试验脚本，模型缓存包含本轮指定版本。验证脚本先确认测试后端仅加载 mock，使用进程参数限定 MCP 地址，输出一份省略凭据的验收 JSON。

```bash
HF_HUB_OFFLINE=1 uv run --isolated --no-project --python 3.12 \
  --with 'kittenml==0.9.8' \
  --with 'https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl' \
  python .local/agensi-pilot-r2/generate_kitten.py

docker compose -f deploy/compose.test.yaml build tests
docker compose -f deploy/compose.test.yaml --profile browser up -d browser
curl --retry 10 --retry-connrefused -fsS http://127.0.0.1:18089/v1/health/ready
uv run --no-sync python .local/agensi-pilot-r2/validate_codex_mcp.py \
  '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex' \
  .local/agensi-pilot-r2/generated/kitten-two-voice.wav
docker compose -f deploy/compose.test.yaml --profile browser down --volumes
```

`make check`、交接文档校验通过，本地 59 项测试通过、5 项集成用例未在该命令中运行。本轮独立后端的 MCP 验收通过，测试资源已停止并清理。

仍未实测独立剪辑师的操作耗时、其他帧率和剪辑器、Codex 调用模型后的选段质量、真实 Agensi OAuth 和上架前分发。本轮未联系 Agensi、未部署或上架，未使用用户提供的百炼凭据或付费 ASR。
