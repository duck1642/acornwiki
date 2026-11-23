import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
const { applyMarkdownTargetReplacements, planMoveLinks } = await server.ssrLoadModule('/src/markdownLinkPlan.ts')
const { markdownLinkRanges } = await server.ssrLoadModule('/src/markdownLinkRanges.ts')
await server.close()

const source = '😀 [first](a.md#part) ![image](<some file.png>)\r\n\r\n[ref][id]\r\n\r\n[id]: a.md "Title"\r\n\r\n`[code](a.md)`\r\n'
const ranges = markdownLinkRanges(source)
assert.deepEqual(ranges.map(({ target }) => target), ['a.md#part', '<some file.png>', 'a.md'])
assert.equal(
  applyMarkdownTargetReplacements(source, ranges, ['../new.md#part', null, '../new.md']),
  '😀 [first](../new.md#part) ![image](<some file.png>)\r\n\r\n[ref][id]\r\n\r\n[id]: ../new.md "Title"\r\n\r\n`[code](a.md)`\r\n',
)
assert.equal(applyMarkdownTargetReplacements(source, ranges, [null, null, null]), source)
assert.throws(() => applyMarkdownTargetReplacements(source, ranges, [null]), /count/)
assert.throws(() => applyMarkdownTargetReplacements(source.replace('a.md#part', 'b.md#part'), ranges, [null, null, null]), /stale/)
assert.throws(() => applyMarkdownTargetReplacements(source, [ranges[0], ranges[0]], ['x', 'y']), /range/)
assert.throws(() => applyMarkdownTargetReplacements(source, ranges, [null, 123, null]), /replacement/)
const python = `import json, sys, tempfile
from pathlib import Path
from backend.app.bridge import Bridge
with tempfile.TemporaryDirectory() as tmp:
    bridge = Bridge()
    try:
        workspace = bridge.open_workspace(tmp)['workspace_id']
        print(json.dumps(bridge.plan_link_targets(workspace, 'note.md', 'a.md', 'new.md', json.load(sys.stdin))))
    finally:
        bridge._close()
`
const planned = spawnSync('python', ['-c', python], {
  cwd: new URL('../..', import.meta.url),
  input: JSON.stringify(ranges.map(range => range.target)),
  encoding: 'utf8',
})
assert.equal(planned.status, 0, planned.stderr)
assert.equal(
  applyMarkdownTargetReplacements(source, ranges, JSON.parse(planned.stdout)),
  '😀 [first](new.md#part) ![image](<some file.png>)\r\n\r\n[ref][id]\r\n\r\n[id]: new.md "Title"\r\n\r\n`[code](a.md)`\r\n',
)
const bridge = {
  list_plan_notes: async () => ['note.md'],
  read_plan_notes: async () => ({ notes: [{ path: 'note.md', content: source, version: 'v1' }], next_index: 1 }),
  plan_link_targets_batch: async (_id, _from, _to, notes) => notes.map(({ targets }) => targets.map(target => target.startsWith('a.md') ? target.replace('a.md', 'new.md') : null)),
}
const { rewrites, snapshots } = await planMoveLinks(bridge, 'workspace', 'a.md', 'new.md')
assert.equal(rewrites.length, 1)
assert.deepEqual(snapshots, [{ path: 'note.md', version: 'v1' }])
assert.equal(rewrites[0].version, 'v1')
assert.ok(rewrites[0].content.includes('[first](new.md#part)'))
const controller = new AbortController()
controller.abort()
await assert.rejects(planMoveLinks(bridge, 'workspace', 'a.md', 'new.md', controller.signal), { name: 'AbortError' })
console.log('Markdown link plan checks passed')
