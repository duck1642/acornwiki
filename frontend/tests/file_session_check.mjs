import assert from 'node:assert/strict'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { FileSession } = await server.ssrLoadModule('/src/fileSession.svelte.ts')
  const { resolveLanguageByFilename } = await server.ssrLoadModule('/src/editorCore.ts')

  // 1. resolveLanguageByFilename handles uppercase extensions, CMakeLists.txt, and plain text.
  assert.equal(resolveLanguageByFilename('SCRIPT.PY')?.name, 'Python')
  assert.equal(resolveLanguageByFilename('CONFIG.JSON')?.name, 'JSON')
  assert.equal(resolveLanguageByFilename('CMakeLists.txt')?.name, 'CMake')
  assert.equal(resolveLanguageByFilename('notes.txt'), null)
  assert.equal(resolveLanguageByFilename('NOTES.TXT'), null)

  // 2. FileSession.dispose() settles a pending prepareClose() prompt instead of hanging.
  const session = new FileSession({
    entityLabel: 'file',
    initialPath: 'demo.txt',
    initialSnapshot: { path: 'demo.txt', content: 'original', version: '1', has_bom: false },
    read: async () => ({ ok: true, file: { path: 'demo.txt', content: 'original', version: '1', has_bom: false } }),
    save: async (path, content, _expected, hasBom) => ({ path, content, version: '2', has_bom: hasBom }),
    getPreferences: () => ({ autosave: false, auto_reload: true, reload_notice: true }),
    getFreezeEditors: () => false,
    onDocumentLoaded: () => {},
  })
  session.start()
  session.onEditorTextChange('edited')
  const pendingClose = session.prepareClose()
  assert.equal(session.prompt, true)
  session.dispose()
  assert.equal(await pendingClose, false)
  assert.equal(session.prompt, false)
} finally {
  await server.close()
}

console.log('FileSession and editorCore checks passed')
