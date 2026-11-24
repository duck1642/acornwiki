import assert from 'node:assert/strict'
import { EditorSelection, EditorState } from '@codemirror/state'
import { keymap } from '@codemirror/view'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { createMarkdownEditorExtensions } = await server.ssrLoadModule('/src/markdownEditor.ts')

  function editor(doc, from, to) {
    return {
      state: EditorState.create({
        doc,
        selection: EditorSelection.range(from, to),
        extensions: createMarkdownEditorExtensions([]),
      }),
      dispatch(changes) {
        this.state = this.state.update(changes).state
      },
    }
  }

  function italicize(view, expected, selected = 'word') {
    const binding = view.state.facet(keymap).flat().find(({ key }) => key === 'Mod-i')
    assert.equal(binding.run(view), true)
    assert.equal(view.state.doc.toString(), expected)
    const { from, to } = view.state.selection.main
    assert.equal(view.state.sliceDoc(from, to), selected)
  }

  const bold = editor('**word**', 2, 6)
  italicize(bold, '***word***')
  italicize(bold, '**word**')

  const boldWithMarkers = editor('**word**', 0, 8)
  italicize(boldWithMarkers, '***word***', '**word**')
  italicize(boldWithMarkers, '**word**', '**word**')

  const plain = editor('word', 0, 4)
  italicize(plain, '*word*')
  italicize(plain, 'word')

  const nested = editor('**start *word***', 9, 13)
  italicize(nested, '**start word**')

  const cursor = editor('', 0, 0)
  italicize(cursor, '**', '')
  italicize(cursor, '', '')

  italicize(editor('**', 0, 2), '', '')
} finally {
  await server.close()
}

console.log('Markdown editor shortcut checks passed')
