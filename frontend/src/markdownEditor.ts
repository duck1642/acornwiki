import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { markdown, markdownLanguage } from '@codemirror/lang-markdown'
import {
  bracketMatching,
  ensureSyntaxTree,
  foldGutter,
  foldKeymap,
  HighlightStyle,
  indentOnInput,
  LanguageDescription,
  syntaxHighlighting,
} from '@codemirror/language'
import { languages } from '@codemirror/language-data'
import { highlightSelectionMatches, search, searchKeymap } from '@codemirror/search'
import { EditorSelection, EditorState, type Extension } from '@codemirror/state'
import { drawSelection, dropCursor, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from '@codemirror/view'
import { classHighlighter, highlightTree, tags } from '@lezer/highlight'
import { icons } from './icons'

function createFoldMarker(open: boolean): HTMLElement {
  const wrapper = document.createElement('span')
  wrapper.className = `cm-fold-chevron${open ? ' open' : ''}`
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('width', '13')
  svg.setAttribute('height', '13')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('fill', 'none')
  svg.setAttribute('stroke', 'currentColor')
  svg.setAttribute('stroke-width', '2.1')
  svg.setAttribute('stroke-linecap', 'round')
  svg.setAttribute('stroke-linejoin', 'round')
  svg.setAttribute('aria-hidden', 'true')
  // Static SVG paths from ./icons, never workspace data.
  svg.innerHTML = open ? icons['chevron-down'] : icons['chevron-right']
  wrapper.appendChild(svg)
  return wrapper
}

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

const markdownHighlightStyle = HighlightStyle.define([
  { tag: tags.heading1, color: 'var(--ink)', fontWeight: '700', fontSize: '1.58em', lineHeight: '1.35' },
  { tag: tags.heading2, color: 'var(--ink)', fontWeight: '700', fontSize: '1.3em', lineHeight: '1.4' },
  { tag: tags.heading3, color: 'var(--ink)', fontWeight: '650', fontSize: '1.14em', lineHeight: '1.45' },
  { tag: [tags.heading4, tags.heading5, tags.heading6, tags.heading], color: 'var(--ink-muted)', fontWeight: '650', fontSize: '1.04em' },
  { tag: tags.strong, color: 'var(--ink)', fontWeight: '700' },
  { tag: tags.emphasis, color: 'var(--ink)', fontStyle: 'italic' },
  { tag: tags.strikethrough, color: 'var(--ink-muted)', textDecoration: 'line-through' },
  { tag: tags.link, color: 'var(--link)', textDecoration: 'underline', textUnderlineOffset: '3px' },
  { tag: tags.url, color: 'color-mix(in srgb, var(--link) 82%, var(--ink-muted))' },
  { tag: tags.quote, color: 'var(--ink-muted)', fontStyle: 'italic' },
  { tag: tags.monospace, color: 'var(--accent)', fontFamily: 'var(--font-mono)' },
  { tag: [tags.processingInstruction, tags.punctuation, tags.meta, tags.contentSeparator, tags.brace, tags.squareBracket, tags.paren], color: 'var(--ink-faint)', fontWeight: '400' },
  { tag: [tags.list], color: 'var(--warn)' },
  { tag: [tags.keyword, tags.operator, tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword], color: 'var(--warn)' },
  { tag: [tags.typeName, tags.className, tags.namespace, tags.labelName], color: 'var(--link)' },
  { tag: [tags.string, tags.special(tags.string), tags.regexp], color: 'var(--accent)' },
  { tag: [tags.comment], color: 'var(--ink-faint)', fontStyle: 'italic' },
  { tag: [tags.number, tags.bool, tags.atom, tags.null], color: 'var(--link)' },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: 'var(--ink)', fontWeight: '600' },
  { tag: [tags.tagName], color: 'var(--warn)' },
  { tag: [tags.attributeName, tags.propertyName], color: 'var(--link)' },
  { tag: [tags.variableName, tags.attributeValue], color: 'var(--ink)' },
  { tag: [tags.invalid], color: 'var(--error)' },
])

const acornEditorTheme = EditorView.theme({
  '&': {
    color: 'var(--ink)',
    backgroundColor: 'transparent',
    fontFamily: 'var(--font-mono)',
    fontSize: 'var(--font-size-mono, 14px)',
    fontWeight: 'var(--font-weight-mono, 400)',
    lineHeight: '1.7',
  },
  '&.cm-focused': {
    outline: 'none',
  },
  '.cm-scroller': {
    overflow: 'visible',
    fontFamily: 'inherit',
    fontWeight: 'inherit',
    lineHeight: 'inherit',
  },
  '.cm-content': {
    padding: '2px 0 96px',
    caretColor: 'var(--accent)',
  },
  '.cm-line': {
    padding: '1px 2px',
  },
  '.cm-cursor, .cm-dropCursor': {
    borderLeftColor: 'var(--accent)',
    borderLeftWidth: '2px',
  },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
    backgroundColor: 'var(--bg-selection)',
  },
  '.cm-activeLine': {
    backgroundColor: 'color-mix(in srgb, var(--ink) 3.5%, transparent)',
    borderRadius: '3px',
  },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: 'var(--ink-faint)',
    borderRight: '0',
    marginRight: '6px',
  },
  '.cm-lineNumbers': {
    paddingRight: '8px',
    borderRight: '1px solid color-mix(in srgb, var(--border) 60%, transparent)',
  },
  '.cm-foldGutter': {
    width: '16px',
  },
  '.cm-foldGutter .cm-gutterElement': {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '0',
    color: 'var(--ink-faint)',
    cursor: 'pointer',
  },
  '.cm-fold-chevron': {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    opacity: '0.45',
  },
  '.cm-fold-chevron:not(.open)': {
    opacity: '0.85',
    color: 'var(--ink-muted)',
  },
  '.cm-foldGutter .cm-gutterElement:hover .cm-fold-chevron': {
    color: 'var(--ink)',
    opacity: '1',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'transparent',
    color: 'var(--ink-muted)',
  },
  '.cm-selectionMatch': {
    backgroundColor: 'color-mix(in srgb, var(--accent) 18%, transparent)',
    borderRadius: '2px',
  },
  '&.cm-focused .cm-matchingBracket, &.cm-focused .cm-nonmatchingBracket': {
    backgroundColor: 'color-mix(in srgb, var(--accent) 22%, transparent)',
    outline: '1px solid color-mix(in srgb, var(--accent) 45%, transparent)',
    borderRadius: '2px',
  },
  '.cm-foldPlaceholder': {
    backgroundColor: 'transparent',
    border: '0',
    color: 'var(--ink-faint)',
    fontSize: '0.8571rem',
    fontWeight: '400',
    letterSpacing: '0.08em',
    marginLeft: '6px',
    padding: '0 4px',
    borderRadius: '3px',
    verticalAlign: 'middle',
  },
  '.cm-foldPlaceholder:hover': {
    backgroundColor: 'var(--bg-hover)',
    color: 'var(--ink)',
  },
  '.cm-panels': {
    backgroundColor: 'var(--bg-panel)',
    color: 'var(--ink)',
    borderColor: 'var(--border)',
    borderRadius: '6px',
    marginBottom: '12px',
  },
  '.cm-panels.cm-panels-top': {
    borderBottom: '1px solid var(--border)',
  },
  '.cm-panels.cm-panels-bottom': {
    borderTop: '1px solid var(--border)',
  },
  '.cm-search': {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 10px',
    fontFamily: 'var(--font-ui)',
    fontSize: '0.8571rem',
  },
  '.cm-search input, .cm-search button': {
    fontFamily: 'var(--font-ui)',
    fontSize: '0.8214rem',
  },
  '.cm-search .cm-textfield': {
    padding: '4px 8px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    backgroundColor: 'var(--bg-app)',
    color: 'var(--ink)',
  },
  '.cm-search .cm-button': {
    padding: '4px 9px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    backgroundImage: 'none',
    backgroundColor: 'var(--bg-paper)',
    color: 'var(--ink)',
    cursor: 'pointer',
  },
  '.cm-search .cm-button:hover': {
    borderColor: 'var(--accent)',
    color: 'var(--accent)',
  },
  '.cm-search label': {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: 'var(--ink-muted)',
  },
  '.cm-search input[type="checkbox"]': {
    accentColor: 'var(--accent)',
  },
  '.cm-search [name="close"]': {
    marginLeft: 'auto',
    color: 'var(--ink-muted)',
    backgroundColor: 'transparent',
    border: '0',
    fontSize: '1.1429rem',
  },
})

export function lineNumbersExtension(enabled: boolean): Extension {
  return enabled ? [lineNumbers(), highlightActiveLineGutter()] : []
}

const PLAIN_CODE_LANGUAGES = new Set(['text', 'plaintext', 'plain', 'txt', 'none', 'raw'])

function resolveCodeLanguage(info: string): LanguageDescription | null {
  const token = info.trim().split(/\s+/)[0]
  if (!token) return null
  if (PLAIN_CODE_LANGUAGES.has(token.toLowerCase())) return null
  return LanguageDescription.matchLanguageName(languages, token, false)
    ?? (!token.includes('.') ? LanguageDescription.matchFilename(languages, `file.${token}`) : null)
}

export function createMarkdownEditorExtensions(extra: Extension[]): Extension[] {
  return [
    history(),
    drawSelection(),
    dropCursor(),
    EditorState.allowMultipleSelections.of(true),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    highlightActiveLine(),
    highlightSelectionMatches(),
    foldGutter({ markerDOM: createFoldMarker }),
    search({ top: true }),
    markdown({ base: markdownLanguage, codeLanguages: resolveCodeLanguage }),
    syntaxHighlighting(markdownHighlightStyle),
    acornEditorTheme,
    EditorView.lineWrapping,
    keymap.of([
      indentWithTab,
      ...markdownShortcuts,
      ...closeBracketsKeymap,
      ...defaultKeymap,
      ...searchKeymap,
      ...historyKeymap,
      ...foldKeymap,
    ]),
    ...extra,
  ]
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
