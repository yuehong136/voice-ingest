# 发布前审查与独立部署演练

本轮基于第一阶段已交付的 v1 框架；只审查生命周期和正式部署路径，不增加厂商。
历史阿里 STT/TTS 验收见 [第一阶段记录](../plans/phase-1-aliyun-stt-tts.md)。
本页本地 mock 演练不替代真实厂商验收，也不代表已上线。

**最终对象存储决定（2026-09-08）：** 使用 PGSTY Silo 社区维护分支，直接固定最新稳定镜像
`pgsty/silo:RELEASE.2026-09-03T13-18-01Z`；部署和集成测试使用同版。
上游源码 commit 为 `9b11dc9469e650815b775cb47b039610644f5da4`；实际拉取的 manifest 摘要
`sha256:b616a0cf8cb281e7e6bb3c9b1fb53875b4016a2878223925541c18f82d6c5ca3`
与[发布记录](https://github.com/pgsty/silo/releases/tag/RELEASE.2026-09-03T13-18-01Z)一致。
它采用 AGPL-3.0-or-later，不要求 AIStor 激活文件。RAGFlow 当前也采用该维护线，
但没有足够数据认定它是社区使用量第一；项目必须以自己的真实契约和恢复验收为依据。

此前曾配置 AIStor Free，并因缺少激活文件暂停实测；用户明确选择社区最新方案后，
已移除许可证环境变量和 overlay。该限制不再阻塞当前部署，AIStor 不属于本轮默认方案。

历史核验发现此前默认的 MinIO 2025-06 镜像受
[GHSA-hv4r-mvr4-25vw](https://github.com/minio/minio/security/advisories/GHSA-hv4r-mvr4-25vw) 影响，
社区仓库已归档。旧镜像已从正式默认配置移除，历史兼容测试仅使用独立资源与合成数据。
升级版本选择不等于已经完成安全审计；当前 Silo 仍需通过 S3 API、CORS 和备份恢复验收。

## 本轮修复

- 删除结果后保留幂等墓碑，STT/TTS 的 retry 均拒绝 `result_deleted`，即使确认重复费用风险也不放行。
- 删除等待当前 Worker 租约结束并提升 generation；陈旧 checkpoint 无法恢复结果指针。
- 转写导出按需生成下载内容，不再写回 S3，避免导出和删除并发时重新生成私有对象。
- retry 的回执检查只读；重建完整回执由取得租约的 Worker 执行，避免检查和删除竞争时重建对象。
- Web 禁止重试已删除任务；合成未知提交必须勾选重复费用确认。
- Compose 支持独立配置文件、三个宿主端口以及精确 Web Origin；默认仅绑定回环地址。
- 正式 Python 镜像使用构建上下文白名单，包含离线对象备份工具，不发送 `.local`、凭据和录音。
- 正式镜像创建独立 `voice-ingest` 用户，避免 Debian 预置 `voice` 组导致构建失败；应用代码由 root 持有，服务用户只读。
- MinIO 初始化显式使用服务端 stale-upload 扫描（24h 阈值、6h 周期），不发送不受支持的 S3 multipart lifecycle 动作。
  通用 S3 初始化继续使用标准 lifecycle，并保留已有规则。
- 测试镜像在构建时冻结并安装依赖；测试和浏览器后台启动使用 `uv run --no-sync`，不在容器运行时重复访问包索引。

数据库结构未改变，初始及增量迁移保持不变。

## 部署与升级

按 [部署文档](../deployment.md) 准备独立项目。API/Worker 使用同一配置文件和部署注册表。
`--env-file` 用于 Compose 变量插值，`VOICE_ENV_FILE` 指向容器使用的文件；两者必须一致。
所有端口、桶、卷和网络都要与现有服务分开。正式镜像与集成测试统一固定为 Python 3.13.11 / Debian bookworm，
SDK 继续保留 Python 3.12 独立安装检查。Web 使用多阶段构建和 Nginx。

以下示例从仓库根目录执行；`release-source.env`、`release-restore.env` 是人工准备的受控配置文件，
不入 Git。分别设置 `VOICE_ENV_FILE` 为自身绝对路径，独立端口、桶和凭据。
保留 `.env.example` 中固定的 Silo `VOICE_MINIO_IMAGE`，无需注册或挂载 AIStor 激活文件。
先运行同样 Compose 参数的 `config --quiet` 检查，避免打印包含凭据的展开配置。
更改浏览器地址后同步 `VOICE_WEB_ORIGIN`；`VOICE_S3_PUBLIC_ENDPOINT` 必须同时可被浏览器和厂商访问。

```sh
docker compose --project-name voice-release-source --env-file .local/release-source.env -f deploy/compose.yaml -f deploy/compose.web.yaml up -d --build
docker compose --project-name voice-release-source --env-file .local/release-source.env -f deploy/compose.yaml -f deploy/compose.web.yaml ps
```

升级前记录源码 SHA、镜像 ID、Alembic revision、非敏感部署配置版本，备份下述完整数据集。
先停止入口及 Worker，再运行目标版本的 `migrate` 和 `storage-init`，成功后启动 API/Worker/Web。
不要同时运行旧版 Worker 和不兼容的新 schema；不要重写 0001 或清库。
失败时停在维护状态，选择恢复到新的独立资源；本工具不自动 downgrade，也不覆盖现有数据库。

## 一致性备份与空目标恢复

工具入口：[deployment_snapshot.py](../../scripts/deployment_snapshot.py)，仅依赖宿主 Python 标准库和 Docker Compose。
对象工具随正式镜像安装：[storage_snapshot.py](../../deploy/storage_snapshot.py)。

前提：只有这个 Compose 项目拥有写权限，没有额外 Worker/API 或其他程序写同一数据库和桶。
先完成或显式中止全部上传；未完成的 multipart 状态不能迁移到新桶。当前工具仅支持未开启版本化的桶。
备份目录包含正文、录音、原始响应、数据库内的临时 URL，须限制文件权限、加密并与源码分开保存。
凭据、部署注册文件、TLS 配置另行受控备份；本工具不复制密钥或保存 Compose 展开配置。

```sh
python scripts/deployment_snapshot.py backup --project voice-release-source --env-file .local/release-source.env --directory .local/backup-001
```

工具停止原先运行的 Web/API/Worker，保留 PostgreSQL/S3；在同一停写窗口生成 `pg_dump` 和对象快照。
数据库 dump、对象清单及每个对象都有 SHA-256。最后的 `snapshot.json` 表示整组备份完成，
成功后恢复原先运行的服务；失败时保持维护状态，不宣称备份成功。中途失败的目录不要继续覆盖使用。

恢复只能使用不同的 Compose project。先创建空 PostgreSQL 和空桶，**不要运行 migrate、API 或 Worker**：

```sh
docker compose --project-name voice-release-restore --env-file .local/release-restore.env -f deploy/compose.yaml -f deploy/compose.web.yaml build
docker compose --project-name voice-release-restore --env-file .local/release-restore.env -f deploy/compose.yaml -f deploy/compose.web.yaml up -d --wait postgres s3
docker compose --project-name voice-release-restore --env-file .local/release-restore.env -f deploy/compose.yaml -f deploy/compose.web.yaml run --rm --no-deps storage-init
python scripts/deployment_snapshot.py restore --project voice-release-restore --env-file .local/release-restore.env --directory .local/backup-001
```

工具拒绝原项目、已运行的入口/Worker、非空 public schema、非空桶和损坏对象。
`pg_restore` 使用单事务，不清库；对象恢复失败可能留下部分对象，应保留诊断并换新的空目标，不能直接启动。
恢复不会自动启动业务。检查配置与快照中的部署 revision 匹配，检查未完成任务及租约，确认不会启动第二组
针对相同远端任务的 Worker。旧源环境仍在运行时，恢复目标只用于已完成数据的只读核验；切换执行权必须先停旧 Worker。

```sh
docker compose --project-name voice-release-restore --env-file .local/release-restore.env -f deploy/compose.yaml -f deploy/compose.web.yaml run --rm --no-deps migrate
docker compose --project-name voice-release-restore --env-file .local/release-restore.env -f deploy/compose.yaml -f deploy/compose.web.yaml up -d api web
```

核验任务、Attempt、事件数量和结果摘要，读取转写、导出、下载并解码音频。
最后在确认执行权后启动 `worker`。数据库备份不能撤销厂商已发生的调用和费用；未知提交仍需人工处理，禁止自动重提。

## 删除与恢复审查边界

HTTP 删除先提交数据库墓碑，再删除 S3 对象；存储失败或进程退出后需要重放同一 DELETE，直到成功。
当前没有自动删除 outbox/后台物理清理保证。墓碑立即阻止查询和重试，但不能把失败请求当作物理删除证明。
陈旧 Worker 的数据库写入受 fencing 保护；已失去租约但尚在网络/存储调用中的进程仍可能留下私有孤立对象，
物理清理应在 Worker 停止后重放 DELETE。已经开始的合法下载也不能撤回。
自动清理与保留期策略是后续工作，不作为本轮已实现能力。

## 验收记录

执行日期：2026-09-08。下列证据分开记录，不能据此宣称部署完成。

| 项目 | 状态与证据 |
| --- | --- |
| 生命周期修复、初始化与快照工具 | 已实现；详见本页修复列表及行为测试 |
| Python 检查与单元测试 | Windows 执行 make check 等价项：Ruff 检查、80 文件格式检查、Pyright 0 错误；53 passed、1 skipped（Windows 符号链接权限）、5 integration deselected |
| 独立 PostgreSQL/S3 集成与迁移 | 最新 Silo + PostgreSQL 16 + Python 3.13.11 的 Linux 全量测试 **59 passed**，含 5 项集成/迁移及 Windows 跳过的符号链接用例；559.40 秒。6 条 Alembic path_separator 弃用提示，无失败 |
| 前端类型与构建 | 通过；浏览器模拟接口测试 7 项通过 |
| SDK 独立安装 | Python 3.12 独立 wheel 安装通过，无服务端或推理依赖 |
| 正式镜像 | Python 3.13.11 和 Nginx 镜像构建通过；修复预置 voice 组冲突及 bootstrap lifecycle 拒绝 |
| 最新 Silo | 镜像实际版本/源码 commit 与 manifest 摘要核对通过；初始化成功；私有对象匿名 GET 403、签名 GET 200、指定 Origin CORS 放行、其他 Origin 不放行、未认证 API 401 |
| 生产 Compose 浏览器闭环 | 正式 Nginx/API/Worker/PostgreSQL/Silo 上两项浏览器测试通过：STT 上传→明确提交→结果，以及 TTS 创建→播放进度→下载；均为 mock 推理 |
| 成对 PostgreSQL/S3 备份恢复 | 完整停写备份→独立空目标恢复通过；1 个资产、1 个上传、2 个任务、2 个 Attempt、11 条事件的记录数量与完整记录 SHA-256 一致；13 个对象逐一读回核对大小、SHA-256、Content-Type 和元数据一致 |
| 恢复后的业务读取 | SDK 核对五种转写导出及合成结果、音频摘要一致；恢复后的 Web 播放并下载原任务音频，下载摘要与原始制品一致；未启动目标 Worker、未创建新任务或重复推理 |
| 文档与 skill | 四份正文同步到个人 skill；链接、逐字节一致性与官方 skill 校验通过 |

当前接手顺序：核对固定 Silo 镜像 → 初始化独立新资源 →
验证 S3 签名/CORS 与未授权访问 → 通过正式 Web 创建 STT/TTS mock 任务并跨 SDK 核对结果 →
备份并恢复到独立空目标，对比任务/Attempt/事件数量、全部导出及音频 SHA-256 →
验证恢复后音频可解码播放，再回填本表。真实阿里调用仍采用单独显式启用的付费验收流程。

本机受控证据位于 `.local/release-rehearsal/`：`backup-silo-001/` 为成对快照，
`source-evidence.json`、`database-comparison.json`、`restored-web.png` 和 `restored-speech.wav`
记录读取与恢复比对。内容只使用合成素材，仍不提交 Git。源码、文档与命令足以在新机器重做验收。
本轮演练服务结束后停止，独立卷保留；此前阿里真实验收数据和记录未删除。

首次 Linux 命令在测试收集前因 `uv run` 重复构建 editable 包、访问 PyPI 超时而失败；
改用镜像已冻结的依赖后，以 `docker compose -f deploy/compose.test.yaml run --rm tests uv run --no-sync pytest -q`
重新执行全部 59 项并通过，默认测试启动命令也已同步修正。此失败属于依赖启动路径，不能把未执行的测试当作通过。
恢复读取曾在 API 尚未启动时收到连接失败；等待 Compose 健康状态后，SDK 和浏览器读取均通过。

公网 TLS、真实域名、外网访问和 Aliyun `signed_url` 回源需要实际托管环境，本机回环测试不能证明。
第一阶段实际 Aliyun 验收使用 `temporary_upload`，该历史记录继续保留，不改写成正式公网链路已通过。
