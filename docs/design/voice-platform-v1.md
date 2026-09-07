# Voice Platform v1 设计

状态：已批准的第一阶段设计；实现和验收状态以 [阶段记录](../plans/phase-1-aliyun-stt-tts.md) 为准。
2026-09-07 已完成框架与阿里 STT/TTS 短样本真实闭环及用户试听确认；未来能力仍是设计范围。
来源：[开源与厂商调研](../references/voice-ai-open-source-research.md)，决策日期 2026-09-07。

## 边界

所有 HTTP API 使用 /v1。项目尚无外部使用者，直接更新契约、SDK、CLI、MCP、Web 和生成类型，
不增加旧客户端兼容层。现有本地资产、任务和验收资料仍必须保留；迁移新增 revision。
首阶段实现阿里 STT/TTS；其他厂商和本地模型只保留扩展契约，不在生产目录伪装为已支持。

业务模块拥有输入输出：transcription 接收音频资产，synthesis 接收完整文本与预置音色。
共同的 jobs 层拥有领取、租约、代次、尝试、事件与完成指针；运行时负责装配适配器和存储。
SDK 合同不依赖 HTTP 服务框架、SQLAlchemy 或推理库。远程 MCP 复用用例，本地 MCP/CLI 复用 SDK。

## 模型与部署

Model 表示模型及实际能力；Adapter 表示协议转换、校验、原始响应与归一化；Deployment
表示具体端点、区域、凭据引用、配置版本和容量；Attempt 固定一次调用所使用的部署快照。
配置变更不能将旧任务悄悄送去新端点。保留旧配置版本用于恢复；找不到原配置时明确失败待处理。
凭据仅在服务端解析，不进入能力目录、日志或配置快照；日志只含内部 ID、阶段、错误码和计量。

能力按实际部署声明：业务类型、输入方式、模型限制、语言、上下文、时间戳/说话人、音色、
格式、采样率和执行方式。通用参数有类型，专属参数由适配器严格校验，不静默忽略。
默认显式选择部署；仅本地策略禁止云端路由。首阶段不自动择优、不跨厂商回退。

## 执行与结果

文件类任务提交后立即返回 Job ID。Worker 在事务外调用 provider。
Provider 可以返回已接受的远端任务，或完整结果；音频流由适配器受限收集，明确结束后才保存为完整结果。
preparing → submitting 必须先落库，再发送可能产生计费/执行的请求。
远端已知任务恢复轮询；未知提交进入 needs_attention，禁止自动重提，人工确认重复风险后才能新尝试。

提交前固定本次 generation 的 capture prefix。原始数据与音频先写私有对象，再最后写完整回执。
回执将远端 task ID 或完整制品指针与 attempt 绑定。进程在回执后、数据库更新前退出，可以恢复回执；
没有有效回执的 submitting 继续按未知提交处理。部分音频无完成回执，不得发布。
实现中先保存包含期望摘要的 manifest，再保存原始响应/音频、最后保存 receipt。
若最后一个 marker 写失败，恢复流程必须读取对象并核对完整 SHA-256 与长度后才可重建回执。
manifest 自身不代表成功，禁止仅凭 manifest 发布音频或放行重复推理。
所有任务 checkpoint 验证 owner、generation、lease，旧 Worker 对象使用独立前缀，不能覆盖权威指针。

转写和合成分别返回 Transcript 与 SynthesisResult；统一记录制品类型、MIME、大小、摘要、
时长及来源。原始响应和协议事件保存在私有存储。音频保存后验证可解码与媒体元数据，再发布结果。
取消代表本地意图，远端可能继续运行。流取消/超时未知不能自动生成第二份；结果处理重试优先复用已持久化数据。

## API 与产品入口

- GET /v1/models：已配置模型/部署/能力；可按 capability 筛选。
- GET /v1/voices：按 model 与 deployment 查询预置音色。
- /v1/transcriptions：现有创建、列表、查询、取消、重试、删除、结果及导出。
- /v1/syntheses：对应合成任务操作，结果元数据与 audio 下载。
- 每个操作共用业务服务；MCP 返回有界数据与受鉴权路径，不倾倒音频或完整输入。
- Web 独立合成工作区：文本、模型、音色、明确提交、状态、播放/下载；所有 UI 支持中英文及窄屏。
- API 模型变更后重新生成前端类型；凭据只在页面内存，工作区切换清理查询缓存和播放资源。

## 后续演进

本地运行时首先考虑已部署 Xinference，LocalAI/vLLM-Omni 为后续候选；主服务不下载权重或管理 GPU。
新增适配器必须将发送后超时或不明确的提交结果转换为 SubmissionUnknown；只有明确未接受的拒绝才能
返回可重试 DomainError。禁止把第三方 SDK 的通用自动重试策略直接用于 start()。
时间戳、说话人、VAD、转换/切片后续作为独立处理能力，记录派生制品与原音频时间映射。
实时文本/音频双向会话是独立执行范围，不把网页连接或 MCP 会话作为持久化任务。
质量评测和成本/延迟指标分开；本阶段框架测试不证明未集成厂商/本地模型可用。

## 当前实现映射

- `providers/speech.py`：SpeechRequest、Accepted、Completed 和适配器协议。
- `providers/registry.py`：模型目录、部署选择、local_only 策略与快照核对。
- `runtime/deployments.py`：显式适配器装配；新增真实厂商时修改此装配处及新增适配器，Worker 不加厂商分支。
- `jobs/service.py`、`jobs/worker.py`、`jobs/receipts.py`：共享生命周期、租约、存储与恢复。
- `transcription/`、`synthesis/`：分别拥有转写和合成业务契约及结果读取。
- `providers/aliyun_contracts.py`、`aliyun_speech.py`、`aliyun_tts.py`：阿里校验、归一化、WebSocket 协议。
- `migrations/versions/0002_speech_platform.py`：保留已有数据的增量迁移。
- `tests/test_speech_platform.py`：独立适配器及恢复契约；`tests/test_integration.py`、`test_migration.py`：独立基础设施。
- `web/src/synthesis/`：合成工作区；生成 OpenAPI 类型由跨平台脚本维护。

首阶段边界：目录描述已配置的适配器能力，不主动调用计费接口探测账户权限；地域和账户授权需要真实验收。
模型 ID 被固定，但厂商如用同一 ID 更新权重，平台不能声称固定了不可见的权重修订版。
合成限制为 20000 字符、64 MiB 完整音频、600 秒单次流处理及 60 秒接收空闲超时；不自动拆分超长文本。
当前目录是一组按部署展开的模型记录，使用 `kind` 判别 STT/TTS；不适用的 STT 限制不应作为合成限制使用。
