# Agensi 试点首轮调研与取舍

2026-11-22 · 基线 `acf812099bd70441646e7548df2d298fb9a246be`。本轮核对了 Web 任务详情、共享 MCP 工具、本地 MCP 文件边界、SDK/HTTP 导出和渲染器。仓库原先没有可分发的剪辑 Skill。以下产品与上游版本均为文档或源码核对，实际使用耗时未实测。

| 参考 | 解决的问题与适用前提 | 首轮决定与理由 |
| --- | --- | --- |
| Descript [转写](https://www.descript.com/transcription)、[自动转写帮助](https://help.descript.com/script-editing/automatic-transcription)、[字幕导出](https://help.descript.com/export-and-share/subtitles) | 导入或录制后进入可编辑原稿，再单独导出 SRT/VTT。需等待同步与转写，文档没有可对比的首份 SRT 耗时。卡住可查同步和服务状态，已有结果可校正。 | **改造后采用**。用现有任务原话加独立导出交付；导出失败仍保留原任务，SRT 缺时码时用 JSON。 |
| Riverside [Magic Clips](https://riverside.com/magic-clips)、[候选列表与条件](https://support.riverside.com/hc/en-us/articles/12124048765981-About-Magic-Clips)、[按剪辑版本生成](https://riverside.com/university-videos/generate-magic-clips-from-edits) | 录制或上传后从项目 Made for You 预览候选并编辑。自动候选要求超过 3 分钟且有稿，出结果耗时未公布；若缺素材可移入项目或上传，可按套餐生成额外候选，来源也可指定为已剪辑版本。 | **改造后采用**。交付可逐条核对的候选和理由，由剪辑师在自己的素材版本上决定取舍；无需另装编辑器，也不限定最短时长。 |
| WhisperX `v3.8.6` [对齐实现](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py)、[回归用例](https://github.com/m-bain/whisperX/blob/v3.8.6/tests/test_word_timestamp_interpolation.py) | CTC 通配符处理数字等未知字符；`ignore` 保留未对齐词的缺失端点。测试用合成 emission 检查 `4,9`、`99`、NaN 与时间赋值，需要模型字典及已识别文本。 | **改造后采用**。借鉴断言方式，覆盖原样数字、缺端点和逆序时间。保留缺失值与源时间基准。上游测试未执行。 |
| [Agent Skills 规范](https://agentskills.io/specification)、Agensi [可售范围](https://www.agensi.io/docs/what-you-can-sell)、[打包规则](https://www.agensi.io/docs/packaging) | `SKILL.md` 加可选文本、脚本与资产。平台分发 Skill，Voice Ingest MCP 需独立连接并列为依赖。文档称只向 Agent 提供已上线的 listing，建议先用自己的 Agent 本地试。 | **直接采用** Skill 结构与独立 MCP 依赖。双 MCP 共存、实际客户端鉴权和上架前定向分发未验证。 |
| FastMCP [4.2.4](https://github.com/PrefectHQ/fastmcp/releases/tag/v4.2.4)；Playwright [1.65.1](https://github.com/microsoft/playwright/releases/tag/v1.65.1)、[发布说明](https://playwright.dev/docs/release-notes) | 本地锁定及实际版本分别为 FastMCP / fastmcp-slim **4.0.2**、Playwright / Core / Test **1.63.0**。FastMCP 更新涉及 OAuth 代理及组件挂载等；Playwright 新增 WebMCP 测试等，依赖对应浏览器版本。当前 MCP 用 Bearer 或本地 stdio，本轮浏览器验证的是常规按钮、剪贴板和文件下载。 | **暂缓升级**。锁定版本覆盖本轮需求；新版未实测。若实际客户端验证发现具体阻碍，再单独提交版本更新、复现和回滚方案。 |
| WaveSurfer [8.1.0](https://github.com/katspaugh/wavesurfer.js/releases/tag/8.1.0) | 先把原声定位交给剪辑师已有的编辑器；是否有必要增加 Web 波形入口，取决于试用中的定位耗时与失败原因。 | **暂缓**。出现定位困难，再复查 Regions / Timeline 的实现与测试，并测长录音内存和移动端。首轮未评估运行表现。 |
