# Voice AI 开源生态与厂商调研

核验日期：2026-09-07。本文是调研快照，不代表本项目已集成这些服务。
项目决策见 [v1 设计](../design/voice-platform-v1.md)，当前范围见
[第一阶段](../plans/phase-1-aliyun-stt-tts.md)。Star 为核验时约值；默认分支提交、
发布频率、模型效果、部署成熟度分别评价，不能互相替代。

## 开源项目快照

数据来自 GitHub 仓库元数据、latest release 和默认分支 commit API；以下仓库核验时均未归档。
日期按 UTC，不能把长期未更新解释为已停止维护，也不能仅凭一次提交称为高频维护。

| 项目 | Star | 发布记录 | 默认分支最新提交 | 决策 |
|---|---:|---|---|---|
| [Xinference](https://github.com/xorbitsai/inference) | 9.5k | [3.3.0 / 2026-08-30](https://github.com/xorbitsai/inference/releases/tag/v3.3.0) | 2026-09-07 | 后续本地运行时优先验收对象；首阶段不集成 |
| [LocalAI](https://github.com/mudler/LocalAI) | 48.9k | [4.9.0 / 2026-08-20](https://github.com/mudler/LocalAI/releases/tag/v4.9.0) | 2026-09-06 | 借鉴小核心与独立后端；后续可选接入 |
| [vLLM-Omni](https://github.com/vllm-project/vllm-omni) | 6.7k | [0.28.0 / 2026-08-31](https://github.com/vllm-project/vllm-omni/releases/tag/v0.28.0) | 2026-09-06 | 本地吞吐和流式推理候选；按模型硬件实测 |
| [FunASR](https://github.com/modelscope/FunASR) | 20.2k | [1.4.14 / 2026-09-03](https://github.com/modelscope/FunASR/releases/tag/v1.4.14) | 2026-09-06 | 借鉴中文识别、VAD、标点、说话人处理分离 |
| [Pipecat](https://github.com/pipecat-ai/pipecat) | 15.3k | [1.8.1 / 2026-08-27](https://github.com/pipecat-ai/pipecat/releases/tag/v1.8.1) | 2026-09-06 | 借鉴 STT/TTS 服务和事件契约；实时阶段再选型 |
| [LiveKit Agents](https://github.com/livekit/agents) | 14.0k | [1.8.0 / 2026-09-05](https://github.com/livekit/agents/releases/tag/livekit-agents@1.8.0) | 2026-09-06 | 借鉴能力描述、插件与指标；不替代持久化任务 |
| [LiteLLM](https://github.com/BerriAI/litellm) | 58.2k | [1.100.0 / 2026-09-06](https://github.com/BerriAI/litellm/releases/tag/v1.100.0) | 2026-09-06 | 路由、错误、用量参考；非必选依赖 |
| [TEN Framework](https://github.com/TEN-framework/ten-framework) | 11.1k | [0.11.71 / 2026-07-31](https://github.com/TEN-framework/ten-framework/releases/tag/0.11.71) | 2026-09-03 | 组件设计参考；主许可证带附加条件 |
| [Speaches](https://github.com/speaches-ai/speaches) | 3.6k | [0.9.0-rc.3 / 2025-12-27](https://github.com/speaches-ai/speaches/releases/tag/v0.9.0-rc.3) | 2026-04-18 | 轻量语音服务参考；不作唯一长期后端 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 25.3k | [1.2.1 / 2025-10-31](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1) | 2025-11-19 | 成熟识别基线；并非近期高频更新 |
| [WhisperX](https://github.com/m-bain/whisperX) | 23.9k | [3.8.6 / 2026-05-25](https://github.com/m-bain/whisperX/releases/tag/v3.8.6) | 2026-07-13 | 借鉴识别、强制对齐、说话人分离流水线 |
| [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) | 3.5k | 未取得 GitHub release | 2026-06-26 | 本地模型候选；服务化另看运行时 |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | 13.3k | 未取得 GitHub release | 2026-03-17 | 本地合成候选；不是已部署能力 |
| [CosyVoice](https://github.com/QwenAudio/CosyVoice) | 23.5k | 未取得 GitHub release | 2026-05-25 | 本地 TTS 候选；区分云端同名服务 |

补充工具：[JiWER](https://github.com/jitsi/jiwer) 提供 CER/WER 和空参考处理，
[pyannote.audio](https://github.com/pyannote/pyannote-audio) 提供说话人分离能力。
本轮未为这两个补充工具核验完整维护元数据，不把它们列入上述 14 个仓库统计。

## 影响设计的源码证据

- [Xinference 音频模型定义](https://github.com/xorbitsai/inference/blob/v3.3.0/xinference/model/audio/core.py#L72)：模型族、revision、能力、引擎与实例分别描述。采用这种分离；不复制其允许任意额外字段的策略。
- [LocalAI 4.9.0](https://github.com/mudler/LocalAI/tree/v4.9.0)：小核心与独立后端镜像。推理依赖应留在外部服务，不进入本项目 SDK。
- [vLLM-Omni speech API](https://github.com/vllm-project/vllm-omni/blob/v0.28.0/docs/serving/speech_api.md)：完整音频、音频字节流、SSE、增量文本 WebSocket 是不同能力，不能只用一个 streaming 布尔值表示。
- [LiveKit STT 能力](https://github.com/livekit/agents/blob/c6939a5b86e4e797ab821ebb9bf7a6892071e328/livekit-agents/livekit/agents/stt/stt.py#L132)：离线识别、流式、临时结果、说话人、对齐粒度分别声明。
- [LiveKit 重试循环](https://github.com/livekit/agents/blob/c6939a5b86e4e797ab821ebb9bf7a6892071e328/livekit-agents/livekit/agents/stt/stt.py#L216)：调用层会重试。不能将实时恢复默认值直接用于本项目付费提交。
- [Pipecat TTS](https://github.com/pipecat-ai/pipecat/blob/1f8a513dd79c31f54bbd5b197fa26aefe242deca/src/pipecat/services/tts_service.py#L1307)：debug 路径可输出合成正文；任何引入都需验证实际日志路径，不能只检查本项目 logger。
- [WhisperX 流水线与限制](https://github.com/m-bain/whisperX/blob/2cfd7b7c5c7bba144954364db747319b50e8232b/README.md)：对齐和说话人分离是独立步骤，部分字符无法对齐。缺少时间戳继续置空，不编造。
- [FunASR](https://github.com/modelscope/FunASR/blob/2d2d385545698a1c216cd421666695cefbc56c32/README.md)：task、checkpoint、runtime 分开选择；工具包许可证不等于权重许可证。
- [TEN 许可证](https://github.com/TEN-framework/ten-framework/blob/ec4115cf8fc4c4d3534bba88b20d2a57e8722123/LICENSE)：主许可有附加条件，不能标为标准 Apache-2.0；使用前按实际组件核验。

## 厂商接口差异

| 对象 | 已核实的差异 | 对本项目的要求 |
|---|---|---|
| [阿里文件 ASR](https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-http-api) | 远端异步任务、文件级状态、临时结果 URL | 保留 task ID；先保存原始结果再归一化 |
| [阿里 TTS](https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide) | WebSocket 音频输出、模型与音色关联 | 首阶段消费流为完整文件；不因此承诺实时会话 |
| [火山极速 ASR](https://www.volcengine.com/docs/6561/1631584?lang=zh) | 一次请求返回结果，无 submit/query 轮询 | 执行契约支持直接结果；首阶段仅作测试参考 |
| [OpenAI 文件转写](https://developers.openai.com/api/docs/guides/speech-to-text) | 文件上传限制；普通转写、时间戳、说话人能力因模型不同 | 按实际模型校验，不能复用阿里时长/大小限制 |
| [ElevenLabs TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/stream) | 音色与模型独立，流式音频，输出格式关联采样率 | 独立音色目录和输出制品元数据 |
| [Azure batch synthesis](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/batch-synthesis) | TTS 也可采用提交、轮询、下载 | 业务能力与执行方式独立 |
| [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) | 本地推理与 vLLM 服务化；可另加对齐模型 | 支持本地部署策略，记录对齐来源 |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | 不同 checkpoint 承担预置音色、设计、克隆 | 首阶段不把高级音色能力作为完成条件 |

LiteLLM 的 [audio transcription](https://docs.litellm.ai/docs/audio_transcription) 有回退与用量功能，
但不能替代本项目未知提交保护。任何代理必须能禁用底层自动重试/跨厂商回退。
[OpenTelemetry](https://opentelemetry.io/docs/specs/semconv/) 用于操作耗时与关联标识；
GenAI 约定仍需按具体版本核验，不能采集正文、签名 URL 或凭据。

## 项目基线与演进边界

调研时项目已有 PostgreSQL 状态机、租约代次隔离、事务外 I/O、私有 S3、SDK/CLI/MCP/Web，
但模型目录、参数限制、归一化、Worker 和全局配置绑定阿里文件 ASR。
分页逐次读完整 JSON、搜索只覆盖前端已加载句段、UUID 排序、历史回听能力有限，属于后续产品优化。
CI 未覆盖真实 PostgreSQL/S3 并发保证，属于本阶段验证基础设施范围。

固定决策：仅 v1；第一阶段只完整集成阿里 STT/TTS；海外和本地正式支持是后续范围。
不引入实时 Agent 框架、模型下载/GPU 管理、自动切片、声音克隆或多租户系统。
保留独立部署和模块化单体，只有实际工作流/容量证据才考虑额外队列或工作流引擎。

## 评测与更新方法

固定授权样本、文本规整规则和数据集版本；STT 比较 CER/WER、术语、静音幻觉、对齐与说话人。
TTS 比较漏读重复、数字和专名发音、可懂度、音色一致性，并人工盲听；ASR 回译只作辅助。
记录模型 revision、引擎版本、部署配置、参数、硬件、冷启动/排队/传输/推理耗时及用量来源。
厂商宣传指标不是本项目测试结果，费用估算不是账单。

更新时重查官方仓库/文档并记录日期与 immutable commit/release，区分机器人更新与功能维护。
不要把本快照中的版本直接当作永久推荐；依赖升级应通过契约与固定评测集。


## 实施期间补充核验：阿里 TTS 原始协议（2026-09-07）

官方来源：[客户端事件](https://help.aliyun.com/zh/model-studio/cosyvoice-client-events)、
[服务端事件](https://help.aliyun.com/zh/model-studio/cosyvoice-server-events)、
[当前示例](https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide)。
服务端 task-started 后发送 continue-task 和 finish-task；同一任务事件保持相同 task_id。
MP3 为默认格式，22050 Hz 为默认采样率；单次文本发送最多 20000 字符。
本项目采用一次完整文本输入，不实现自动切片。仅匹配 task-finished、非空音频和媒体校验共同满足时发布。
官方示例的模型/音色为 qwen-audio-3.0-tts-flash / longanhuan_v3.6；业务空间和地域必须匹配账户。
接口文档的可用性说明不能证明当前账户已获得权限，仍需独立真实验收。
本项目在 2026-09-07 获得用户显式授权后，已用该模型/音色组合通过北京默认端点完成真实闭环，
并以同一音频完成 STT；结果与限制见[本阶段验收记录](../plans/phase-1-aliyun-stt-tts.md)。
这一证据只适用于本次账户和样本，不扩展为所有地域、账户或模型的可用性保证。
实现使用异步 WebSocket 客户端隔离每个部署的认证和连接配置，避免 SDK 全局配置污染；
禁用网络正文日志，保存私有协议事件，流断开按未知结果处理，不自动重新合成。


## 实施期间补充核验：S3 批量删除校验（2026-09-07）

独立 MinIO 集成测试暴露 MissingContentMD5，模拟 S3 测试未能覆盖该差异。
依据 [AWS DeleteObjects 文档](https://docs.aws.amazon.com/botocore/latest/reference/services/s3/client/delete_objects.html)
以及 [botocore 校验实现](https://github.com/boto/botocore/blob/develop/botocore/httpchecksum.py)，
在序列化 XML 完成后、签名前计算 Content-MD5，并保留 SDK 自身校验；不降级 SDK、不关闭校验。
MD5 在此只作为 S3 请求完整性字段，制品身份和恢复校验仍使用 SHA-256。
此发现进一步说明真实数据库/对象存储测试不能被内存替身替代。测试使用历史 MinIO 镜像验证兼容性，
不把该镜像当成新生产部署版本推荐；生产对象存储版本需按当前官方维护和许可证情况单独选择。

## 发布审查补充：MinIO multipart 清理（2026-09-08）

正式 Compose 启动暴露 `AbortIncompleteMultipartUpload` lifecycle 被拒绝，原脚本导致 storage-init 失败。
[官方问题记录](https://github.com/minio/minio/issues/19115)说明该动作不适用于 MinIO；
[本次镜像版本对应源码](https://github.com/minio/minio/blob/RELEASE.2025-06-13T11-33-47Z/internal/config/api/api.go)
定义 `MINIO_API_STALE_UPLOADS_EXPIRY` 和 `MINIO_API_STALE_UPLOADS_CLEANUP_INTERVAL`。
采用明确区分的 bootstrap 策略：Compose 的 MinIO 使用服务端扫描；通用 S3 使用标准 lifecycle 并保留已有规则。
源码参数核验和初始化策略单元测试不等于已在最新 AIStor 上初始化成功或等待 24 小时验证物理回收。
上述旧镜像仍只作为本轮本地兼容演练配置，
正式托管版本和维护情况必须单独选择，见[部署演练](../operations/deployment-rehearsal.md)。

同日进一步核实[官方高危公告](https://github.com/minio/minio/security/advisories/GHSA-hv4r-mvr4-25vw)：
旧社区版受 unsigned-trailer 签名绕过影响，社区仓库于 2026-04-25 归档；公告修复指向 AIStor，
不能将旧社区镜像视为持续维护的生产默认。采用结论更新为：历史镜像仅保留在隔离兼容验证中；
曾暂选 AIStor 单节点免费版；下文最终社区选型已取代该临时决定，保留核验事实以免混淆产品线。

2026-09-08 查询[官方发布接口](https://dl.min.io/api/releases/aistor/latest)，
返回镜像 `quay.io/minio/aistor/minio:RELEASE.2026-08-07T18-34-35Z`，元数据发布时间
`2026-08-07T22:20:29Z`；镜像内 `--version` 核验 commit
`59a3350e61d019f9ba2fcd37c44ac038639d35cf`、Go 1.26.5 / linux/amd64。
[发布制品说明](https://docs.min.io/aistor/operations/release-artifacts/)用于后续重新查询，
部署固定本次具体 tag，不使用会静默漂移的 latest 标签。
[许可说明](https://docs.min.io/aistor/operations/licenses/)确认 Free 需有效许可证、支持单节点且不含 SLA；
无许可证可离线启动，但所有 S3 操作被阻止。免费版不是旧 AGPL 社区版；
这一限制只适用于 AIStor，不能推导为所有 MinIO 社区分支都需要激活。

## 最终社区对象存储选型（2026-09-08）

用户明确要求采用持续维护的社区最新版本；不为尚未对外使用的系统引入旧客户端兼容层，
但已有资产、迁移及真实验收记录仍保留。最终选择 PGSTY Silo，替代临时 AIStor 配置。

| 项目快照 | 实际镜像 | 判断 |
| --- | --- | --- |
| [RAGFlow main](https://github.com/infiniflow/ragflow/blob/main/docker/docker-compose-base.yml) | pgsty/silo:RELEASE.2026-08-06T00-00-00Z | 同一维护线的采用证据，不能推导为使用量第一 |
| [RAGFlow v0.26.4](https://github.com/infiniflow/ragflow/blob/v0.26.4/docker/docker-compose-base.yml) | pgsty/minio:RELEASE.2026-03-25T00-00-00Z | 更名前的历史发行版，不作为本项目默认 |
| [Langfuse main](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml) | cgr.dev/chainguard/minio | 第三方构建、无固定 tag；无法由 Compose 确定其准确版本 |
| [Milvus master standalone](https://github.com/milvus-io/milvus/blob/master/deployments/docker/standalone/docker-compose.yml) | minio/minio:RELEASE.2024-05-28T17-19-04Z | 示例保留旧版，不等于当前安全推荐 |

[Silo 项目](https://github.com/pgsty/silo)是独立维护的 MinIO 分支，2026-08-06 从 pgsty/minio 更名，
采用 AGPL-3.0-or-later，无 AIStor 激活文件要求，与 MinIO 公司无隶属关系。
本项目直接采用[最新稳定版 RELEASE.2026-09-03T13-18-01Z](https://github.com/pgsty/silo/releases/tag/RELEASE.2026-09-03T13-18-01Z)，
源码 `9b11dc9469e650815b775cb47b039610644f5da4`，镜像 `pgsty/silo:RELEASE.2026-09-03T13-18-01Z`。
实际拉取 manifest 摘要与上游一致：`sha256:b616a0cf8cb281e7e6bb3c9b1fb53875b4016a2878223925541c18f82d6c5ca3`。
本次核对了发布页与镜像摘要，没有声称已独立验证所有签名或整个依赖树的安全性。

该发行版重点改进 bucket CORS、multipart 校验和与权限一致性；上游报告自身集群恢复测试通过。
我们必须另行验证 Voice Ingest 的签名上传/下载、删除、CORS、初始化、迁移和成对备份恢复，
不能拿上游测试报告替代本项目证据。[固定源码配置](https://github.com/pgsty/silo/blob/9b11dc9469e650815b775cb47b039610644f5da4/internal/config/api/api.go)
保留 MINIO_API_CORS_ALLOW_ORIGIN 和 stale-upload 参数；实际 24 小时孤立分片回收尚需长期观察。
AIStor 仅保留为后续可选部署方向，本轮不要求其许可证，也不交付 AIStor 已验证的声明。
