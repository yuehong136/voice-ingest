# 采访剪辑清单

[English](clip-checklist.md) · [Voice Ingest](../../README.zh-CN.md)

用清单在自己的剪辑器中找到逐字原话。每条标明素材版本、入点和出点，并单列为什么值得选这段。

## 看采访示例

打开成品清单及配套字幕。在 GitHub 文件页选择 **Raw**，可另存为 `.srt`。同一句 “We lowered the review time from nine hours to four.” 在原版从 `00:00:07,000` 开始，在裁首版从 `00:00:02,000` 开始。[成品清单](../../skills/voice-ingest-clip-checklist/assets/example-checklist.md) · [原版 SRT](../../skills/voice-ingest-clip-checklist/assets/interview-original.srt) · [裁首五秒版 SRT](../../skills/voice-ingest-clip-checklist/assets/interview-trim-5s.srt)

预览发布后，可在 [GitHub Releases](https://github.com/yuehong136/voice-ingest/releases) 找到独立页面 `clip-demo.html`、短录屏 `clip-checklist-demo.mp4` 和 `voice-ingest-clip-demo.zip`。在浏览器打开 HTML，也可解压 ZIP 单独查看素材、字幕和清单。录屏演示如何定位并播放对应原话，示例用合成语音制作。

在剪辑器中打开清单对应的素材，把时间显示切到源素材时间。清单的出点表示结束边界。用 24 fps 的 Shotcut 标记时，结束边界的前一帧是最后一帧。使用前同时核对版本、位置和原话。

## 使用手头已有的 SRT

1. 按客户端的本地 Skill 安装方式加载[采访剪辑清单 Skill](../../skills/voice-ingest-clip-checklist/SKILL.md)。预览发布后，也可从对应 Release 下载并解压 `voice-ingest-clip-checklist.zip`。
2. 显式提供 SRT，并注明导出时使用的媒体文件名与版本，或序列名称与版本。说明时间从媒体起算，还是从序列起算。客户端不能读文件时，可用获准的附件方式或粘贴完整 cue。可直接使用[纯文本示例](../../skills/voice-ingest-clip-checklist/assets/paste-example.md)试跑。
3. 要求逐字引用、保留完整起止时间、单列选段理由。使用清单前，先在自己的剪辑器中核对至少一条。

提供原版 SRT 后，可以直接使用这段提问。

> 请使用采访剪辑清单 Skill。我提供的是 `interview-original.mp4` 的字幕，按源媒体时间起算。找出能说明结果的一段，给我逐字原话、字幕编号、起止时间、素材版本，并单列选段理由。

这条路径只需要能读取所提供字幕的 Agent，不需要 Voice Ingest 后端、MCP 或转录密钥。把私有字幕交给 Agent 前，先检查客户端的数据处理规则。Skill 中还包含可在本地运行的 Python 读取脚本，可核对字幕正文与时码。

## 使用录音或已有任务

先用合成录音[跑本地 mock](../../README.zh-CN.md#快速开始)，体验上传、查询和导出。Mock 结果为模拟文本。要获取真实识别的原话和时间戳，请[配置阿里 ASR](../../README.zh-CN.md#供应商与模型)，使用对应地域的 DashScope 密钥及供应商可访问的素材方式。只提交你有权处理的素材，云端转写可能计费。

在网页上传音频后先确认设置，再点「开始转写」。如果已有任务，打开它并点「复制给 Agent」，也可只把任务 ID 交给 Skill。剪贴板不可用时可手动复制同样的内容。在 [MCP 客户端配置](../../README.zh-CN.md#连接远程客户端)里填写服务密钥。交接消息只包含任务 ID 和操作指令。异机客户端须使用它能访问的后端地址。

| 遇到的情况 | 怎么继续 |
| --- | --- |
| 无权限或找不到任务 | 核对该工作区的后端地址、鉴权和任务 ID。如果 MCP 暂不可用，可在有权限的网页会话中下载 JSON 或 SRT，再通过获准的附件向 Agent 提供。 |
| 任务仍在运行 | 保留原 ID，稍后查询。上传文件与创建转写任务是两个步骤。 |
| 供应商提交结果不确定，任务需要处理 | 先核对状态和已有的供应商回执，再决定是否显式重试。Worker 不自动重提不确定的请求。再次提交可能再次计费。 |
| 缺少时间戳，SRT 导出失败 | 下载 JSON，保留原话和已有时间，并让 Agent 把待核对的条目列出。字幕和素材版本对不上时，等拿到配套字幕再使用选区。 |

## 素材去向与删除

配置的后端在 PostgreSQL 保存任务状态，在私有 S3 保存音频与结果。启用阿里后，Worker 会根据配置提交签名源地址，或把音频暂存到阿里临时文件服务。附件和 Agent 工具读取还遵循该客户端的数据规则。首次试用可用合成素材，凭据留在自己的配置中。[架构说明](../architecture.md) · [供应商配置](../deployment.md#real-asr-from-a-local-browser)

用 `uv run voice-ingest jobs delete JOB_ID` 删除任务结果。服务保留幂等墓碑，以防意外重复创建任务。源文件不再被任何任务使用时，可用 `uv run voice-ingest assets delete ASSET_ID` 删除。请确认删除成功，并按各自保留规则处理本地下载、备份及供应商保留的副本。[恢复与保留](../deployment.md#recovery-and-monitoring) · [删除语义](../operations/deployment-rehearsal.md#删除与恢复审查边界)
