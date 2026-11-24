import assert from 'node:assert/strict'
import { history, isolateHistory, redo, undo } from '@codemirror/commands'
import { EditorState, Transaction } from '@codemirror/state'
import { noteLineEndings, noteText } from '../src/noteLineEndings.ts'

function open(content) {
  return EditorState.create({ doc: content, extensions: [history(), noteLineEndings(content)] })
}

for (const content of ['', 'one', 'one\ntwo\n', 'one\r\ntwo\r\n', 'one\r\ntwo\n\rthree\n']) {
  const state = open(content)
  assert.deepEqual(state.doc.toJSON(), content.split(/\r\n?|\n/))
  assert.equal(noteText(state), content)
}

let state = open('😀 first\r\nsecond\n\nthird\r\n')
const edit = changes => {
  state = state.update({ changes, annotations: isolateHistory.of('full') }).state
}
const apply = command => assert.equal(command({
  state,
  dispatch: transaction => { state = transaction.state },
}), true)

// Insert text at the tracked LF and add a line while retaining the existing LF.
edit({ from: state.doc.line(2).to, insert: '!\nadded' })
assert.deepEqual(state.doc.toJSON(), ['😀 first', 'second!', 'added', '', 'third', ''])
assert.equal(noteText(state), '😀 first\r\nsecond!\r\nadded\n\nthird\r\n')

// Delete both LF breaks and change another line in the same transaction.
edit([{ from: 0, to: 2, insert: '💡' }, { from: state.doc.line(3).to, to: state.doc.line(5).from }])
assert.equal(noteText(state), '💡 first\r\nsecond!\r\naddedthird\r\n')
apply(undo)
assert.equal(noteText(state), '😀 first\r\nsecond!\r\nadded\n\nthird\r\n')
apply(redo)
assert.equal(noteText(state), '💡 first\r\nsecond!\r\naddedthird\r\n')
apply(undo)
apply(undo)
assert.equal(noteText(state), '😀 first\r\nsecond\n\nthird\r\n')

state = open('first\nsecond\r\nthird')
edit({ from: state.doc.length, insert: '\nlast' })
assert.equal(noteText(state), 'first\nsecond\r\nthird\nlast')

state = open('one')
edit({ from: state.doc.length, insert: '\r\ntwo' })
assert.equal(noteText(state), 'one\ntwo')

state = open('first\r\nsecond\n\nthird')
for (const time of [1000, 1001]) {
  const breakPosition = state.doc.line(2).to
  state = state.update({
    changes: { from: breakPosition, to: breakPosition + 1 },
    userEvent: 'delete.backward',
    annotations: Transaction.time.of(time),
  }).state
}
assert.equal(noteText(state), 'first\r\nsecondthird')
apply(undo)
assert.equal(noteText(state), 'first\r\nsecond\n\nthird')
apply(redo)
assert.equal(noteText(state), 'first\r\nsecondthird')

state = open('first\nsecond\rthird')
edit({ from: state.doc.line(3).from, insert: '\n' })
assert.equal(noteText(state), 'first\nsecond\r\r\nthird')
assert.deepEqual(open(noteText(state)).doc.toJSON(), state.doc.toJSON())

console.log('Note line ending checks passed')
