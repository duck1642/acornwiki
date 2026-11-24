import { markdown, markdownLanguage } from '@codemirror/lang-markdown'
import { ensureSyntaxTree } from '@codemirror/language'
import { EditorSelection, EditorState, type Extension } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { classHighlighter, highlightTree } from '@lezer/highlight'
import {
  createBaseEditorExtensions,
  lineNumbersExtension,
  resolveCodeLanguage,
  wordWrapExtension,
} from './editorCore'

export { lineNumbersExtension, wordWrapExtension }

type MarkerPositions = { opening: number; closing: number }

function resolveItalicMarkers(
  state: EditorState,
  from: number,
  to: number,
  markers: MarkerPositions,
): MarkerPositions | null {
  const { opening, closing } = markers
  if (opening + 1 === closing) return markers
  const isStar = (pos: number) => pos >= 0 && pos < state.doc.length && state.sliceDoc(pos, pos + 1) === '*'
  if (![opening - 1, opening + 1, closing - 1, closing + 1].some(isStar)) return markers

  // Markdown can assign adjacent stars to distinct emphasis and strong emphasis nodes.
  const tree = ensureSyntaxTree(state, to)
  for (let node = tree?.resolveInner(from, 1) ?? null; node; node = node.parent) {
    if (node.name !== 'Emphasis') continue
    const open = node.firstChild
    const close = node.lastChild
    if (open?.name !== 'EmphasisMark' || close?.name !== 'EmphasisMark') continue
    if (!isStar(open.from) || !isStar(close.from)) continue
    const includesMarkers = open.from === from && close.to === to
    const betweenMarkers = open.to <= from && to <= close.from
      && /^\**$/.test(state.sliceDoc(open.to, from)) && /^\**$/.test(state.sliceDoc(to, close.from))
    if (includesMarkers || betweenMarkers) return { opening: open.from, closing: close.from }
  }
  return null
}

function wrapSelection(marker: string): (view: EditorView) => boolean {
  return (view) => {
    if (view.state.readOnly) return false
    const length = marker.length
    const { state } = view
    const changes = state.changeByRange((range) => {
      const before = state.sliceDoc(Math.max(0, range.from - length), range.from)
      const after = state.sliceDoc(range.to, Math.min(state.doc.length, range.to + length))
      let markers: MarkerPositions | null = null
      if (before === marker && after === marker) {
        markers = { opening: range.from - length, closing: range.to }
      } else if (range.to - range.from >= length * 2) {
        const start = state.sliceDoc(range.from, range.from + length)
        const end = state.sliceDoc(range.to - length, range.to)
        if (start === marker && end === marker) {
          markers = { opening: range.from, closing: range.to - length }
        }
      }
      if (markers && marker === '*' && !range.empty) {
        markers = resolveItalicMarkers(state, range.from, range.to, markers)
      }
      if (markers) {
        const { opening, closing } = markers
        const changes = state.changes([
          { from: opening, to: opening + length },
          { from: closing, to: closing + length },
        ])
        return {
          changes,
          range: EditorSelection.range(changes.mapPos(range.from), changes.mapPos(range.to)),
        }
      }
      if (range.empty) {
        return {
          changes: { from: range.from, to: range.to, insert: `${marker}${marker}` },
          range: EditorSelection.cursor(range.from + length),
        }
      }
      return {
        changes: [
          { from: range.from, insert: marker },
          { from: range.to, insert: marker },
        ],
        range: EditorSelection.range(range.from + length, range.to + length),
      }
    })
    view.dispatch(changes)
    return true
  }
}

function insertLink(view: EditorView): boolean {
  if (view.state.readOnly) return false
  const changes = view.state.changeByRange((range) => {
    if (range.empty) {
      const urlStart = range.from + 7
      return {
        changes: { from: range.from, to: range.to, insert: '[link](url)' },
        range: EditorSelection.range(urlStart, urlStart + 3),
      }
    }
    const urlStart = range.to + 3
    return {
      changes: [
        { from: range.from, insert: '[' },
        { from: range.to, insert: '](url)' },
      ],
      range: EditorSelection.range(urlStart, urlStart + 3),
    }
  })
  view.dispatch(changes)
  return true
}

const markdownShortcuts = [
  { key: 'Mod-b', run: wrapSelection('**') },
  { key: 'Mod-i', run: wrapSelection('*') },
  { key: 'Mod-e', run: wrapSelection('`') },
  { key: 'Mod-k', run: insertLink },
]

export function createMarkdownEditorExtensions(extra: Extension[]): Extension[] {
  return createBaseEditorExtensions(
    [
      markdown({ base: markdownLanguage, codeLanguages: resolveCodeLanguage }),
      ...extra,
    ],
    markdownShortcuts,
  )
}

export async function highlightCodeElement(codeEl: HTMLElement, langName: string): Promise<void> {
  const desc = resolveCodeLanguage(langName)
  if (!desc) return
  const source = codeEl.textContent ?? ''
  if (!source) return
  const support = await desc.load()
  if (!codeEl.isConnected || codeEl.textContent !== source) return
  const tree = support.language.parser.parse(source)
  const fragment = document.createDocumentFragment()
  let pos = 0
  highlightTree(tree, classHighlighter, (from, to, classes) => {
    if (from > pos) fragment.appendChild(document.createTextNode(source.slice(pos, from)))
    const span = document.createElement('span')
    span.className = classes
    span.textContent = source.slice(from, to)
    fragment.appendChild(span)
    pos = to
  })
  if (pos < source.length) fragment.appendChild(document.createTextNode(source.slice(pos)))
  codeEl.replaceChildren(fragment)
}
