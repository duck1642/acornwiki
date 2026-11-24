import { invertedEffects } from '@codemirror/commands'
import { EditorState, MapMode, RangeSet, RangeValue, StateEffect, StateField, type Extension, type Range } from '@codemirror/state'

class LineEnding extends RangeValue {
  // Anchor the marker to the newline character after this position.
  readonly startSide = 1
  readonly endSide = 1
  readonly mapMode = MapMode.TrackAfter
  readonly separator: string

  constructor(separator: string) {
    super()
    this.separator = separator
  }
}

const restoreEndings = StateEffect.define<RangeSet<LineEnding>>({
  map: (endings, changes) => endings.map(changes),
})

const lineEndings = StateField.define<{ preferred: string; exceptions: RangeSet<LineEnding> }>({
  create: () => ({ preferred: '\n', exceptions: RangeSet.empty }),
  update(value, transaction) {
    if (!transaction.docChanged) return value
    let exceptions = value.exceptions.map(transaction.changes)
    for (const effect of transaction.effects) {
      if (!effect.is(restoreEndings)) continue
      const restored: Range<LineEnding>[] = []
      for (const cursor = effect.value.iter(); cursor.value; cursor.next()) {
        restored.push(cursor.value.range(cursor.from))
      }
      exceptions = exceptions.update({ add: restored })
    }
    return { preferred: value.preferred, exceptions }
  },
})

const preserveEndingsOnUndo = invertedEffects.of((transaction) => {
  const { exceptions } = transaction.startState.field(lineEndings)
  if (exceptions === RangeSet.empty) return []
  const removed: Range<LineEnding>[] = []
  transaction.changes.iterChangedRanges((from, to) => {
    exceptions.between(from, to, (position, _, ending) => {
      if (position < to) removed.push(ending.range(position))
    })
  })
  return removed.length ? [restoreEndings.of(RangeSet.of(removed, true))] : []
})

export function noteLineEndings(content: string): Extension {
  const existing = content.matchAll(/\r\n?|\n/g)
  const first = existing.next().value
  const preferred = first?.[0] ?? '\n'
  const exceptions: Range<LineEnding>[] = []
  let removedCarriageReturns = first ? first[0].length - 1 : 0
  // CodeMirror's default handling normalizes every separator to one character.
  for (const { 0: separator, index } of existing) {
    if (separator !== preferred) {
      exceptions.push(new LineEnding(separator).range(index - removedCarriageReturns))
    }
    removedCarriageReturns += separator.length - 1
  }
  return [lineEndings.init(() => ({ preferred, exceptions: RangeSet.of(exceptions) })), preserveEndingsOnUndo]
}

export function noteText(state: EditorState): string {
  const { preferred, exceptions } = state.field(lineEndings)
  const { doc } = state
  if (exceptions === RangeSet.empty) return doc.sliceString(0, doc.length, preferred)

  const cursor = exceptions.iter()
  let content = ''
  let position = 0
  for (const part = doc.iter(); !part.next().done;) {
    let value = part.value
    if (part.lineBreak) {
      value = preferred
      if (cursor.value && cursor.from === position) {
        value = cursor.value.separator
        cursor.next()
      }
      // Adjacent CR and LF must still open as two separate line breaks.
      if (value === '\n' && content.endsWith('\r')) content += '\r'
    }
    content += value
    position += part.value.length
  }
  return content
}
