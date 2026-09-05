# 本地验收记录（2026-09-05）

## 真实阿里 ASR

用户授权使用本地 MP3 和所提供的密钥。整文件提交一次，没有切片或压缩。

- 文件：20,929,680 字节，87 分 12.420 秒，16 kHz，双声道 MP3。
- 模型：`qwen-audio-3.0-asr-flash-filetrans`，北京常规 DashScope REST 通道。
- 供应商任务已成功；具体任务 ID 仅保留在本地验收记录中。
- 输出：743 个句段、24,078 个文本字符；JSON、TXT、Markdown、SRT、VTT 均生成。
- 743 个句段均具有合法的起止时间，且未超出原音频时长。
- 首句时间 80–4080 ms，中部抽查 2604660–2611740 ms，末句 5219320–5227920 ms。
- 未进行逐句人工听校；时间范围检查不能证明文字识别准确率。

调用复用了项目的供应商提交、查询、结果下载、规范化和导出代码。为了让阿里读取本地文件，
本次使用阿里官方临时文件存储，未公开本地文件服务。原始结果、转写正文及调用脚本存放在
被忽略的 `.local/live/` 中，不进入源码交付。

这证明了真实密钥、该模型和完整录音的供应商链路；尚不能代替部署环境中
“私有 S3 签名地址可被阿里公网读取”的验收。`fun-asr` 已有适配和契约测试，未另行产生真实调用。

## 密钥与计费通道

所提供密钥对北京常规 DashScope 模型接口返回 200，对 Token Plan 接口返回
401 InvalidApiKey；真实 ASR 使用前者。未查询账单，不能断言本次实际扣费金额或套餐抵扣。
项目当前只适配常规 DashScope ASR，不做 Token Plan 与按量计费之间的自动切换。
专用 `sk-sp-` 密钥在本适配器启动时明确拒绝。参见 [部署说明](deployment.md)。

## 本地基础设施验证

独立 PostgreSQL、MinIO 上验证了并发幂等提交、任务领取上限和租约代次隔离，
以及 30 分钟、一小时模拟录音的真实分片上传、SHA256、ffprobe、私有桶访问、
worker 重建恢复、HTTP 与 MCP 结果互查。模拟转写文本不代表真实 ASR 质量。
迁移执行和 Alembic schema drift 检查通过。

最终检查：20 项离线测试、3 项 PostgreSQL/MinIO 集成测试通过；Ruff、格式检查、
Pyright 均通过。wheel/sdist 构建、仅安装 SDK 的独立环境导入检查通过；
Compose 静态配置检查通过。Docker 镜像构建因 Debian 包下载超时中止，
镜像运行及完整 Compose 启动尚未验收。

尚未部署到现有服务器，未修改同事的服务或 80/443 端口。

## Web 演示工作台（2026-09-05）

新增 React / Vite / TypeScript 前端，默认显示明确标记的示例文本，可切换中英文。
5 项 Playwright 浏览器测试通过：示例搜索与导出、移动端无横向溢出、鉴权错误及密钥不持久化、
上传与重复提交恢复、提交不确定时的风险确认，以及独立 PostgreSQL/MinIO 后端上的实际浏览器上传闭环。
上述行为按 5 个测试用例组合覆盖，真实后端用例使用模拟 ASR，不产生云端费用。

前端生产构建、类型检查、格式检查，以及后端 20 项离线测试通过。桌面和手机截图已目视检查。
前端新增 Compose 配置静态检查通过，完整 Compose 启动及公网 HTTPS / S3 CORS 仍需部署环境验收。

## Real browser ASR acceptance (2026-09-05)

With explicit user authorization, the local API and separate worker now use regular Beijing
DashScope, a dedicated database and private MinIO bucket, and `temporary_upload` evaluation mode.
Workspace and provider credentials remain separate; the provider key is in an ignored, owner-only
backend `.env` file.

- The browser uploaded the complete 111,426,188-byte MP4, lasting 698,333 ms, without splitting or compression.
- Upload, task creation, polling, result reading and all five export downloads used the real HTTP API.
- `qwen-audio-3.0-asr-flash-filetrans` returned 101 segments and 3,930 text characters.
- Every segment has valid timing within the recording: first start 120 ms, last end 698,070 ms.
- Restarting the worker after the provider task ID was persisted resumed the same task; only one attempt exists.
- JSON, TXT, Markdown, SRT and VTT downloaded successfully through the page. The connected workspace shows the result.
- Recordings, transcripts, screenshots and task identifiers stay local and are excluded from the public repository.
- The transcript has not been manually checked word by word.

Latest checks: 24 offline tests, 3 PostgreSQL/MinIO integration tests, Ruff and Pyright passed.
Frontend formatting, type checking and production build passed. Four regular browser tests passed;
the fifth, requiring the mock backend, was intentionally skipped in this run and previously passed
against the mock environment. Paid acceptance used a separate browser flow.

This verifies the persistent product workflow beyond the earlier standalone provider script.
Temporary storage remains local evaluation only; production public S3 URLs, HTTPS and full Compose
startup still require deployment acceptance.
