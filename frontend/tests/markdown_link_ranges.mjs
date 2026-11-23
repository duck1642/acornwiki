import assert from 'node:assert/strict'
import { markdownLinkRanges } from '../src/markdownLinkRanges.ts'

const source = `😀 [link](a(b).md "Title") ![alt](<image file.png>)
[![nested](pic.png)](target.md#section)

[reference][id]

[id]: folder/file.md "Reference"

\\[escaped](skip.md)

    [indented](skip.md)

~~~md
[fenced](skip.md)
~~~

\`[inline](skip.md)\`
`
const ranges = markdownLinkRanges(source)
assert.deepEqual(ranges.map(range => range.target), [
  'a(b).md', '<image file.png>', 'pic.png', 'target.md#section', 'folder/file.md',
])
for (const range of ranges) assert.equal(source.slice(range.from, range.to), range.target)

assert.deepEqual(markdownLinkRanges('[x](a\\(b\\).md)').map(range => range.target), ['a\\(b\\).md'])
assert.deepEqual(markdownLinkRanges('[x](old.md)\n\n```\n[skip](no.md)').map(range => range.target), ['old.md'])
assert.deepEqual(markdownLinkRanges('data\r\r    [code](old.md)\r\r[working](old.md)').map(range => range.target), ['old.md'])
assert.throws(() => markdownLinkRanges('https://host/[name](old.md)'), /automatic web address/)
assert.deepEqual(markdownLinkRanges('xwww.example.com/[name](old.md)').map(range => range.target), ['old.md'])
console.log('Markdown link source range checks passed')
