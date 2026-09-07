# 第一阶段交接与验收

更新日期：2026-09-07。状态：第一阶段功能与验收完成。框架、阿里适配器与全部入口已实现，
离线、独立基础设施及本阶段真实阿里 STT/TTS 闭环通过，用户已确认音频清晰完整、无明显异常。
本文记录本地与真实厂商验收；远程 CI 以提交对应流水线为准。生产部署和更广泛的语音质量评测仍未验收。
仓库 D:\project\voice-ingest；先确认 git top-level 和工作区变化，再读 AGENTS.md、
[当前架构](../architecture.md)、[v1 设计](../design/voice-platform-v1.md)。
历史验收见 [acceptance.md](../acceptance.md)，不能代替本阶段验证。

## 固定范围

只使用 /v1；搭建 STT/TTS 框架并完整接通阿里云。保留现有资产和任务，新增迁移。
STT 主验收模型 qwen-audio-3.0-asr-flash-filetrans；保留现有 fun-asr 支持。
HTTP 统一还包括 `/v1/health/live`、`/v1/health/ready`、`/v1/metrics`、`/v1/docs`、
`/v1/openapi.json` 和远程 MCP `/v1/mcp/`；旧的无版本路径不保留兼容层。
TTS 主验收 qwen-audio-3.0-tts-flash / longanhuan_v3.6 / MP3；实施时核验官方地域和音色支持。
使用预置音色和完整文件，不加入其他厂商、本地运行时部署、声音克隆、实时会话或自动分段。

## 实施顺序

1. 文档和个人 skill，固定决策并保留全部调研证据。
2. 模型/部署注册、共享任务/制品、配置快照、恢复回执；迁入阿里 STT。
3. 阿里 TTS 及 API、SDK、CLI、两种 MCP、Web；生成契约。
4. 单元/契约、独立 PostgreSQL/S3、迁移、SDK 安装、浏览器与真实厂商验收。
5. 回填下面的证据表，更新架构与 skill 的参考副本，不将未跑的验收写成通过。

## 完成标准

| 层面 | 必须证明 |
|---|---|
| 阿里 STT | 上传 → 创建 → 轮询 → Worker 重启恢复同一任务 → 结果 → 五种导出 |
| 阿里 TTS | 模型/音色查询 → 文本创建 → 完整制品 → 查询 → 解码、播放与下载 |
| 多入口 | 一个入口创建、其他入口查询，不实现第二套业务流程 |
| 可扩展性 | 注入不同协议测试适配器无需改核心 Worker；同步、异步、流结果均有测试 |
| 隔离 | 多部署容量独立；Attempt 固定配置；仅本地禁止云端 |
| 恢复 | 超时/崩溃未知不重提；回执恢复；完整原始结果处理失败不重推理；旧 Worker 无法提交 |
| 取消 | 提交竞争保留远端信息；不完整音频不发布；remote_may_run 如实表达 |
| 隐私 | 正文、凭据和签名 URL 不出现在日志、异常、Trace；原始数据只进私有存储 |
| 工程 | 增量迁移、SDK-only 安装、make check 等价检查、前端生成类型/构建/E2E |
| 知识 | skill 官方校验、引用链接、镜像正文一致性、无上下文接手阅读路径 |

## 测试资源和真实验收

普通测试仅用合成数据和 mock。集成测试数据库必须叫 voice_test，每次使用独立 schema/bucket；
不得使用应用数据库。真实 ASR/TTS 付费验收单独显式启用，不从 .env 的存在推定许可。
只用明确授权的音频/文本和独立资源。先完成可审查的代码及 mock/基础设施验证，再执行已授权真实验收。
不在文档、skill 或源码存储密钥、用户录音、转写正文、真实厂商响应或任务标识。

检查入口：make check；Windows 无 make 时分别执行 Ruff、格式、Pyright、非 integration pytest。
前端 npm run types:generate、npm run check、npm run build、npm test。
真实验收需记录模型/部署、时间、尝试次数、结果摘要、重启证据；账单未核对则不写实际扣费。

## 当前实施证据

### 已实现

- STT/TTS 独立契约、共享 Job/Attempt/Event、部署目录与容量、有效选项及配置快照、local_only 路由拒绝。
- 阿里原有文件 STT 迁入适配器；新增 TTS WebSocket → 完整音频，校验结束事件、大小、摘要、格式、采样率与时长。
- 提交前持久化、未知不自动重提、旧 Worker 写入隔离、原始结果与音频回执、结果处理失败恢复且不重复推理。
- HTTP 全部 /v1；SDK、CLI、远程/本地 MCP 与 Web 合成入口，生成类型同步。模型/音色目录只声明已配置能力。
- 增量迁移 0002；已有数据、0001 和历史验收文档保留。只启动过独立测试资源，未改应用或远程知识库部署。
- 14 个开源项目及补充参考、厂商差异、设计与路线，个人 skill 和对应参考副本。

### 已验证（2026-09-07，本地工作区）

| 检查 | 实际结果与边界 |
|---|---|
| make check 的 Windows 等价检查 | Ruff、Ruff 格式检查、Pyright 通过；非 integration pytest **44 passed / 1 skipped / 5 deselected**。本机无 make；跳过项仅为 Windows 无创建符号链接权限 |
| Linux / PostgreSQL / S3 | 定向重验 **6 passed**：5 项集成/迁移用例，加 Windows 跳过的真实符号链接访问边界用例。数据库名 voice_test，每个测试独立 schema/bucket |
| 持久化与媒体 | PostgreSQL 并发领取、幂等与旧代次写入；30/60 分钟合成 WAV 上传和真实 ffprobe；TTS 完整 WAV 保存/下载与实际解码；0001→0002 数据保留及 ORM 差异为空 |
| 框架行为 | 独立直接/异步测试适配器、部署容量与配置快照、local_only、提交未知、取消竞争、完成回执后进程退出、最终存储 marker 失败恢复、归一化失败不重复推理、残缺音频不发布、日志隐私、跨入口契约 |
| 前端 | 类型生成、格式/TypeScript、生产构建通过；浏览器 **7 passed**，含独立 MinIO 上传转写和 PostgreSQL/S3 合成。真实合成音频播放进度/下载、窄屏、密钥与正文不持久化等检查通过 |
| SDK-only | 构建 wheel 后安装到独立虚拟环境，仅安装基础依赖；导入 SDK/合成契约通过，未安装 FastAPI、SQLAlchemy、FastMCP、websockets、torch、dashscope |
| 知识交付 | skill 官方 quick_validate、项目相对文档链接检查、三个参考副本正文一致性及 SHA-256 检查通过 |
| 工作区卫生 | 提交前 git diff --check 通过；初始迁移未修改；提交范围排除密钥、.env、真实音频及私有验收数据。提交和推送状态以 Git 历史及远端 HEAD 为准 |

首轮 Linux 全量运行的 50 个测试主体通过，但 3 个 S3 清理步骤失败，不算全量通过。
根因是旧版 MinIO 要求 DeleteObjects 的 Content-MD5；补齐标准校验后，上述全部 5 项集成/迁移及
Linux 文件边界测试通过（合计 6 项）。不能把首轮失败隐藏为绿色全量运行；当前证据由修复后的定向重验
与 Windows 全量离线检查组成。

浏览器测试最初因默认 5 秒断言/30 秒总预算在 Docker Desktop 负载下超时；观察到上传和任务持续推进。
独立后端用例改为 120 秒总预算、30 秒上传/60 秒任务等待，最多两个浏览器 Worker，随后 7 项全部通过。
这些是测试等待上限，不是性能承诺。最后的截图检查还修复了合成列表与详情暂时显示不同状态的问题。
该显示修正后两项合成浏览器用例再次通过（2 passed）。测试截图只含合成素材，位于 web/test-results，
最后的定向复验截图保存在 .local/browser-review-final；它们是本机验证产物，不是厂商质量证明。
测试完成后已清理本轮独立 Compose 容器、网络及测试卷；没有清理应用资源。

### 尚未验证

- 实际账单金额与付费流水尚未核对；调用请求成功不能证明具体扣费金额。
- 本地验收记录不包含远程 CI 结果，须按对应提交检查流水线；应用部署/生产行为尚未验收。
- 更长录音、多说话人、多语言与复杂文本的本阶段真实质量回归；下面的短样本用于框架业务闭环验收。

### 本阶段真实阿里验收（2026-09-07）

用户明确授权使用提供的百炼 Key 直接执行验收，并在试听后确认“清晰完整，无明显异常”。
本轮使用自建的中性短文本，先 TTS 后将生成音频上传用于 STT，不读取用户私人录音。
自动流程时间为北京时间 17:35:58 至 17:36:56；之后补充媒体、浏览器与其他入口检查。

| 项目 | 实际证据 |
|---|---|
| 隔离 | 独立 Compose 项目、voice_acceptance PostgreSQL、私有 voice-acceptance-* bucket；不连接其他应用资源 |
| TTS | qwen-audio-3.0-tts-flash / longanhuan_v3.6；北京默认端点；MP3、22050 Hz、56933 字节、约 3.553 秒；匹配结束事件和完整原始协议已保存 |
| STT | qwen-audio-3.0-asr-flash-filetrans；上传本轮 MP3，经阿里临时文件传输提交；归一化文本去除标点后与原输入完全一致 |
| 重启恢复 | 5 个独立 Worker 进程；TTS 2 个执行代次、STT 3 个执行代次。STT 提交后退出原 Worker，以新进程恢复已知远端任务 |
| 调用次数 | 两个任务的 Attempt 均为 1，无重新合成或重新识别；后续入口核对仅查询和下载 |
| 完整性 | ffmpeg 全文件解码通过；浏览器音频时长 3.552625 秒，播放进度正常；浏览器下载 SHA-256 与 SDK 制品一致 |
| 导出 | JSON/TXT/Markdown/SRT/VTT 五种导出通过；Web 下载 JSON 与 SDK 导出结构一致 |
| 多入口 | SDK 经 HTTP 创建；HTTP MCP、本地 MCP 经公开 SDK、CLI 均查询同一真实任务；Web 查看、播放、下载成功，窄屏无水平溢出 |
| 人工试听 | 用户确认清晰完整、无明显异常；记录为本样本试听验收，不扩大为音质评测结论 |

原始响应、协议事件、厂商请求标识、部署快照、尝试参数、数据库状态和音频保存在受控资源；
本机证据根目录为 `.local/aliyun-phase1-acceptance/output/`，其下随机目录中的 evidence.json 是私有汇总。
密钥不进入项目文档、个人 skill 或 Git；凭据文件及证据父目录限制为当前 Windows 用户访问。
验收后停止 API、PostgreSQL、S3 服务，保留命名数据卷与证据，不执行清库或删除验收数据。
重新启动这些服务不会自动运行 Worker；禁止为复查结果再次执行付费 runner。

### 后续扩展与已知限制

- 海外、其他国内与已部署本地推理服务尚未集成；新增真实适配器只修改适配器与运行时装配，不能在 Worker 塞厂商分支。
- 首个 TTS 仅一个预置音色、MP3/22050 Hz；目录不探测账户授权，不提供实时会话、克隆或自动长文本分段。
- 配置变更后，旧 Attempt 如无法找到完全相同的配置快照会停止处理；须恢复原配置，不能换端点继续旧尝试。
  不提供同时加载同一部署 ID 多个历史版本的自动管理。更换部署时使用新 ID，旧部署保留到任务处理完毕。
- TTS 提交失败时，同一页面内的同一正文复用幂等键；刷新不会持久化正文或该页面的提交键。
  HTTP 结果不明确时先查询任务记录，不以刷新并再次提交作为恢复方式。
- 全文搜索、历史回听、对齐/说话人增强与模型质量评测产品化仍是后续范围。

## 可复现检查命令

在仓库根目录执行，Windows 不依赖 make：

```powershell
uv sync --all-extras --frozen
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m 'not integration'
npm ci --prefix web
npm ci --prefix web/tools
npm --prefix web run types:generate
npm --prefix web run check
npm --prefix web run build
docker compose -f deploy/compose.test.yaml build tests
docker compose -f deploy/compose.test.yaml up -d postgres s3
docker compose -f deploy/compose.test.yaml run --rm tests
docker compose -f deploy/compose.test.yaml --profile browser up -d browser
$env:VOICE_API_TARGET='http://127.0.0.1:18089'
$env:VOICE_WEB_TEST_KEY='browser-test-key'
npm --prefix web test
docker compose -f deploy/compose.test.yaml --profile browser down --volumes
uv build
uv venv .local/sdk-only
uv pip install --python .local/sdk-only/Scripts/python.exe dist/voice_ingest-0.1.0-py3-none-any.whl
.local/sdk-only/Scripts/python.exe scripts/check_sdk_install.py
uv run python scripts/validate_handoff.py
```

测试 Compose 不读 .env，不连接应用网络；只清理 voice-ingest-phase1-tests 项目自建资源。
S3 测试端口 19039、浏览器后端 18089 均只绑定 loopback。Linux SDK 检查将 Scripts/python.exe 换为 bin/python。
仓库 CI 增加同样的独立基础设施、浏览器集成、迁移、SDK-only 和生成契约一致性检查。
新增 CI 在推送后运行；按提交核验远程状态，不能用本地执行证据代替绿色流水线。

## 真实厂商验收入口（需显式启用，本轮已执行）

`scripts/accept_aliyun.py` 拒绝未带 `--allow-paid` 的执行，拒绝应用数据库、非阿里配置和普通 bucket。
先由操作者在独立 `voice_acceptance` 数据库运行迁移，建立私有 `voice-acceptance-*` bucket，并准备
受控 dotenv 文件：API key、S3、数据库、VOICE_PROVIDER=aliyun、区域、业务空间及区域匹配的常规百炼密钥；
VOICE_ALIYUN_SOURCE_MODE=temporary_upload。不要把该文件、录音或真实响应提交到仓库或发进聊天。
不要让其他 Worker 同时使用该验收数据库，以免打乱重启检查点。
脚本还会在调用前拒绝存在活动任务或未决远端任务的验收数据库；先处理原任务，不能反复新建调用。

在已获授权后才执行：

```powershell
uv run python scripts/accept_aliyun.py --config .local/acceptance.env --allow-paid --audio <授权录音绝对路径>
```

脚本使用 SDK 经 HTTP 创建任务，由多个独立 Worker 子进程跨重启执行，再经 MCP 查询；
先查询预置音色并生成 TTS MP3，再对指定录音执行 STT 并导出五种格式。若操作者未提供录音，可在明确授权后
使用 `--generated-source` 替换 `--audio`，以本次 TTS 音频作为 STT 输入，不访问私人录音。
同一轮仅创建一个 TTS 和一个 STT 任务；原始任务和对象保留，不自动重试推理。
私有证据保存在 .local/aliyun-acceptance/随机目录：任务信息、Worker 进程、导出、音频、摘要；不进文档正文。
后续每轮仍必须实际试听 speech.mp3，确认内容和完整性，并补充实际账户地域支持与账单状态；
脚本成功不等同于人工质量验收。本轮人工确认已记录在上方。
若失败，先检查原任务的状态/回执和厂商请求标识，不重新运行脚本来掩盖失败；重新运行会创建新任务并可能再次计费。

## 个人 skill 与交接

个人 skill：C:\Users\duxiaolong\.codex\skills\voice-platform-development\SKILL.md。
项目 docs 是权威正文，skill references 是同名参考副本，快照与同步索引位于 skill 的 references/index.md。
相关文档变化后同步对应副本并核对 SHA-256。换电脑的接手者无需个人 skill 即可沿 docs 完整接手。
