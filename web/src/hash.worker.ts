import { createSHA256 } from 'hash-wasm'
self.onmessage = async ({ data: file }: MessageEvent<File>) => {
  try {
    const hash = await createSHA256()
    hash.init()
    for (let offset = 0; offset < file.size; offset += 2 * 1024 * 1024) {
      const chunk = await file.slice(offset, offset + 2 * 1024 * 1024).arrayBuffer()
      hash.update(new Uint8Array(chunk))
      self.postMessage({ progress: Math.min(1, (offset + chunk.byteLength) / file.size) })
    }
    self.postMessage({ hash: hash.digest() })
  } catch {
    self.postMessage({ error: 'Could not read this file.' })
  }
}
