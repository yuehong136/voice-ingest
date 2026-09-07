# README product screenshots

These are browser captures of the actual `web/` production build, using only the
explicit **Explore sample transcript** flow and the public fixtures in
[`web/src/demo.ts`](../../../web/src/demo.ts). They are UI examples, not real ASR
acceptance evidence. No user recordings, credentials, or private transcripts are
used. The images are not generated mockups and the capture script does not restyle
or replace the UI.

## Reproduce

From the repository root, with Node.js 24 LTS and Google Chrome installed:

```sh
cd web
npm ci
npm run screenshots
```

The command builds the frontend, starts an isolated production preview on
`127.0.0.1:4174`, opens fresh Playwright browser contexts, and closes the browser
and preview server when finished. Port 4174 must be free. As with the existing
browser tests, set `PLAYWRIGHT_CHANNEL` to use another installed supported channel.
Backend and external network requests are blocked during capture. No backend,
Docker stack, or API key is needed.

| File | Viewport | Content |
| --- | --- | --- |
| `workspace-en.png` | 1440 × 1200 | English workspace, full-page capture |
| `workspace-zh-CN.png` | 1440 × 1200 | Chinese workspace, full-page capture |
| `reader-mobile-en.png` | 390 × 844 | English reader, scrolled into view |
| `reader-mobile-zh-CN.png` | 390 × 844 | Chinese reader, scrolled into view |

Captures use a 1× pixel ratio, loaded local fonts, light appearance, UTC, and reduced
motion. Font rasterization can differ by operating system; these are documentation
assets rather than pixel comparison baselines. Review every image after regeneration
for clipping, readable text, and the visible sample-content label. Keep both root
READMEs in sync with the corresponding language images.

中文：以上图片均为项目实际运行后的浏览器截图，使用明确标注的内置示例，
不代表真实语音识别效果。重新生成后需检查中英文画面、文字裁切与示例标记。
