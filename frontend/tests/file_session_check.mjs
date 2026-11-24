import assert from 'node:assert/strict'
import { undoDepth } from '@codemirror/commands'
import { EditorSelection, EditorState } from '@codemirror/state'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { FileSession } = await server.ssrLoadModule('/src/fileSession.svelte.ts')
  const { createBaseEditorExtensions, replaceEditorDocument, resolveLanguageByFilename } = await server.ssrLoadModule('/src/editorCore.ts')

  // 1. resolveLanguageByFilename handles uppercase extensions, CMakeLists.txt, and plain text.
  assert.equal(resolveLanguageByFilename('SCRIPT.PY')?.name, 'Python')
  assert.equal(resolveLanguageByFilename('CONFIG.JSON')?.name, 'JSON')
  assert.equal(resolveLanguageByFilename('CMakeLists.txt')?.name, 'CMake')
  assert.equal(resolveLanguageByFilename('notes.txt'), null)
  assert.equal(resolveLanguageByFilename('NOTES.TXT'), null)

  // 2. FileSession emits explicit 'initial' vs 'reload' reasons and dispose() settles prepareClose().
  let disk = { path: 'demo.txt', content: 'original', version: '1', has_bom: false }
  const loadReasons = []
  const session = new FileSession({
    entityLabel: 'file',
    initialPath: 'demo.txt',
    initialSnapshot: { ...disk },
    read: async () => ({ ok: true, file: { ...disk } }),
    save: async (path, content, _expected, hasBom) => ({ path, content, version: '2', has_bom: hasBom }),
    getPreferences: () => ({ autosave: false, auto_reload: true, reload_notice: true }),
    getFreezeEditors: () => false,
    onDocumentLoaded: (_content, reason) => { loadReasons.push(reason) },
  })
  session.start()
  assert.deepEqual(loadReasons, ['initial'])

  disk = { path: 'demo.txt', content: 'external', version: '2', has_bom: false }
  await session.checkExternalNow()
  assert.deepEqual(loadReasons, ['initial', 'reload'])

  session.onEditorTextChange('edited')
  const pendingClose = session.prepareClose()
  assert.equal(session.prompt, true)
  session.dispose()
  assert.equal(await pendingClose, false)
  assert.equal(session.prompt, false)

  // 3. replaceEditorDocument('reload') clears undo history while preserving clamped line/column selection and scroll.
  const baseExt = () => createBaseEditorExtensions([])
  const scrollDOM = { scrollTop: 320, scrollLeft: 48 }
  const outerScroll = { scrollTop: 510, scrollLeft: 12 }
  const fakeView = {
    state: EditorState.create({ doc: 'alpha\nbeta gamma\ndelta', extensions: baseExt() }),
    scrollDOM,
    dom: { isConnected: true },
    setState(next) { this.state = next },
  }
  // Create a local edit so undoDepth > 0 and move selection to line 2, col 5..10 ("gamma").
  fakeView.state = fakeView.state.update({
    changes: { from: 0, to: 5, insert: 'ALPHA' },
    selection: EditorSelection.single(11, 16),
  }).state
  assert.ok(undoDepth(fakeView.state) > 0)

  // Reload with a shorter line 2: undo history must reset to 0, selection clamps cleanly, scroll is restored.
  replaceEditorDocument(fakeView, 'one\ntwo\nthree', baseExt(), 'reload', outerScroll)
  assert.equal(undoDepth(fakeView.state), 0)
  const main = fakeView.state.selection.main
  const line2 = fakeView.state.doc.line(2)
  assert.equal(main.anchor, line2.to)
  assert.equal(main.head, line2.to)
  assert.equal(scrollDOM.scrollTop, 320)
  assert.equal(scrollDOM.scrollLeft, 48)
  assert.equal(outerScroll.scrollTop, 510)
  assert.equal(outerScroll.scrollLeft, 12)
} finally {
  await server.close()
}

console.log('FileSession and editorCore checks passed')
