import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const python = resolve(
  '..',
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
for (const [command, args] of [
  [python, ['scripts/openapi.py']],
  [
    process.execPath,
    ['tools/node_modules/openapi-typescript/bin/cli.js', '.openapi.json', '-o', 'src/schema.d.ts'],
  ],
]) {
  const result = spawnSync(command, args, { stdio: 'inherit' })
  if (result.status !== 0) process.exit(result.status ?? 1)
}
